"""Recanto 1.2: missions by period, Discord event ingestion and opt-in Web Push.
Tables are additive; no existing progress, wallets or collections are dropped.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, select, func, delete
from sqlalchemy.orm import Mapped, mapped_column

VALID_EVENTS={'daily_card','daily_coins','trade','pet','feed','adopt','pack','voice_minutes','message_count'}
VALID_PERIODS={'unica','diaria','semanal'}


def register_engagement(*, app, Base, engine, SessionLocal, User, Wallet, current_user_id, utcnow):
    tz=ZoneInfo(os.getenv('RECANTO_TIMEZONE','America/Sao_Paulo'))

    class Mission(Base):
        __tablename__='recanto_missions_v2'
        code:Mapped[str]=mapped_column(String(48),primary_key=True)
        title:Mapped[str]=mapped_column(String(120),nullable=False)
        kind:Mapped[str]=mapped_column(String(12),nullable=False)
        event:Mapped[str]=mapped_column(String(30),nullable=False)
        goal:Mapped[int]=mapped_column(Integer,nullable=False)
        reward:Mapped[int]=mapped_column(Integer,nullable=False)
        emoji:Mapped[str]=mapped_column(String(32),default='🎯')
        image_url:Mapped[str | None]=mapped_column(String(512),nullable=True)
        enabled:Mapped[bool]=mapped_column(Boolean,default=True,nullable=False)
        week_tag:Mapped[str | None]=mapped_column(String(12),nullable=True)

    class MissionDeleted(Base):
        # Persisted tombstones keep built-in missions deleted across Render restarts.
        __tablename__='recanto_deleted_missions'
        code:Mapped[str]=mapped_column(String(48),primary_key=True)
        deleted_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

    class Counter(Base):
        __tablename__='recanto_mission_counters'
        user_id:Mapped[str]=mapped_column(ForeignKey('users.id'),primary_key=True)
        event:Mapped[str]=mapped_column(String(30),primary_key=True)
        bucket:Mapped[str]=mapped_column(String(24),primary_key=True)
        amount:Mapped[int]=mapped_column(Integer,default=0,nullable=False)

    class MissionClaim(Base):
        __tablename__='recanto_mission_claims'
        user_id:Mapped[str]=mapped_column(ForeignKey('users.id'),primary_key=True)
        code:Mapped[str]=mapped_column(String(48),primary_key=True)
        bucket:Mapped[str]=mapped_column(String(24),primary_key=True)
        claimed_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

    class BotEvent(Base):
        __tablename__='recanto_discord_events'
        event_id:Mapped[str]=mapped_column(String(110),primary_key=True)
        user_id:Mapped[str]=mapped_column(ForeignKey('users.id'),nullable=False)
        created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

    class PushSubscription(Base):
        __tablename__='recanto_push_subscriptions'
        endpoint_hash:Mapped[str]=mapped_column(String(64),primary_key=True)
        user_id:Mapped[str]=mapped_column(ForeignKey('users.id'),nullable=False)
        endpoint:Mapped[str]=mapped_column(String(2048),nullable=False)
        p256dh:Mapped[str]=mapped_column(String(256),nullable=False)
        auth:Mapped[str]=mapped_column(String(256),nullable=False)

    class NotificationSent(Base):
        __tablename__='recanto_notification_sent'
        user_id:Mapped[str]=mapped_column(ForeignKey('users.id'),primary_key=True)
        event_key:Mapped[str]=mapped_column(String(128),primary_key=True)
        created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

    Base.metadata.create_all(engine)
    defaults=[
        ('adopt_first','Adote sua primeira Pequena Lenda','unica','adopt',1,40,'🐾'),
        ('trade_first','Faça sua primeira troca','unica','trade',1,35,'🤝'),
        ('daily_card','Resgate um card','diaria','daily_card',1,12,'🃏'),
        ('daily_coins','Resgate suas moedas','diaria','daily_coins',1,8,'🪙'),
        ('daily_pet','Acaricie um pet','diaria','pet',1,8,'💕'),
        ('daily_feed','Alimente um pet','diaria','feed',1,12,'🍪'),
        ('daily_pack','Abra um pacote','diaria','pack',1,18,'🎁'),
    ]
    with SessionLocal.begin() as db:
        for code,title,kind,event,goal,reward,emoji in defaults:
            if not db.get(Mission,code) and not db.get(MissionDeleted,code):
                db.add(Mission(code=code,title=title,kind=kind,event=event,goal=goal,reward=reward,emoji=emoji))

    def period_key(kind, now=None):
        now=(now or utcnow()).astimezone(tz)
        if kind=='unica':return 'all'
        if kind=='diaria':return 'd:'+now.date().isoformat()
        monday=now.date()-timedelta(days=now.weekday())
        return 'w:'+monday.isoformat()

    def next_reset(kind):
        now=utcnow().astimezone(tz)
        if kind=='diaria': date=now.date()+timedelta(days=1)
        else: date=now.date()+timedelta(days=7-now.weekday())
        return datetime(date.year,date.month,date.day,tzinfo=tz).astimezone(timezone.utc).isoformat()

    def tracked(db,uid,event,amount=1):
        if event not in VALID_EVENTS:return
        for kind in VALID_PERIODS:
            bucket=period_key(kind)
            row=db.get(Counter,(uid,event,bucket))
            if row:row.amount=min(999999,row.amount+amount)
            else:db.add(Counter(user_id=uid,event=event,bucket=bucket,amount=amount))

    def require_user(request):
        uid=current_user_id(request)
        if not uid:raise HTTPException(401,detail='Faça login')
        return uid

    def admin(request):
        uid=require_user(request)
        admins={n.strip() for n in os.getenv('RECANTO_ADMIN_DISCORD_IDS','249610270069096448').split(',') if n.strip().isdecimal()}
        if uid in admins:return uid
        # Também respeita administradores extras cadastrados no painel anterior.
        table=Base.metadata.tables.get('admin_permissions')
        if table is not None:
            with SessionLocal() as db:
                if db.execute(select(table.c.discord_id).where(table.c.discord_id==uid)).first():return uid
        raise HTTPException(403,detail='Somente administradores')

    def shown_missions(db):
        entries=db.scalars(select(Mission).where(Mission.enabled.is_(True)).order_by(Mission.code)).all()
        # Show all registered missions. Daily and weekly counters use distinct
        # time buckets, so weekly missions remain active and reset automatically.
        return ([m for m in entries if m.kind=='semanal']+
                [m for m in entries if m.kind=='diaria']+
                [m for m in entries if m.kind=='unica'])

    @app.get('/api/missions')
    def list_missions(request:Request):
        uid=require_user(request)
        with SessionLocal() as db:
            entries=shown_missions(db)
            items=[]
            for m in entries:
                bucket=period_key(m.kind)
                counter=db.get(Counter,(uid,m.event,bucket))
                progress_value=counter.amount if counter else 0
                # Conta adoções realizadas antes da atualização, sem duplicar ações.
                if m.kind=='unica' and m.event=='adopt' and not progress_value:
                    pets=Base.metadata.tables.get('user_pets')
                    if pets is not None and db.execute(select(pets.c.user_id).where(pets.c.user_id==uid)).first():progress_value=1
                claimed=db.get(MissionClaim,(uid,m.code,bucket)) is not None
                items.append({'code':m.code,'title':m.title,'kind':m.kind,'goal':m.goal,'reward':m.reward,'progress':min(m.goal,progress_value),'claimed':claimed,'emoji':m.emoji,'image_url':m.image_url})
            return {'items':items,'next_reset':next_reset('diaria'),'weekly_reset':next_reset('semanal')}

    @app.post('/api/missions/{code}/claim')
    def claim_mission(code:str,request:Request):
        uid=require_user(request)
        with SessionLocal.begin() as db:
            m=db.get(Mission,code)
            if not m or m not in shown_missions(db):raise HTTPException(404,detail='Missão não disponível')
            bucket=period_key(m.kind)
            if db.get(MissionClaim,(uid,code,bucket)):raise HTTPException(409,detail='Recompensa já resgatada')
            val=db.get(Counter,(uid,m.event,bucket))
            amount=val.amount if val else 0
            if m.kind=='unica' and m.event=='adopt' and amount<1:
                pets=Base.metadata.tables.get('user_pets')
                if pets is not None and db.execute(select(pets.c.user_id).where(pets.c.user_id==uid)).first():amount=1
            if amount<m.goal:raise HTTPException(409,detail='Missão ainda não concluída')
            balance=db.get(Wallet,uid)
            if not balance:raise HTTPException(404,detail='Carteira não encontrada')
            # Bloqueio no registro da carteira impede duplicação sob concorrência.
            if engine.dialect.name!='sqlite':db.execute(select(Wallet.user_id).where(Wallet.user_id==uid).with_for_update()).one()
            balance.coins+=m.reward
            db.add(MissionClaim(user_id=uid,code=code,bucket=bucket))
            return {'ok':True,'coins_gained':m.reward}

    @app.get('/api/admin/missions')
    def admin_missions(request:Request):
        admin(request)
        with SessionLocal() as db:
            return {'items':[{'code':m.code,'title':m.title,'kind':m.kind,'event':m.event,'goal':m.goal,'reward':m.reward,'emoji':m.emoji,'image_url':m.image_url,'enabled':m.enabled,'week_tag':m.week_tag} for m in db.scalars(select(Mission).order_by(Mission.code)).all()], 'week':period_key('semanal')}

    @app.post('/api/admin/missions')
    async def save_mission(request:Request):
        admin(request)
        data=await request.json()
        if not isinstance(data,dict):raise HTTPException(422,detail='Dados inválidos')
        code=str(data.get('code','')).strip().lower()
        kind=str(data.get('kind',''))
        event=str(data.get('event',''))
        title=str(data.get('title','')).strip()[:120]
        if not re.fullmatch(r'[a-z0-9_]{3,48}',code) or kind not in VALID_PERIODS or event not in VALID_EVENTS or not title:
            raise HTTPException(422,detail='Código, tipo, evento ou título inválidos')
        goal=data.get('goal');reward=data.get('reward')
        if type(goal)!=int or type(reward)!=int or not 1<=goal<=20000 or not 1<=reward<=500:
            raise HTTPException(422,detail='Meta (1–20000) ou recompensa (1–500) inválida')
        emoji=str(data.get('emoji') or '🎯')[:32]
        image=str(data.get('image_url') or '')[:512] or None
        if image and not (image.startswith('https://') or image.startswith('/uploads/')):raise HTTPException(422,detail='Imagem deve ser HTTPS')
        with SessionLocal.begin() as db:
            m=db.get(Mission,code)
            tombstone=db.get(MissionDeleted,code)
            if tombstone:db.delete(tombstone)
            if not m:m=Mission(code=code);db.add(m)
            m.title=title;m.kind=kind;m.event=event;m.goal=goal;m.reward=reward;m.emoji=emoji;m.image_url=image
            m.enabled=bool(data.get('enabled',True))
            m.week_tag=period_key('semanal') if kind=='semanal' else None
        return {'ok':True,'code':code}

    @app.post('/api/admin/missions/{code}/visibility')
    async def admin_mission_visibility(code:str,request:Request):
        admin(request)
        data=await request.json()
        if not isinstance(data,dict) or type(data.get('enabled')) is not bool:
            raise HTTPException(422,detail='Informe enabled true ou false')
        with SessionLocal.begin() as db:
            mission=db.get(Mission,code)
            if not mission:raise HTTPException(404,detail='Missão inexistente')
            mission.enabled=data['enabled']
            if mission.enabled and mission.kind=='semanal':mission.week_tag=period_key('semanal')
        return {'ok':True,'code':code,'enabled':data['enabled']}

    @app.post('/api/admin/missions/{code}/delete')
    def delete_mission(code:str,request:Request):
        admin(request)
        with SessionLocal.begin() as db:
            m=db.get(Mission,code)
            if not m:raise HTTPException(404,detail='Missão inexistente')
            # Progress counters are shared across missions with the same event;
            # never erase them or other missions could lose their progress.
            db.execute(delete(MissionClaim).where(MissionClaim.code==code))
            db.delete(m)
            # Built-in defaults must not be re-created on next server boot.
            if not db.get(MissionDeleted,code):db.add(MissionDeleted(code=code))
            desc=Base.metadata.tables.get('recanto_mission_descriptions')
            if desc is not None:db.execute(delete(desc).where(desc.c.code==code))
        return {'ok':True,'code':code,'deleted':True}

    @app.post('/api/integrations/discord/event')
    async def discord_event(request:Request):
        secret=os.getenv('RECANTO_BOT_SECRET','')
        supplied=request.headers.get('x-recanto-bot-secret','')
        if len(secret)<24 or not secrets.compare_digest(secret,supplied):raise HTTPException(401,detail='Integração não autorizada')
        data=await request.json()
        if not isinstance(data,dict):raise HTTPException(422,detail='Evento inválido')
        uid=str(data.get('discord_id',''))
        event_id=str(data.get('event_id',''))
        event=str(data.get('event',''))
        amount=data.get('amount',1)
        if not re.fullmatch(r'[0-9]{6,32}',uid) or not 8<=len(event_id)<=110 or event not in {'voice_minutes','message_count'}:
            raise HTTPException(422,detail='Identificador ou evento inválido')
        if type(amount)!=int or not 1<=amount<=(15 if event=='voice_minutes' else 1):raise HTTPException(422,detail='Quantidade inválida')
        with SessionLocal.begin() as db:
            if not db.get(User,uid):return {'ok':True,'ignored':'usuario_nao_cadastrado'}
            if db.get(BotEvent,event_id):return {'ok':True,'duplicate':True}
            db.add(BotEvent(event_id=event_id,user_id=uid))
            tracked(db,uid,event,amount)
        return {'ok':True}

    # -------- notificações Web Push. Envio ocorre por chamada agendada EXTERNA. --------
    @app.get('/api/push/key')
    def push_key(request:Request):
        require_user(request)
        public=os.getenv('VAPID_PUBLIC_KEY','')
        return {'enabled':bool(public and os.getenv('VAPID_PRIVATE_KEY')),'public_key':public}

    @app.post('/api/push/subscribe')
    async def push_subscribe(request:Request):
        uid=require_user(request)
        data=await request.json()
        endpoint=data.get('endpoint','') if isinstance(data,dict) else ''
        keys=data.get('keys',{}) if isinstance(data,dict) else {}
        hostname=urlsplit(endpoint).hostname if isinstance(endpoint,str) else None
        push_host_ok=bool(hostname and (hostname in {'fcm.googleapis.com','updates.push.services.mozilla.com','web.push.apple.com'}
            or hostname.endswith('.notify.windows.com') or hostname.endswith('.push.apple.com')
            or hostname.endswith('.push.services.mozilla.com')))
        if not isinstance(endpoint,str) or not endpoint.startswith('https://') or not push_host_ok or len(endpoint)>2048 or not isinstance(keys,dict) or not all(isinstance(keys.get(k),str) and 8<len(keys[k])<=256 for k in ('p256dh','auth')):
            raise HTTPException(422,detail='Assinatura push inválida ou endpoint não suportado')
        digest=hashlib.sha256(endpoint.encode()).hexdigest()
        with SessionLocal.begin() as db:
            row=db.get(PushSubscription,digest)
            if not row:db.add(PushSubscription(endpoint_hash=digest,user_id=uid,endpoint=endpoint,p256dh=keys['p256dh'],auth=keys['auth']))
            else:row.user_id=uid;row.p256dh=keys['p256dh'];row.auth=keys['auth']
        return {'ok':True}

    @app.post('/api/push/unsubscribe')
    async def push_unsubscribe(request:Request):
        uid=require_user(request)
        data=await request.json()
        endpoint=data.get('endpoint') if isinstance(data,dict) else None
        if endpoint:
            with SessionLocal.begin() as db:
                row=db.get(PushSubscription,hashlib.sha256(str(endpoint).encode()).hexdigest())
                if row and row.user_id==uid:db.delete(row)
        return {'ok':True}

    @app.post('/api/jobs/send-notifications')
    def send_notifications(request:Request):
        secret=os.getenv('RECANTO_CRON_SECRET','')
        if len(secret)<24 or not secrets.compare_digest(secret,request.headers.get('x-recanto-cron-secret','')):raise HTTPException(401,detail='Job não autorizado')
        private=os.getenv('VAPID_PRIVATE_KEY','')
        subject=os.getenv('VAPID_SUBJECT','')
        if not private or not os.getenv('VAPID_PUBLIC_KEY') or not subject.startswith('mailto:'):
            return {'ok':False,'detail':'Configure VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY e VAPID_SUBJECT'}
        from pywebpush import webpush
        table=Base.metadata.tables['notification_preferences']
        cardtable=Base.metadata.tables['card_cooldowns']
        ptable=Base.metadata.tables['user_pets']
        etable=Base.metadata.tables['pet_expeditions']
        delivered=0
        now=utcnow()
        with SessionLocal() as db:
            enabled_uids=[r[0] for r in db.execute(select(table.c.user_id).where(table.c.enabled.is_(True))).all()]
        for uid in enabled_uids[:250]:
            with SessionLocal() as db:
                subs=db.scalars(select(PushSubscription).where(PushSubscription.user_id==uid)).all()
                if not subs:continue
                alerts=[]
                last_card=db.execute(select(cardtable.c.last_claimed).where(cardtable.c.user_id==uid)).scalar()
                if last_card:
                    ready=last_card.replace(tzinfo=timezone.utc) if last_card.tzinfo is None else last_card
                    if now>=ready+timedelta(hours=5):alerts.append(('card:'+ready.isoformat(),'Seu card está disponível','Já pode resgatar uma nova carta no Recanto!'))
                expedition=db.execute(select(etable.c.ends_at).where(etable.c.user_id==uid)).scalar()
                if expedition:
                    ends=expedition.replace(tzinfo=timezone.utc) if expedition.tzinfo is None else expedition
                    if now>=ends:alerts.append(('expedition:'+ends.isoformat(),'Expedição concluída','Sua Pequena Lenda voltou! Entre no Recanto para coletar a recompensa.'))
                pet=db.execute(select(ptable.c.food,ptable.c.status,ptable.c.last_tick_at).where(ptable.c.user_id==uid)).first()
                estimated_food=pet[0] if pet else 100
                if pet and pet[2]:
                    last_tick=pet[2].replace(tzinfo=timezone.utc) if pet[2].tzinfo is None else pet[2]
                    estimated_food=max(0,pet[0]-4*max(0,int((now-last_tick).total_seconds()//3600)))
                if pet and pet[1]=='ativo' and estimated_food<=30:
                    # no máximo 1 aviso a cada 12h de fome persistente
                    alerts.append(('hunger:'+now.date().isoformat()+('am' if now.hour<12 else 'pm'),'Seu pet está com fome','Sua Pequena Lenda precisa de alimentação!'))
                # 0.4.6: conquistas ainda não exibidas no aplicativo aberto
                # tornam-se Web Push na rotina agendada, sem envio duplicado.
                # Não apagar avisos aqui: eles continuam na caixa de avisos do app.
                achievement=Base.metadata.tables.get('recanto_achievement_notices')
                if achievement is not None:
                    pending=db.execute(select(achievement.c.key,achievement.c.kind,achievement.c.title)
                        .where(achievement.c.user_id==uid,
                               achievement.c.read_at.is_(None),
                               achievement.c.created_at>=now-timedelta(days=7))
                        .order_by(achievement.c.created_at).limit(12)).all()
                    for key,kind,event_title in pending:
                        label='Selo conquistado!' if kind=='badge' else 'Missão concluída!'
                        alerts.append(('achievement:'+key,label,event_title))
                for key,title,body in alerts:
                    if db.get(NotificationSent,(uid,key)):continue
                    success=False
                    for subscription in subs:
                        try:
                            webpush(subscription_info={'endpoint':subscription.endpoint,'keys':{'p256dh':subscription.p256dh,'auth':subscription.auth}},
                              data=json.dumps({'title':title,'body':body},ensure_ascii=False),
                              vapid_private_key=private,vapid_claims={'sub':subject},ttl=3600,timeout=10)
                            success=True
                        except Exception:
                            # Push inválido não é contado como entregue; será tentado de novo.
                            pass
                    if success:
                        with SessionLocal.begin() as write_db:
                            if not write_db.get(NotificationSent,(uid,key)):
                                write_db.add(NotificationSent(user_id=uid,event_key=key))
                        delivered+=1
        return {'ok':True,'sent':delivered}

    return tracked
