"""Recanto Pokémon — collection-based PvE. Server-authoritative transactions.
This module is an independent game: favorite Pokémon do not grant ownership.
External PokéAPI data is cached; no Legendary/Mythical species can spawn/capture.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import random, time, re, json, httpx
from fastapi import HTTPException, Request
from sqlalchemy import Integer, String, DateTime, ForeignKey, Boolean, Text, select, delete, func
from sqlalchemy.orm import Mapped, mapped_column

RNG = random.SystemRandom()
POKEMON_TYPES = ('normal','fire','water','electric','grass','ice','fighting','poison','ground','flying','psychic','bug','rock','ghost','dragon','dark','steel','fairy')
STARTERS = {1:('Bulbasaur','grass'),4:('Charmander','fire'),7:('Squirtle','water'),
 152:('Chikorita','grass'),155:('Cyndaquil','fire'),158:('Totodile','water'),
 252:('Treecko','grass'),255:('Torchic','fire'),258:('Mudkip','water'),
 387:('Turtwig','grass'),390:('Chimchar','fire'),393:('Piplup','water'),
 495:('Snivy','grass'),498:('Tepig','fire'),501:('Oshawott','water'),
 650:('Chespin','grass'),653:('Fennekin','fire'),656:('Froakie','water'),
 722:('Rowlet','grass'),725:('Litten','fire'),728:('Popplio','water'),
 810:('Grookey','grass'),813:('Scorbunny','fire'),816:('Sobble','water'),
 906:('Sprigatito','grass'),909:('Fuecoco','fire'),912:('Quaxly','water')}
BALLS={'pokebola': {'name':'Pokébola','price':35,'chance':35,'emoji':'🔴'},
       'superbola':{'name':'Superbola','price':80,'chance':55,'emoji':'🔵'},
       'ultrabola':{'name':'Ultrabola','price':155,'chance':75,'emoji':'🟡'}}
ITEMS={**BALLS,'cura':{'name':'Poção','price':90,'emoji':'💊'},'evolucao':{'name':'Pedra de Evolução','price':175,'emoji':'💎'},'racao':{'name':'Ração Pokémon','price':30,'emoji':'🍓'}}
DEFAULT_SETTINGS={'encounter_min_minutes':25,'encounter_max_minutes':55,'encounter_duration_minutes':3,
    'encounter_attempts':2,'starter_balls':5,'hospital_minutes':45,'illness_chance':8,
    'expedition_minutes':40,'expedition_coins_min':20,'expedition_coins_max':55,
    'expedition_card_chance':12,'expedition_collectible_chance':4,
    'boss_cooldown_minutes':90,'max_pokemon':120,'shiny_odds':4096}


def define_models(Base):
    class PokemonAccount(Base):
        __tablename__='recanto_pokemon_accounts'
        user_id:Mapped[str]=mapped_column(ForeignKey('users.id'),primary_key=True)
        starter_id:Mapped[int]=mapped_column(Integer,nullable=False)
        next_encounter:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
        next_boss:Mapped[datetime | None]=mapped_column(DateTime(timezone=True),nullable=True)

    class OwnedPokemon(Base):
        __tablename__='recanto_pokemon_owned'
        id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
        user_id:Mapped[str]=mapped_column(ForeignKey('users.id'),nullable=False,index=True)
        species_id:Mapped[int]=mapped_column(Integer,nullable=False)
        slug:Mapped[str]=mapped_column(String(90),nullable=False)
        name:Mapped[str]=mapped_column(String(100),nullable=False)
        types:Mapped[str]=mapped_column(String(100),nullable=False,default='normal')
        level:Mapped[int]=mapped_column(Integer,default=5,nullable=False)
        xp:Mapped[int]=mapped_column(Integer,default=0,nullable=False)
        position:Mapped[int]=mapped_column(Integer,default=0,nullable=False)
        status:Mapped[str]=mapped_column(String(20),default='healthy',nullable=False)
        ready_at:Mapped[datetime | None]=mapped_column(DateTime(timezone=True),nullable=True)
        obtained_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
        gender:Mapped[str]=mapped_column(String(16),nullable=False,default='unknown',server_default='unknown')
        shiny:Mapped[bool]=mapped_column(Boolean,nullable=False,default=False,server_default='false')

    class PokemonItem(Base):
        __tablename__='recanto_pokemon_items'
        user_id:Mapped[str]=mapped_column(ForeignKey('users.id'),primary_key=True)
        sku:Mapped[str]=mapped_column(String(30),primary_key=True)
        quantity:Mapped[int]=mapped_column(Integer,default=0,nullable=False)

    class PokemonEncounter(Base):
        __tablename__='recanto_pokemon_encounters'
        user_id:Mapped[str]=mapped_column(ForeignKey('users.id'),primary_key=True)
        species_id:Mapped[int]=mapped_column(Integer,nullable=False)
        slug:Mapped[str]=mapped_column(String(90),nullable=False)
        name:Mapped[str]=mapped_column(String(100),nullable=False)
        types:Mapped[str]=mapped_column(String(100),nullable=False)
        capture_rate:Mapped[int]=mapped_column(Integer,nullable=False,default=100)
        level:Mapped[int]=mapped_column(Integer,nullable=False)
        attempts:Mapped[int]=mapped_column(Integer,nullable=False,default=0)
        expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
        gender:Mapped[str]=mapped_column(String(16),nullable=False,default='unknown',server_default='unknown')
        shiny:Mapped[bool]=mapped_column(Boolean,nullable=False,default=False,server_default='false')

    class PokemonFeedLog(Base):
        # Alimentação tem intervalo por Pokémon; não depende do dispositivo.
        __tablename__='recanto_pokemon_feeds'
        pokemon_id:Mapped[int]=mapped_column(ForeignKey('recanto_pokemon_owned.id'),primary_key=True)
        last_fed_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

    class PokemonCaptureAttempt(Base):
        # Rolling window enforced across encounters, devices and sessions.
        __tablename__='recanto_pokemon_capture_attempts'
        id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
        user_id:Mapped[str]=mapped_column(ForeignKey('users.id'),nullable=False,index=True)
        attempted_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)

    class PokemonExpedition(Base):
        __tablename__='recanto_pokemon_expeditions'
        user_id:Mapped[str]=mapped_column(ForeignKey('users.id'),primary_key=True)
        config_id:Mapped[int]=mapped_column(Integer,nullable=False)
        member_ids:Mapped[str]=mapped_column(String(256),nullable=False)
        expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
        coins:Mapped[int]=mapped_column(Integer,nullable=False)
        card_roll:Mapped[bool]=mapped_column(Boolean,default=False)
        collectible_roll:Mapped[bool]=mapped_column(Boolean,default=False)

    class PokemonExpeditionConfig(Base):
        __tablename__='recanto_pokemon_expedition_configs'
        id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
        name:Mapped[str]=mapped_column(String(90),nullable=False)
        required_type:Mapped[str]=mapped_column(String(30),nullable=False,default='any')
        required_count:Mapped[int]=mapped_column(Integer,default=1,nullable=False)
        minutes:Mapped[int]=mapped_column(Integer,default=40,nullable=False)
        min_coins:Mapped[int]=mapped_column(Integer,default=20,nullable=False)
        max_coins:Mapped[int]=mapped_column(Integer,default=55,nullable=False)
        card_chance:Mapped[int]=mapped_column(Integer,default=10,nullable=False)
        collectible_chance:Mapped[int]=mapped_column(Integer,default=4,nullable=False)
        active:Mapped[bool]=mapped_column(Boolean,default=True,nullable=False)

    class PokemonBoss(Base):
        __tablename__='recanto_pokemon_bosses'
        id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
        name:Mapped[str]=mapped_column(String(90),nullable=False)
        species_id:Mapped[int]=mapped_column(Integer,nullable=False,default=25)
        level:Mapped[int]=mapped_column(Integer,default=15,nullable=False)
        reward_coins:Mapped[int]=mapped_column(Integer,default=80,nullable=False)
        active:Mapped[bool]=mapped_column(Boolean,default=True,nullable=False)

    class PokemonBossDesign(Base):
        """Optional battle presentation/party/reward config. Additive table, no existing boss migration."""
        __tablename__='recanto_pokemon_boss_designs'
        boss_id:Mapped[int]=mapped_column(Integer,primary_key=True)
        payload:Mapped[str]=mapped_column(Text,nullable=False,default='{}')

    class PokemonMoveConfig(Base):
        __tablename__='recanto_pokemon_move_configs'
        species_id:Mapped[int]=mapped_column(Integer,primary_key=True)
        payload:Mapped[str]=mapped_column(Text,nullable=False,default='[]')

    class PokemonTrade(Base):
        __tablename__='recanto_pokemon_trades'
        id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
        sender_id:Mapped[str]=mapped_column(ForeignKey('users.id'),nullable=False)
        receiver_id:Mapped[str]=mapped_column(ForeignKey('users.id'),nullable=False)
        offered_id:Mapped[int]=mapped_column(Integer,nullable=False)
        wanted_id:Mapped[int]=mapped_column(Integer,nullable=False)
        status:Mapped[str]=mapped_column(String(18),nullable=False,default='pending')
        created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

    class PokemonSetting(Base):
        __tablename__='recanto_pokemon_settings'
        key:Mapped[str]=mapped_column(String(50),primary_key=True)
        value:Mapped[int]=mapped_column(Integer,nullable=False)
    return dict(Account=PokemonAccount,Owned=OwnedPokemon,Item=PokemonItem,Encounter=PokemonEncounter,
      CaptureAttempt=PokemonCaptureAttempt,FeedLog=PokemonFeedLog,Expedition=PokemonExpedition,ExpeditionConfig=PokemonExpeditionConfig,Boss=PokemonBoss,BossDesign=PokemonBossDesign,MoveConfig=PokemonMoveConfig,Trade=PokemonTrade,Setting=PokemonSetting)


def register_routes(*,app,models,SessionLocal,me,only_admin,writing,utcnow,naive_to_utc,pokemon_catalog,
        pokemon_entry,wallet,require_coins,publish_feed,stock,grant_card,Card,Collectible,InventoryCollectible,
        pokemon_generation,feed_card,progress,UIAsset,safe_artwork):
    M=models
    _species_cache={}
    _pokemon_type_cache={}
    _poke_client=httpx.Client(timeout=httpx.Timeout(6.0, connect=3.0),follow_redirects=True,limits=httpx.Limits(max_connections=8,max_keepalive_connections=4))
    def type_backgrounds(db):
        return {row.key[len('pokemon-bg-'):]:row.image_url for row in db.scalars(select(UIAsset).where(UIAsset.key.like('pokemon-bg-%'))).all() if row.key[len('pokemon-bg-'):] in POKEMON_TYPES}
    SPRITE_KEY_RE=re.compile(r'^pokemon-sprite:(\d{1,4}):(wild|owned|back):(any|male|female|unknown):(normal|shiny)$')
    def sprite_overrides(db):
        result={}
        for row in db.scalars(select(UIAsset).where(UIAsset.key.like('pokemon-sprite:%'))).all():
            match=SPRITE_KEY_RE.fullmatch(row.key)
            if match and int(match.group(1))<=1025 and row.image_url:
                result[':'.join(match.groups())]=row.image_url
        return result
    def media_assets(db):
        return {r.key:r.image_url for r in db.scalars(select(UIAsset).where(
            (UIAsset.key.like('pokemon-item-%')) | (UIAsset.key=='pokemon-nurse-joy'))).all()}
    def boss_design(db,bid):
        row=db.get(M['BossDesign'],bid)
        if row:
            try:return json.loads(row.payload)
            except (ValueError,TypeError):pass
        return {}
    def clean_url(raw,audio=False):
        if raw is None or str(raw).strip()=='':return ''
        url=str(raw).strip()
        if len(url)>500 or not (url.startswith('https://') or url.startswith('/uploads/')):
            raise HTTPException(422,detail='Use um endereço HTTPS ou arquivo enviado pelo Recanto')
        if not audio:return safe_artwork(url)
        if not re.search(r'\.(mp3|ogg|wav|m4a)(?:[?#]|$)',url,re.I):
            raise HTTPException(422,detail='Áudio deve ser MP3, OGG, WAV ou M4A')
        return url

    def draw_gender(rate):
        # Official gender_rate represents female probability in eighths; -1 = undefined.
        if rate == -1:return 'unknown'
        rate=max(0,min(8,int(rate)))
        return 'female' if RNG.randrange(8)<rate else 'male'
    def draw_shiny(db):
        return RNG.randrange(max(1,params(db,'shiny_odds')))==0
    def now():return utcnow()
    def norm_date(v):return naive_to_utc(v) if v else None
    def verify_int(raw,lo,hi,label):
        if type(raw) is not int or not lo<=raw<=hi:raise HTTPException(422,detail=f'{label}: valor inválido')
        return raw
    def params(db,key):
        if key=='encounter_duration_minutes':return 3
        if key=='encounter_attempts':return 2
        row=db.get(M['Setting'],key)
        return row.value if row else DEFAULT_SETTINGS[key]
    def flags(species_id):
        n=verify_int(species_id,1,1025,'Espécie')
        cached=_species_cache.get(n)
        if cached and cached[1]>time.monotonic():return cached[0]
        try:
            response=_poke_client.get(f'https://pokeapi.co/api/v2/pokemon-species/{n}/')
            response.raise_for_status();obj=response.json()
            data={'legendary':bool(obj.get('is_legendary')),'mythical':bool(obj.get('is_mythical')),
                  'capture_rate':int(obj.get('capture_rate') or 45),'gender_rate':int(obj.get('gender_rate',-1)),'evolution_chain':obj.get('evolution_chain',{}).get('url')}
            _species_cache[n]=(data,time.monotonic()+86400*7)
            return data
        except (httpx.HTTPError,KeyError,TypeError,ValueError) as e:
            raise HTTPException(503,detail='Não foi possível verificar os dados oficiais do Pokémon. Tente novamente.') from e
    def get_types(n):
        cached=_pokemon_type_cache.get(n)
        if cached and cached[1]>time.monotonic():return cached[0]
        try:
            response=_poke_client.get(f'https://pokeapi.co/api/v2/pokemon/{n}/');response.raise_for_status()
            types=[r['type']['name'] for r in sorted(response.json().get('types',[]),key=lambda e:int(e.get('slot',99))) if 'type' in r]
            if not types:raise ValueError('sem tipos')
            _pokemon_type_cache[n]=(types,time.monotonic()+86400*7)
            return types
        except (httpx.HTTPError,KeyError,TypeError,ValueError):
            if n in STARTERS:return [STARTERS[n][1]]
            raise HTTPException(503,detail='Tipos do Pokémon indisponíveis. Tente novamente.')
    def owned_json(p):
        return {'id':p.id,'species_id':p.species_id,'name':p.name,'slug':p.slug,
          'image_url':f'https://img.pokemondb.net/sprites/home/normal/{p.slug}.png',
          'generation':pokemon_generation(p.species_id),'types':p.types.split(','),
          'gender':p.gender,'shiny':bool(p.shiny),
          'level':p.level,'xp':p.xp,'xp_next':p.level*12,'position':p.position,
          'status':p.status,'ready_at':norm_date(p.ready_at).isoformat() if p.ready_at else None}
    def owned(db,uid):return db.scalars(select(M['Owned']).where(M['Owned'].user_id==uid).order_by(M['Owned'].position,M['Owned'].id)).all()
    def item_counts(db,uid):return {row.sku:row.quantity for row in db.scalars(select(M['Item']).where(M['Item'].user_id==uid)).all()}
    def item_change(db,uid,sku,change):
        if sku not in ITEMS:raise HTTPException(422,detail='Item desconhecido')
        row=db.get(M['Item'],(uid,sku));qty=(row.quantity if row else 0)+change
        if qty<0:raise HTTPException(409,detail='Você não possui esse item de Pokémon')
        if not row:db.add(M['Item'](user_id=uid,sku=sku,quantity=qty))
        else:row.quantity=qty
    CAPTURE_WINDOW=timedelta(minutes=10)
    CAPTURE_LIMIT=2
    ENCOUNTER_LIFETIME=timedelta(minutes=3)
    def capture_status(db,uid,at=None):
        at=at or now()
        # Do not depend on having Pokébolas: attempts are only recorded on throws.
        recent=db.scalars(select(M['CaptureAttempt'].attempted_at).where(
            M['CaptureAttempt'].user_id==uid,
            M['CaptureAttempt'].attempted_at>at-CAPTURE_WINDOW
        ).order_by(M['CaptureAttempt'].attempted_at)).all()
        allowed=max(0,CAPTURE_LIMIT-len(recent))
        return {'remaining':allowed,'limit':CAPTURE_LIMIT,'window_minutes':10,
                'next_at':(norm_date(recent[0])+CAPTURE_WINDOW).isoformat() if recent and not allowed else None}

    def encounter_json(row):
        return {'name':row.name,'species_id':row.species_id,'slug':row.slug,'types':row.types.split(','),
          'image_url':f'https://img.pokemondb.net/sprites/home/normal/{row.slug}.png',
          'level':row.level,'gender':row.gender,'shiny':bool(row.shiny),
          'attempts':row.attempts,'expires_at':norm_date(row.expires_at).isoformat()}
    def get_pokemon(db,uid,id,action=True):
        obj=db.get(M['Owned'],id)
        if not obj or obj.user_id!=uid:raise HTTPException(404,detail='Pokémon não encontrado')
        if action and obj.status!='healthy':raise HTTPException(409,detail='Este Pokémon está em expedição ou na enfermaria')
        return obj
    def award_xp(db,p,points):
        p.xp+=points
        while p.xp>=p.level*12 and p.level<100:
            p.xp-=p.level*12;p.level+=1
    def team(db,uid):
        return [p for p in owned(db,uid) if p.position>0 and p.status=='healthy']
    def get_exp_config(db):
        configs=db.scalars(select(M['ExpeditionConfig']).order_by(M['ExpeditionConfig'].id)).all()
        if configs:return configs
        return []
    def config_json(x):return {'id':x.id,'name':x.name,'required_type':x.required_type,
      'required_count':x.required_count,'minutes':x.minutes,'min_coins':x.min_coins,'max_coins':x.max_coins,
      'card_chance':x.card_chance,'collectible_chance':x.collectible_chance,'active':x.active}
    def boss_json(x):return {'id':x.id,'name':x.name,'species_id':x.species_id,'level':x.level,
      'reward_coins':x.reward_coins,'active':x.active}
    def enriched_boss(db,x):
        return {**boss_json(x),**boss_design(db,x.id)}
    BATTLE_MOVES={
        'normal':('Investida',40),'fire':('Brasas',40),'water':('Jato d’Água',40),
        'grass':('Chicote de Vinha',45),'electric':('Choque do Trovão',40),
        'ice':('Vento Gelado',45),'fighting':('Soco Karate',50),
        'poison':('Ferrão Venenoso',45),'ground':('Tiro de Lama',45),
        'flying':('Ataque de Asa',55),'psychic':('Confusão',50),
        'bug':('Picada',45),'rock':('Lançamento de Rocha',50),
        'ghost':('Lambida',40),'dragon':('Sopro do Dragão',55),
        'dark':('Mordida',55),'steel':('Garra de Metal',50),
        'fairy':('Vento de Fada',45)}
    STRONG={
        'fire':('grass','bug','ice','steel'), 'water':('fire','ground','rock'),
        'grass':('water','ground','rock'), 'electric':('water','flying'),
        'ice':('grass','ground','flying','dragon'), 'fighting':('normal','ice','rock','dark','steel'),
        'poison':('grass','fairy'), 'ground':('fire','electric','poison','rock','steel'),
        'flying':('grass','fighting','bug'), 'psychic':('fighting','poison'),
        'bug':('grass','psychic','dark'), 'rock':('fire','ice','flying','bug'),
        'ghost':('psychic','ghost'), 'dragon':('dragon',), 'dark':('psychic','ghost'),
        'steel':('ice','rock','fairy'), 'fairy':('fighting','dragon','dark')}
    WEAK={'fire':('water','rock','fire','dragon'), 'water':('grass','water','dragon'),
        'grass':('fire','grass','poison','flying','bug','dragon','steel'),
        'electric':('electric','grass','dragon','ground'),
        'normal':('rock','steel','ghost'), 'fighting':('poison','flying','psychic','bug','fairy','ghost'),
        'ghost':('dark','normal'), 'dragon':('steel','fairy')}
    def make_unit(db,unit_id,owned_p=None,enemy=None,boss=False):
        if owned_p:
            level=int(owned_p.level);types=owned_p.types.split(',')
            name=owned_p.name;species=int(owned_p.species_id);position=owned_p.position
            gender=owned_p.gender;shiny=bool(owned_p.shiny)
        else:
            level=int(enemy.get('level',15));types=enemy.get('types',['normal']) or ['normal']
            types=[t for t in types if t in POKEMON_TYPES] or ['normal']
            name=enemy.get('name') or 'Pokémon';species=int(enemy.get('species_id',25));position=int(enemy.get('position',2))
            gender='unknown';shiny=False
        hp=round(55+level*5.2+(15 if boss else 0))
        return {'id':unit_id,'name':name,'species_id':species,'level':level,'types':types,'position':position,
            'gender':gender,'shiny':shiny,'boss':boss,'max_hp':hp,'hp':hp,
            'attack':round(18+level*1.8),'defense':round(14+level*1.5),
            'speed':round(15+level*1.7),'moves':move_config_for_species(db,species,types),'statuses':{}}
    def simulate_battle(db,pokemon,boss,design):
        friends=[make_unit(db,'p-'+str(p.id),owned_p=p) for p in pokemon]
        enemies=[]
        helpers=design.get('helpers',[])[:5]
        for idx,h in enumerate(helpers):
            enemies.append(make_unit(db,'h-'+str(idx),enemy=h))
        enemies.append(make_unit(db,'boss-'+str(boss.id),enemy={
            'name':boss.name,'species_id':boss.species_id,'level':boss.level,
            'types':[design.get('type','normal')],'position':design.get('boss_position',2)},boss=True))
        initial={'allies':[{k:v for k,v in u.items() if k not in ('attack','defense','speed','moves','statuses')} for u in friends],
                 'enemies':[{k:v for k,v in u.items() if k not in ('attack','defense','speed','moves','statuses')} for u in enemies]}
        events=[];won=False
        def status_tick(unit,turn):
            statuses=unit.get('statuses',{})
            for key,label,mult in (('burn','Queimadura',0.06),('poison','Veneno',0.05)):
                if statuses.get(key,0)>0 and unit['hp']>0:
                    damage=max(1,round(unit['max_hp']*mult))
                    unit['hp']=max(0,unit['hp']-damage)
                    statuses[key]-=1
                    events.append({'kind':'status_damage','round':turn,'actor':unit['id'],'target':unit['id'],'label':label,'damage':damage,'hp':unit['hp']})
            if statuses.get('paralyze',0)>0 and unit['hp']>0:
                statuses['paralyze']-=1
                if RNG.randrange(100)<45:
                    events.append({'kind':'skip','round':turn,'actor':unit['id'],'target':unit['id'],'label':'Paralisia'})
                    return True
            return False
        for turn in range(1,19):
            living=[u for u in friends+enemies if u['hp']>0]
            living.sort(key=lambda u:u['speed']+RNG.randrange(-6,7),reverse=True)
            for actor in living:
                if actor['hp']<=0:continue
                if status_tick(actor,turn):
                    continue
                if actor['hp']<=0:continue
                side=enemies if actor in friends else friends
                targets=[t for t in side if t['hp']>0]
                if not targets:break
                front=[t for t in targets if t['position']<=3]
                target=RNG.choice(front or targets)
                move=RNG.choice(actor.get('moves') or default_moves_for_types(actor.get('types')))
                atype=move.get('type') if move.get('type') in POKEMON_TYPES else (actor['types'][0] if actor['types'] else 'normal')
                name=move.get('name') or BATTLE_MOVES.get(atype,BATTLE_MOVES['normal'])[0]
                power=int(move.get('power') or BATTLE_MOVES.get(atype,BATTLE_MOVES['normal'])[1])
                effect=str(move.get('effect') or 'none')
                factor=1.0
                for defense_type in target['types']:
                    if defense_type in STRONG.get(atype,()):factor*=1.6
                    if defense_type in WEAK.get(atype,()):factor*=0.65
                critical=RNG.randrange(100)<8
                damage=max(0,round((actor['attack']+power*.30)*(.80+RNG.random()*.4)
                    /(1+target['defense']/65)*factor*(1.5 if critical else 1)))
                if power<=0: damage=0
                target['hp']=max(0,target['hp']-damage)
                event={'kind':'attack','round':turn,'actor':actor['id'],'target':target['id'],'move':name,
                    'type':atype,'damage':damage,'hp':target['hp'],'critical':critical,'effectiveness':round(factor,2)}
                if effect in ('burn','poison','paralyze') and target['hp']>0 and RNG.randrange(100)<35:
                    target['statuses'][effect]=max(target['statuses'].get(effect,0),2)
                    event['effect_text']={'burn':'Queimadura','poison':'Veneno','paralyze':'Paralisia'}[effect]
                elif effect=='heal':
                    heal=max(8,round(actor['max_hp']*0.12))
                    actor['hp']=min(actor['max_hp'],actor['hp']+heal)
                    event['self_hp']=actor['hp'];event['heal']=heal;event['effect_text']='Cura'
                elif effect=='drain' and damage>0:
                    heal=max(5,round(damage*0.4))
                    actor['hp']=min(actor['max_hp'],actor['hp']+heal)
                    event['self_hp']=actor['hp'];event['heal']=heal;event['effect_text']='Drenou energia'
                events.append(event)
            if not any(u['hp']>0 for u in enemies):won=True;break
            if not any(u['hp']>0 for u in friends):break
        return initial,events,won


    def enriched_boss_from_values(boss,design):
        return {**boss_json(boss),**design}
    def set_illness(db,people):
        changed=[]
        for p in people:
            if RNG.randrange(100)<params(db,'illness_chance'):
                p.status='sick';changed.append(p.name)
        return changed
    def note(db,uid,kind,**payload):publish_feed(db,uid,kind,**payload)
    @app.get('/api/pokemon/adventure')
    def adventure(request:Request):
        uid=me(request)
        with SessionLocal() as db:
            acct=db.get(M['Account'],uid)
            if not acct:return {'started':False,'sprite_overrides':sprite_overrides(db),'starters':[{'id':i,'name':n,'type':t,'generation':pokemon_generation(i),
                'image_url':f'https://img.pokemondb.net/sprites/home/normal/{n.lower()}.png'} for i,(n,t) in STARTERS.items()]}
            encounter=db.get(M['Encounter'],uid)
            if encounter and norm_date(encounter.expires_at)<=now():encounter=None
            expedition=db.get(M['Expedition'],uid)
            configs=[config_json(c) for c in get_exp_config(db) if c.active]
            bosses=[enriched_boss(db,b) for b in db.scalars(select(M['Boss']).where(M['Boss'].active.is_(True))).all()]
            # Uma única consulta traz todos os preços, evitando N consultas por item.
            prices={row.key:row.value for row in db.scalars(select(M['Setting']).where(M['Setting'].key.like('item_price_%'))).all()}
            return {'started':True,'owned':[owned_json(p) for p in owned(db,uid)],
             'items':item_counts(db,uid),'shop':[{**data,'sku':sku,'price':prices.get('item_price_'+sku,data['price'])} for sku,data in ITEMS.items()],
             'capture_backgrounds':type_backgrounds(db),'sprite_overrides':sprite_overrides(db),'media_assets':media_assets(db),
             'encounter':encounter_json(encounter) if encounter else None,
             'capture_limit':capture_status(db,uid),
             'next_encounter':norm_date(acct.next_encounter).isoformat(),
             'next_boss':norm_date(acct.next_boss).isoformat() if acct.next_boss else None,
             'expedition':{'ends_at':norm_date(expedition.expires_at).isoformat(),'team':json.loads(expedition.member_ids),
                           'config_id':expedition.config_id} if expedition else None,
             'expedition_options':configs,'bosses':bosses,'starter_id':acct.starter_id,
             'settings':{'max_pokemon':params(db,'max_pokemon')}}
    @app.post('/api/pokemon/adventure/start')
    async def starter(request:Request):
        uid=me(request);data=await request.json();sid=data.get('species_id')
        if type(sid) is not int or sid not in STARTERS:raise HTTPException(422,detail='Escolha um inicial entre as 9 gerações')
        name,kind=STARTERS[sid]
        # Starter species always have a 1/8 female rate; no external HTTP on onboarding.
        gender=draw_gender(1)
        with writing() as db:
            if db.get(M['Account'],uid):raise HTTPException(409,detail='Você já escolheu seu Pokémon inicial')
            record=M['Owned'](user_id=uid,species_id=sid,name=name,slug=name.lower(),types=kind,
                level=5,xp=0,position=1,status='healthy',obtained_at=now(),
                gender=gender,shiny=draw_shiny(db))
            db.add(M['Account'](user_id=uid,starter_id=sid,next_encounter=now()+timedelta(minutes=RNG.randint(3,8))))
            db.add(record);item_change(db,uid,'pokebola',params(db,'starter_balls'))
            progress(db,uid,'pokemon_starter')
            note(db,uid,'pokemon_starter',pokemon={'name':name,'slug':name.lower(),'species_id':sid,'gender':record.gender,'shiny':record.shiny})
        return {'ok':True}
    @app.post('/api/pokemon/adventure/seek')
    def seek(request:Request):
        uid=me(request)
        # HTTP access happens outside the transaction to avoid locking users during slow PokéAPI calls.
        with SessionLocal() as db:
            acct=db.get(M['Account'],uid)
            if not acct:raise HTTPException(409,detail='Escolha um inicial primeiro')
            if norm_date(acct.next_encounter)>now():raise HTTPException(409,detail='Ainda não chegou a hora de um encontro selvagem')
            found=db.get(M['Encounter'],uid)
            if found and norm_date(found.expires_at)>now():return {'encounter':encounter_json(found)}
        catalog=pokemon_catalog()
        # Verify every encountered species with official is_legendary/is_mythical flags.
        entry=None;spec=None
        for _ in range(12):
            possible=RNG.choice(catalog)
            spec=flags(possible['id'])
            if not spec['legendary'] and not spec['mythical']:
                entry=possible;break
        if not entry:raise HTTPException(503,detail='Não foi possível gerar um encontro válido')
        types=get_types(entry['id']);created=None
        with writing() as db:
            acct=db.get(M['Account'],uid)
            if norm_date(acct.next_encounter)>now():
                current=db.get(M['Encounter'],uid)
                if current and norm_date(current.expires_at)>now():return {'encounter':encounter_json(current)}
                raise HTTPException(409,detail='Encontro já processado')
            previous=db.get(M['Encounter'],uid)
            if previous:db.delete(previous);db.flush()
            created=M['Encounter'](user_id=uid,species_id=entry['id'],slug=entry['slug'],name=entry['name'],types=','.join(types),
                capture_rate=spec['capture_rate'],level=RNG.randint(3,14),attempts=0,
                expires_at=now()+ENCOUNTER_LIFETIME,gender=draw_gender(spec['gender_rate']),
                shiny=draw_shiny(db))
            db.add(created)
            acct.next_encounter=now()+timedelta(minutes=RNG.randint(params(db,'encounter_min_minutes'),params(db,'encounter_max_minutes')))
        return {'encounter':encounter_json(created)}
    @app.post('/api/pokemon/adventure/catch')
    async def catch(request:Request):
        uid=me(request);data=await request.json();ball=str(data.get('ball',''))
        if ball not in BALLS:raise HTTPException(422,detail='Selecione uma Pokébola válida')
        with writing() as db:
            encounter=db.get(M['Encounter'],uid)
            if not encounter or norm_date(encounter.expires_at)<=now():raise HTTPException(409,detail='O Pokémon selvagem já foi embora')
            if len(owned(db,uid))>=params(db,'max_pokemon'):raise HTTPException(409,detail='Sua coleção atingiu o limite de Pokémon')
            # Serialize requests for the same account before checking the global
            # ten-minute quota (prevents simultaneous requests on different devices).
            account=db.scalar(select(M['Account']).where(M['Account'].user_id==uid).with_for_update())
            if not account:raise HTTPException(409,detail='Escolha um Pokémon inicial')
            quota=capture_status(db,uid)
            if quota['remaining']<=0:
                raise HTTPException(429,detail='Limite de 2 tentativas a cada 10 minutos. Aguarde o próximo intervalo.')
            item_change(db,uid,ball,-1)
            db.add(M['CaptureAttempt'](user_id=uid,attempted_at=now()))
            # Species capture_rate influences but cannot exceed the configured ball chance.
            chance=max(4,round((db.get(M['Setting'],'ball_chance_'+ball).value if db.get(M['Setting'],'ball_chance_'+ball) else BALLS[ball]['chance'])*(0.35+0.65*min(encounter.capture_rate,255)/255)))
            success=RNG.randrange(100)<chance
            encounter.attempts+=1
            escaped=encounter.attempts>=min(2,params(db,'encounter_attempts'))
            if success:
                p=M['Owned'](user_id=uid,species_id=encounter.species_id,name=encounter.name,slug=encounter.slug,
                    types=encounter.types,level=encounter.level,xp=0,position=0,status='healthy',obtained_at=now(),
                    gender=encounter.gender,shiny=encounter.shiny)
                db.add(p);db.delete(encounter)
                progress(db,uid,'pokemon_catch')
                for kind in set(encounter.types.split(',')):
                    if kind in ('normal','fire','water','electric','grass','ice','fighting',
                                'poison','ground','flying','psychic','bug','rock','ghost',
                                'dragon','dark','steel','fairy'):
                        progress(db,uid,'pokemon_catch_type_'+kind)
                note(db,uid,'pokemon_catch',pokemon={'name':p.name,'slug':p.slug,'species_id':p.species_id,'gender':p.gender,'shiny':p.shiny})
            elif escaped:
                db.delete(encounter)
        return {'ok':True,'caught':success,'escaped':escaped if not success else False,'chance':chance}
    @app.post('/api/pokemon/adventure/team')
    async def choose_team(request:Request):
        uid=me(request);data=await request.json();ids=data.get('ids')
        if not isinstance(ids,list) or len(ids)>6 or len(set(map(str,ids)))!=len(ids) or any(type(i) is not int for i in ids):
            raise HTTPException(422,detail='Escolha até seis Pokémon diferentes')
        with writing() as db:
            all_owned=owned(db,uid)
            selected={p.id:p for p in all_owned}
            if any(id not in selected or selected[id].status!='healthy' for id in ids):raise HTTPException(409,detail='A equipe tem Pokémon indisponível')
            for p in all_owned:p.position=(ids.index(p.id)+1) if p.id in ids else 0
        return {'ok':True}
    @app.post('/api/pokemon/adventure/shop')
    async def purchase_item(request:Request):
        uid=me(request);data=await request.json();sku=str(data.get('sku',''));qty=data.get('quantity',1)
        verify_int(qty,1,30,'Quantidade')
        if sku not in ITEMS:raise HTTPException(422,detail='Item inválido')
        with writing() as db:
            row=db.get(M['Setting'],'item_price_'+sku)
            cost=(row.value if row else ITEMS[sku]['price'])*qty
            require_coins(db,uid,cost).coins-=cost
            item_change(db,uid,sku,qty)
            new_balance=wallet(db,uid).coins
        return {'ok':True,'coins_balance':new_balance}
    @app.post('/api/pokemon/adventure/use-item')
    async def use_item(request:Request):
        uid=me(request);data=await request.json();id=verify_int(data.get('id'),1,100000000,'Pokémon')
        sku=str(data.get('sku',''))
        if sku not in ('cura','racao'):
            raise HTTPException(422,detail='Item inválido para cuidar de Pokémon')
        with writing() as db:
            p=get_pokemon(db,uid,id,action=False)
            if sku=='cura':
                if p.status not in ('sick','hospital'):
                    raise HTTPException(409,detail='Este Pokémon não está doente')
                item_change(db,uid,sku,-1)
                p.status='healthy';p.ready_at=None
                progress(db,uid,'pokemon_heal')
            else:
                if p.status!='healthy':
                    raise HTTPException(409,detail='Alimente apenas Pokémon saudáveis e disponíveis')
                last=db.get(M['FeedLog'],p.id)
                at=now()
                if last and norm_date(last.last_fed_at)+timedelta(hours=6)>at:
                    raise HTTPException(409,detail='Este Pokémon pode ser alimentado novamente após 6 horas')
                item_change(db,uid,sku,-1)
                award_xp(db,p,6)
                if last:last.last_fed_at=at
                else:db.add(M['FeedLog'](pokemon_id=p.id,last_fed_at=at))
                progress(db,uid,'pokemon_feed')
        return {'ok':True}

    @app.post('/api/pokemon/adventure/evolve')
    async def evolve(request:Request):
        uid=me(request);data=await request.json();id=data.get('id');verify_int(id,1,100000000,'Pokémon')
        with SessionLocal() as db:
            p=get_pokemon(db,uid,id)
            sid=p.species_id;level=p.level
        # Official evolution tree, cached by species metadata endpoint.
        detail=flags(sid)
        if not detail.get('evolution_chain'):raise HTTPException(409,detail='Este Pokémon não possui evolução')
        try:
            chain=httpx.get(detail['evolution_chain'],timeout=8);chain.raise_for_status()
            chain=chain.json()['chain']
        except (httpx.HTTPError,KeyError,TypeError) as e:raise HTTPException(503,detail='Evoluções indisponíveis') from e
        def children(node):
            if node['species']['name']==p.slug:return node.get('evolves_to',[])
            for c in node.get('evolves_to',[]):
                result=children(c)
                if result is not None:return result
            return None
        options=children(chain) or []
        if not options:raise HTTPException(409,detail='Este Pokémon está na evolução final')
        target=options[0]
        detail_evo=target.get('evolution_details') or [{}]
        trigger=(detail_evo[0].get('trigger') or {}).get('name','level-up')
        needs_stone=trigger=='use-item'
        min_level=detail_evo[0].get('min_level') or 16
        if not needs_stone and level<min_level:raise HTTPException(409,detail=f'Evolução liberada no nível {min_level}')
        slug=target['species']['name'];entry=next((x for x in pokemon_catalog() if x['slug']==slug),None)
        if not entry:raise HTTPException(503,detail='Evolução indisponível na Pokédex')
        info=flags(entry['id'])
        if info['legendary'] or info['mythical']:raise HTTPException(409,detail='Evolução indisponível')
        types=get_types(entry['id'])
        with writing() as db:
            p=get_pokemon(db,uid,id)
            if p.species_id!=sid or (not needs_stone and p.level<min_level):raise HTTPException(409,detail='Pokémon mudou durante a evolução')
            if needs_stone:item_change(db,uid,'evolucao',-1)
            p.species_id=entry['id'];p.name=entry['name'];p.slug=slug;p.types=','.join(types)
            progress(db,uid,'pokemon_evolve')
            note(db,uid,'pokemon_evolve',pokemon={'name':p.name,'slug':p.slug,'species_id':p.species_id})
        return {'ok':True,'name':entry['name']}
    @app.post('/api/pokemon/adventure/hospital')
    async def hospital(request:Request):
        uid=me(request);data=await request.json();id=verify_int(data.get('id'),1,100000000,'Pokémon')
        with writing() as db:
            p=get_pokemon(db,uid,id,action=False)
            if p.status=='sick':
                p.status='hospital';p.ready_at=now()+timedelta(minutes=params(db,'hospital_minutes'))
            elif p.status=='hospital' and p.ready_at and norm_date(p.ready_at)<=now():
                p.status='healthy';p.ready_at=None
                progress(db,uid,'pokemon_heal')
            else:raise HTTPException(409,detail='Pokémon não precisa de cuidados ou recuperação ainda não terminou')
        return {'ok':True}
    @app.post('/api/pokemon/adventure/expedition/start')
    async def expedition_start(request:Request):
        uid=me(request);data=await request.json();cid=verify_int(data.get('config_id'),1,100000,'Expedição')
        ids=data.get('ids')
        if not isinstance(ids,list) or len(ids)>6 or not ids or len(set(map(str,ids)))!=len(ids) or any(type(x) is not int for x in ids):
            raise HTTPException(422,detail='Selecione de um a seis Pokémon sem repetições')
        with writing() as db:
            cfg=db.get(M['ExpeditionConfig'],cid)
            if not cfg or not cfg.active:raise HTTPException(404,detail='Expedição indisponível')
            if db.get(M['Expedition'],uid):raise HTTPException(409,detail='Você já possui uma expedição ativa')
            selected=[get_pokemon(db,uid,i) for i in ids]
            if sum(cfg.required_type in p.types.split(',') for p in selected)<cfg.required_count and cfg.required_type!='any':
                raise HTTPException(409,detail=f'É preciso ter {cfg.required_count} Pokémon do tipo {cfg.required_type}')
            if cfg.required_type=='any' and len(selected)<cfg.required_count:raise HTTPException(409,detail='Equipe insuficiente')
            for p in selected:p.status='expedition'
            progress(db,uid,'pokemon_expedition_start')
            db.add(M['Expedition'](user_id=uid,config_id=cid,member_ids=json.dumps(ids),
               expires_at=now()+timedelta(minutes=cfg.minutes),coins=RNG.randint(cfg.min_coins,cfg.max_coins),
               card_roll=RNG.randrange(100)<cfg.card_chance,
               collectible_roll=RNG.randrange(100)<cfg.collectible_chance))
        return {'ok':True}
    @app.post('/api/pokemon/adventure/expedition/collect')
    def expedition_collect(request:Request):
        uid=me(request)
        with writing() as db:
            x=db.get(M['Expedition'],uid)
            if not x or norm_date(x.expires_at)>now():raise HTTPException(409,detail='Expedição ainda não terminou')
            participants=[db.get(M['Owned'],id) for id in json.loads(x.member_ids)]
            for p in participants:
                if p and p.user_id==uid:
                    p.status='healthy';award_xp(db,p,25)
            illnesses=set_illness(db,[p for p in participants if p and p.user_id==uid])
            earned=x.coins;wallet(db,uid).coins+=earned
            bonus=[]
            if x.card_roll:
                available=[r for r in stock(db) if r.get('remaining',0)>0]
                if available:
                    chosen=RNG.choice(available);g=grant_card(db,uid,chosen)
                    bonus.append('Card: '+g['name'])
            if x.collectible_roll:
                choices=db.scalars(select(Collectible).where(Collectible.active.is_(True))).all()
                if choices:
                    item=RNG.choice(choices);row=db.get(InventoryCollectible,(uid,item.id))
                    if row:row.quantity+=1
                    else:db.add(InventoryCollectible(user_id=uid,collectible_id=item.id,quantity=1,acquired_at=now()))
                    bonus.append('Colecionável: '+item.name)
            db.delete(x)
            progress(db,uid,'pokemon_expedition_finish')
            note(db,uid,'pokemon_expedition',coins=earned,items=bonus)
            balance=wallet(db,uid).coins
        return {'ok':True,'coins':earned,'bonus':bonus,'illnesses':illnesses,'coins_balance':balance}
    @app.post('/api/pokemon/adventure/battle')
    async def battle(request:Request):
        uid=me(request);data=await request.json();bid=verify_int(data.get('boss_id'),1,100000,'Chefe')
        with writing() as db:
            acct=db.get(M['Account'],uid);boss=db.get(M['Boss'],bid)
            if not acct or not boss or not boss.active:raise HTTPException(404,detail='Chefe indisponível')
            if acct.next_boss and norm_date(acct.next_boss)>now():raise HTTPException(409,detail='Aguarde o intervalo entre batalhas')
            party=team(db,uid)
            if not party:raise HTTPException(409,detail='Monte uma equipe saudável antes de batalhar')
            design=boss_design(db,bid)
            initial,events,won=simulate_battle(db,party,boss,design)
            lo=int(design.get('coins_min',boss.reward_coins));hi=int(design.get('coins_max',boss.reward_coins))
            earned=RNG.randint(lo,hi) if won else max(1,lo//7)
            wallet(db,uid).coins+=earned
            for p in party:award_xp(db,p,30 if won else 8)
            illnesses=set_illness(db,party if not won else [])
            drops=[]
            if won:
                for drop in design.get('item_drops',[]):
                    if RNG.randrange(100)<int(drop.get('chance',0)):
                        count=int(drop.get('quantity',1))
                        item_change(db,uid,drop['sku'],count)
                        drops.append(f'{ITEMS[drop["sku"]]["name"]} ×{count}')
                if RNG.randrange(100)<int(design.get('card_chance',0)):
                    eligible=[c for c in stock(db) if c.get('remaining',0)>0]
                    if eligible:
                        result=grant_card(db,uid,RNG.choice(eligible))
                        drops.append('Card: '+result['name'])
                if RNG.randrange(100)<int(design.get('collectible_chance',0)):
                    choices=db.scalars(select(Collectible).where(Collectible.active.is_(True))).all()
                    if choices:
                        item=RNG.choice(choices)
                        row=db.get(InventoryCollectible,(uid,item.id))
                        if row:row.quantity+=1
                        else:db.add(InventoryCollectible(user_id=uid,collectible_id=item.id,quantity=1,acquired_at=now()))
                        drops.append('Colecionável: '+item.name)
            acct.next_boss=now()+timedelta(minutes=params(db,'boss_cooldown_minutes'))
            progress(db,uid,'pokemon_battle')
            if won:progress(db,uid,'pokemon_battle_win')
            note(db,uid,'pokemon_battle_start',boss=boss.name)
            note(db,uid,'pokemon_battle',boss=boss.name,won=won,coins=earned,drops=drops)
            balance=wallet(db,uid).coins
            boss_payload=enriched_boss_from_values(boss,design)
        return {'ok':True,'won':won,'coins':earned,'coins_balance':balance,
            'battle':initial,'events':events,'boss':boss_payload,
            'drops':drops,'illnesses':illnesses}

    @app.get('/api/pokemon/adventure/trades')
    def trades(request:Request):
        uid=me(request)
        with SessionLocal() as db:
            rows=db.scalars(select(M['Trade']).where((M['Trade'].sender_id==uid)|(M['Trade'].receiver_id==uid)).order_by(M['Trade'].id.desc()).limit(40)).all()
            return {'items':[{'id':x.id,'status':x.status,'sender_id':x.sender_id,'receiver_id':x.receiver_id,
                'offered':owned_json(db.get(M['Owned'],x.offered_id)) if db.get(M['Owned'],x.offered_id) else None,
                'wanted':owned_json(db.get(M['Owned'],x.wanted_id)) if db.get(M['Owned'],x.wanted_id) else None,
                'mine':x.sender_id==uid} for x in rows]}
    @app.get('/api/pokemon/adventure/member/{member_id}')
    def member_pokemon(member_id:str,request:Request):
        me(request)
        if not re.fullmatch(r'[0-9]{5,30}',member_id):raise HTTPException(422,detail='Membro inválido')
        with SessionLocal() as db:return {'items':[owned_json(p) for p in owned(db,member_id)]}
    @app.post('/api/pokemon/adventure/trades')
    async def propose_trade(request:Request):
        uid=me(request);data=await request.json();target=str(data.get('to_user',''))
        offer=verify_int(data.get('offered_id'),1,100000000,'Seu Pokémon')
        wanted=verify_int(data.get('wanted_id'),1,100000000,'Pokémon desejado')
        if target==uid or not re.fullmatch(r'[0-9]{5,30}',target):raise HTTPException(422,detail='Destinatário inválido')
        with writing() as db:
            if not db.get(M['Account'],target):raise HTTPException(409,detail='Este membro ainda não iniciou Pokémon')
            get_pokemon(db,uid,offer);get_pokemon(db,target,wanted)
            if db.scalar(select(func.count(M['Trade'].id)).where(M['Trade'].sender_id==uid,M['Trade'].status=='pending'))>=15:
                raise HTTPException(429,detail='Limite de propostas pendentes')
            db.add(M['Trade'](sender_id=uid,receiver_id=target,offered_id=offer,wanted_id=wanted,
                status='pending',created_at=now()))
        return {'ok':True}
    @app.post('/api/pokemon/adventure/trades/{trade_id}/decide')
    async def decide(trade_id:int,request:Request):
        uid=me(request);data=await request.json();action=data.get('action')
        if action not in ('accept','reject','cancel'):raise HTTPException(422,detail='Ação inválida')
        with writing() as db:
            x=db.get(M['Trade'],trade_id)
            if not x or x.status!='pending':raise HTTPException(409,detail='Proposta não está pendente')
            if (action=='cancel' and x.sender_id!=uid) or (action!='cancel' and x.receiver_id!=uid):raise HTTPException(403,detail='Sem permissão')
            if action=='accept':
                a=get_pokemon(db,x.sender_id,x.offered_id);b=get_pokemon(db,x.receiver_id,x.wanted_id)
                if a.position or b.position:raise HTTPException(409,detail='Retire os Pokémon das equipes antes de trocar')
                if len(owned(db,x.sender_id))>=params(db,'max_pokemon') or len(owned(db,x.receiver_id))>=params(db,'max_pokemon'):
                    # one-for-one swaps preserve count, even at limit
                    pass
                a.user_id,b.user_id=x.receiver_id,x.sender_id
                progress(db,x.sender_id,'pokemon_trade')
                progress(db,x.receiver_id,'pokemon_trade')
                note(db,x.sender_id,'pokemon_trade',a=a.name,b=b.name)
                x.status='accepted'
            else:x.status='rejected' if action=='reject' else 'cancelled'
        return {'ok':True}
    @app.get('/api/admin/pokemon/adventure')
    def admin_config(request:Request):
        only_admin(request)
        with SessionLocal() as db:
            return {'settings':{k:params(db,k) for k in DEFAULT_SETTINGS},
                'prices':{sku:(db.get(M['Setting'],'item_price_'+sku).value if db.get(M['Setting'],'item_price_'+sku) else item['price']) for sku,item in ITEMS.items()},
                'ball_chances':{sku:(db.get(M['Setting'],'ball_chance_'+sku).value if db.get(M['Setting'],'ball_chance_'+sku) else item['chance']) for sku,item in BALLS.items()},
                'expeditions':[config_json(c) for c in get_exp_config(db)],
                'bosses':[enriched_boss(db,x) for x in db.scalars(select(M['Boss'])).all()],
                'capture_backgrounds':type_backgrounds(db),
                'sprite_overrides':sprite_overrides(db),'media_assets':media_assets(db)}
    @app.get('/api/admin/pokemon/adventure/moves')
    def get_move_config(request:Request,species_id:int):
        only_admin(request)
        species_id=verify_int(species_id,1,1025,'Espécie')
        types=get_types(species_id)
        with SessionLocal() as db:
            return {'species_id':species_id,'types':types,'moves':move_config_for_species(db,species_id,types)}

    @app.post('/api/admin/pokemon/adventure/moves')
    async def save_move_config(request:Request):
        only_admin(request)
        payload=await request.json()
        if not isinstance(payload,dict):raise HTTPException(422,detail='Dados inválidos')
        species_id=verify_int(payload.get('species_id'),1,1025,'Espécie')
        types=get_types(species_id)
        moves=sanitize_moves_payload(payload.get('moves'),types)
        with writing() as db:
            row=db.get(M['MoveConfig'],species_id)
            dump=json.dumps(moves,ensure_ascii=False)
            if row: row.payload=dump
            else: db.add(M['MoveConfig'](species_id=species_id,payload=dump))
        return {'ok':True,'species_id':species_id,'moves':moves}

    @app.post('/api/admin/pokemon/adventure/media')
    async def update_media(request:Request):
        only_admin(request);data=await request.json()
        key=str(data.get('key') or '')
        if key!='pokemon-nurse-joy' and key not in {'pokemon-item-'+sku for sku in ITEMS}:
            raise HTTPException(422,detail='Imagem de item inválida')
        url=clean_url(data.get('image_url'))
        with writing() as db:
            row=db.get(UIAsset,key)
            if not url:
                if row:db.delete(row)
            elif row:row.image_url=url
            else:db.add(UIAsset(key=key,selector='',mode='image',image_url=url))
        return {'ok':True,'key':key,'image_url':url}

    @app.post('/api/admin/pokemon/adventure/background')
    async def save_capture_background(request:Request):
        only_admin(request)
        payload=await request.json()
        if not isinstance(payload,dict):raise HTTPException(422,detail='Dados inválidos')
        pokemon_type=str(payload.get('type') or '').strip().lower()
        if pokemon_type not in POKEMON_TYPES:raise HTTPException(422,detail='Selecione um dos 18 tipos de Pokémon')
        url=safe_artwork(payload.get('image_url'))
        key='pokemon-bg-'+pokemon_type
        with writing() as db:
            entry=db.get(UIAsset,key)
            if not url:
                if entry:db.delete(entry)
            elif entry:
                entry.image_url=url
            else:
                db.add(UIAsset(key=key,selector='',mode='background',image_url=url))
        return {'ok':True,'type':pokemon_type,'image_url':url}


    @app.post('/api/admin/pokemon/adventure/sprite')
    async def save_pokemon_sprite(request:Request):
        only_admin(request)
        payload=await request.json()
        if not isinstance(payload,dict):raise HTTPException(422,detail='Dados inválidos')
        species_id=verify_int(payload.get('species_id'),1,1025,'Espécie')
        context=payload.get('context')
        gender=payload.get('gender')
        shiny=payload.get('variant')
        if context not in ('wild','owned','back') or gender not in ('any','male','female','unknown') or shiny not in ('normal','shiny'):
            raise HTTPException(422,detail='Contexto, gênero ou variante inválidos')
        url=safe_artwork(payload.get('image_url'))
        key=f'pokemon-sprite:{species_id}:{context}:{gender}:{shiny}'
        with writing() as db:
            record=db.get(UIAsset,key)
            if not url:
                if record:db.delete(record)
            elif record:record.image_url=url
            else:db.add(UIAsset(key=key,selector='',mode='image',image_url=url))
        return {'ok':True,'key':f'{species_id}:{context}:{gender}:{shiny}','image_url':url}

    @app.post('/api/admin/pokemon/adventure/settings')
    async def update_config(request:Request):
        only_admin(request);data=await request.json()
        allowed={**DEFAULT_SETTINGS,**{'item_price_'+k:v['price'] for k,v in ITEMS.items()},
          **{'ball_chance_'+k:v['chance'] for k,v in BALLS.items()}}
        if not isinstance(data,dict):raise HTTPException(422,detail='Configuração inválida')
        with writing() as db:
            for key,value in data.items():
                if key not in allowed:raise HTTPException(422,detail='Configuração desconhecida')
                if key.startswith('ball_chance_') and value>100:raise HTTPException(422,detail='Chance de Pokébola inválida')
                if key=='shiny_odds' and not 1<=value<=1000000:raise HTTPException(422,detail='Chance Shiny: 1 em 1 a 1.000.000')
                verify_int(value,0,100000,'Valor')
                row=db.get(M['Setting'],key)
                if row:row.value=value
                else:db.add(M['Setting'](key=key,value=value))
            db.flush()
            lo=params(db,'encounter_min_minutes');hi=params(db,'encounter_max_minutes')
            if lo<1 or hi<lo:raise HTTPException(422,detail='Intervalo de encontros inválido')
            if params(db,'encounter_attempts')<1 or params(db,'encounter_attempts')>10:raise HTTPException(422,detail='Tentativas: 1 a 10')
            if params(db,'illness_chance')>100:raise HTTPException(422,detail='Probabilidade de doença inválida')
        return {'ok':True}
    @app.post('/api/admin/pokemon/adventure/expedition')
    async def save_exp_config(request:Request):
        only_admin(request);data=await request.json();id=data.get('id')
        name=str(data.get('name','')).strip()[:90];r_type=str(data.get('required_type','any')).strip()[:30]
        if not name or not re.fullmatch('[a-z-]{2,30}',r_type):raise HTTPException(422,detail='Nome ou tipo inválido')
        fields=('required_count','minutes','min_coins','max_coins','card_chance','collectible_chance')
        for k in fields:verify_int(data.get(k),0,10000,k)
        if not 1<=data['required_count']<=6 or not 1<=data['minutes'] or data['max_coins']<data['min_coins'] or data['card_chance']>100 or data['collectible_chance']>100:
            raise HTTPException(422,detail='Requisitos ou recompensas inválidos')
        with writing() as db:
            row=db.get(M['ExpeditionConfig'],id) if type(id) is int else None
            if not row:row=M['ExpeditionConfig']();db.add(row)
            for k in ('name','required_type','required_count','minutes','min_coins','max_coins','card_chance','collectible_chance','active'):
                if k in data:setattr(row,k,(name if k=='name' else r_type if k=='required_type' else bool(data[k]) if k=='active' else data[k]))
        return {'ok':True}
    @app.post('/api/admin/pokemon/adventure/boss')
    async def save_boss(request:Request):
        only_admin(request);data=await request.json();id=data.get('id')
        name=str(data.get('name','')).strip()[:90]
        if not name:raise HTTPException(422,detail='Informe o nome do chefe')
        for k,lo,hi in [('species_id',1,1025),('level',1,100),('reward_coins',0,100000)]:verify_int(data.get(k),lo,hi,k)
        helpers=data.get('helpers',[])
        if not isinstance(helpers,list) or len(helpers)>5:raise HTTPException(422,detail='Máximo de 5 ajudantes')
        clean_helpers=[]
        occupied={verify_int(data.get('boss_position',2),1,6,'Posição do chefe')}
        for i,h in enumerate(helpers):
            if not isinstance(h,dict):raise HTTPException(422,detail='Ajudante inválido')
            sp=verify_int(h.get('species_id'),1,1025,'Espécie ajudante')
            level=verify_int(h.get('level'),1,100,'Nível ajudante')
            pos=verify_int(h.get('position'),1,6,'Posição ajudante')
            if pos in occupied:raise HTTPException(422,detail='Duas unidades na mesma posição')
            occupied.add(pos)
            kind=str(h.get('type') or 'normal').lower()
            if kind not in POKEMON_TYPES:raise HTTPException(422,detail='Tipo de ajudante inválido')
            clean_helpers.append({'species_id':sp,'level':level,'position':pos,
                'name':str(h.get('name') or f'Ajudante {i+1}')[:70],'types':[kind]})
        boss_type=str(data.get('type') or 'normal').lower()
        if boss_type not in POKEMON_TYPES:raise HTTPException(422,detail='Tipo de chefe inválido')
        mincoins=verify_int(data.get('coins_min',data['reward_coins']),0,100000,'Moedas mínimas')
        maxcoins=verify_int(data.get('coins_max',data['reward_coins']),mincoins,100000,'Moedas máximas')
        cards=verify_int(data.get('card_chance',0),0,100,'Chance de card')
        collectible=verify_int(data.get('collectible_chance',0),0,100,'Chance de colecionável')
        drops=data.get('item_drops',[])
        if not isinstance(drops,list) or len(drops)>12:raise HTTPException(422,detail='Drops inválidos')
        valid_drops=[]
        for drop in drops:
            if not isinstance(drop,dict) or drop.get('sku') not in ITEMS:raise HTTPException(422,detail='Item de drop inválido')
            valid_drops.append({'sku':drop['sku'],
               'chance':verify_int(drop.get('chance'),0,100,'Chance de item'),
               'quantity':verify_int(drop.get('quantity'),1,50,'Quantidade de item')})
        config={'helpers':clean_helpers,'boss_position':int(data.get('boss_position',2)),
          'type':boss_type,'background_url':clean_url(data.get('background_url')),
          'image_url':clean_url(data.get('image_url')),
          'music_url':clean_url(data.get('music_url'),audio=True),
          'coins_min':mincoins,'coins_max':maxcoins,'card_chance':cards,
          'collectible_chance':collectible,'item_drops':valid_drops}
        with writing() as db:
            row=db.get(M['Boss'],id) if type(id) is int else None
            if not row:row=M['Boss']();db.add(row)
            for k in ('name','species_id','level','reward_coins','active'):
                if k in data:setattr(row,k,name if k=='name' else bool(data[k]) if k=='active' else data[k])
            db.flush()
            design=db.get(M['BossDesign'],row.id)
            if design:design.payload=json.dumps(config,ensure_ascii=False)
            else:db.add(M['BossDesign'](boss_id=row.id,payload=json.dumps(config,ensure_ascii=False)))
            saved_id=row.id
        return {'ok':True,'id':saved_id}

    # The server creates defaults exactly once. Administrators can subsequently edit them.
    with SessionLocal.begin() as db:
        if not db.scalar(select(func.count(M['ExpeditionConfig'].id))):
            db.add(M['ExpeditionConfig'](name='Trilha Verde',required_type='any',required_count=1,
                   minutes=40,min_coins=20,max_coins=55,card_chance=12,collectible_chance=4,active=True))
            db.add(M['ExpeditionConfig'](name='Costa Azul',required_type='water',required_count=2,
                   minutes=65,min_coins=35,max_coins=80,card_chance=18,collectible_chance=7,active=True))
        if not db.scalar(select(func.count(M['Boss'].id))):
            db.add(M['Boss'](name='Guardião do Bosque',species_id=3,level=15,reward_coins=80,active=True))
            db.add(M['Boss'](name='Dragão da Montanha',species_id=6,level=35,reward_coins=140,active=True))
