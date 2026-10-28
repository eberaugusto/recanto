"""Recanto 0.3.13. Economia e jogo executados inteiramente no servidor.

Ações que alteram saldo/itens usam transações serializadas. O browser só pede
operações; nunca escolhe resultado de sorteio, saldo, recompensa ou tempo.
"""
from __future__ import annotations
import logging
import asyncio

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import os
import hashlib
import time
import httpx
import random
import secrets
import hmac
import json
import re
import uuid

from fastapi import HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, and_, func, select, text, inspect, delete, update
from sqlalchemy.orm import Mapped, mapped_column
from PIL import Image

RANDOM = random.SystemRandom()
TIERS = {'comum': 3, 'raro': 2, 'lendário': 1, 'prismático': 1}
TIER_LABEL = {'comum': 'Comum', 'raro': 'Raro', 'lendário': 'Lendário', 'prismático': 'Prismático'}
WEIGHTS = {
    'diario': {'comum': 60, 'raro': 29, 'lendário': 10, 'prismático': 1},
    'pack3': {'comum': 65, 'raro': 20, 'lendário': 12, 'prismático': 3},
    'pack5': {'comum': 65, 'raro': 25, 'lendário': 9, 'prismático': 1},
    'expedition': {'comum': 84, 'raro': 14, 'lendário': 1.8, 'prismático': 0.2},
}
DEFAULTS = {
    'card_bonus_comum': 1, 'card_bonus_raro': 2,
    'card_bonus_lendário': 4, 'card_bonus_prismático': 5,
    'daily_coins': 35, 'trade_bonus': 8,
    'trade_reward_limit': 2, 'pack3_cost': 700, 'pack5_cost': 550,
    'treat_bundle_cost': 65, 'treat_fruit_cost': 45, 'treat_feast_cost': 90,
    'visit_pet_reward': 3, 'visit_feed_reward': 5, 'visit_owner_reward': 1,
    'vet_cost': 180, 'vaccine_cost': 120, 'neglect_hours': 48,
    'vet_dead_days': 3,
    'pet_death_penalty': 150,
    # EXP por ação (o servidor concede somente após a transação confirmada).
    'xp_pet_self': 8, 'xp_pet_visit': 12, 'xp_feed_self': 12, 'xp_feed_visit': 15,
    'xp_trade_cards': 40, 'xp_trade_coins': 40, 'xp_spend_per_25_coins': 2,
    'xp_card_comum': 8, 'xp_card_raro': 16, 'xp_card_lendário': 32, 'xp_card_prismático': 60,
    'xp_achievement': 70, 'xp_favorite_card': 12, 'xp_favorite_game': 10,
    'xp_discord_voice_minute': 4, 'xp_discord_message': 2,
    'xp_mission_claim': 20,
    'card_claim_minutes': 300,
    'card_chance_comum': 60, 'card_chance_raro': 29,
    'card_chance_lendário': 10, 'card_chance_prismático': 1,
}
MISSIONS = [
    ('daily_card', 'Resgate um card', 1, 12),
    ('daily_coins', 'Resgate suas moedas diárias', 1, 8),
    ('trade', 'Conclua uma troca', 1, 30),
    ('pet', 'Acaricie seu Pet', 1, 8),
    ('feed', 'Alimente seu Pet', 1, 12),
    ('adopt', 'Adote um Pet', 1, 20),
    ('pack', 'Abra um pacote do Inventário', 1, 15),
]
# Preços mínimos de ofertas e valores de venda de cópias EXTRAS (sem gerar mais cards).
COIN_OFFER_MIN = {'comum': 35, 'raro': 110, 'lendário': 350, 'prismático': 850}
DUPLICATE_SALE = {'comum': 10, 'raro': 40, 'lendário': 120, 'prismático': 300}
DEFAULT_COLLECTIONS = ('Celebridades', 'Personagens', 'Memes')
EXPEDITIONS = {
    'passeio': {'name': 'Passeio no bosque', 'minutes': 60, 'food': 12, 'coins': (12, 22), 'card_chance': 2},
    'exploracao': {'name': 'Exploração das ruínas', 'minutes': 180, 'food': 28, 'coins': (30, 50), 'card_chance': 5},
    'jornada': {'name': 'Jornada distante', 'minutes': 480, 'food': 45, 'coins': (62, 90), 'card_chance': 8},
}
GAMES = [
    ('league','League of Legends','⚔️'),('valorant','VALORANT','🎯'),('minecraft','Minecraft','⛏️'),
    ('roblox','Roblox','🧱'),('fortnite','Fortnite','🪂'),('cs2','Counter-Strike 2','🔫'),
    ('genshin','Genshin Impact','🌠'),('marvel','Marvel Rivals','🦸'),('stardew','Stardew Valley','🌾'),
    ('overwatch','Overwatch 2','🛡️'),('rocket','Rocket League','🚗'),('dota','Dota 2','🗡️'),
    ('apex','Apex Legends','🏹'),('gta','GTA V','🚘'),('terraria','Terraria','🌳'),
    ('deadby','Dead by Daylight','🔦'),('warframe','Warframe','🤖'),('rust','Rust','🪓'),
    ('ffxiv','Final Fantasy XIV','🐉'),    ('honkai','Honkai: Star Rail','🚂'),
    ('aniimo','Aniimo','🐾'),('mk1','Mortal Kombat 1','🥊'),
    ('elden-ring','Elden Ring','⚔️'),('tft','Teamfight Tactics','♟️'),
    ('pokemon','Pokémon','⚡'),('pubg','PUBG: Battlegrounds','🎯'),
    ('fc26','EA Sports FC','⚽'),('sims4','The Sims 4','💎'),
    ('hollow-knight','Hollow Knight','🗡️'),('silksong','Hollow Knight: Silksong','🦋'),
    ('hades','Hades','🔥'),('monster-hunter','Monster Hunter Wilds','🐲'),
    ('baldurs-gate','Baldur’s Gate 3','🎲'),('cyberpunk','Cyberpunk 2077','🌆'),
    ('destiny2','Destiny 2','🌌'),('among-us','Among Us','🚀'),
    ('clash-royale','Clash Royale','👑'),('brawl-stars','Brawl Stars','⭐'),
    ('fall-guys','Fall Guys','🏃'),('rainbow6','Rainbow Six Siege','🛡️'),
    ('cod-warzone','Call of Duty: Warzone','🎖️'),('diablo4','Diablo IV','👹'),
    ('sea-of-thieves','Sea of Thieves','🏴‍☠️'),('palworld','Palworld','🐣'),
    ('wuthering','Wuthering Waves','🌊'),('zenless','Zenless Zone Zero','🌀'),
    ('red-dead','Red Dead Redemption 2','🤠'),('ark','ARK: Survival Ascended','🦖'),
    ('street-fighter','Street Fighter 6','🥋'),('super-smash','Super Smash Bros. Ultimate','⭐'),
]
# Campeões conhecidos de League of Legends. A arte pode ser substituída na Central de Assets.
# Data Dragon fornece a miniatura padrão; URLs personalizadas têm prioridade.
CHAMPIONS = [
    ('Aatrox','Aatrox'),('Ahri','Ahri'),('Akali','Akali'),('Akshan','Akshan'),
    ('Alistar','Alistar'),('Ambessa','Ambessa'),('Amumu','Amumu'),('Anivia','Anivia'),
    ('Annie','Annie'),('Aphelios','Aphelios'),('Ashe','Ashe'),('Aurelion Sol','AurelionSol'),
    ('Aurora','Aurora'),('Azir','Azir'),('Bard','Bard'),('Bel’Veth','Belveth'),
    ('Blitzcrank','Blitzcrank'),('Brand','Brand'),('Braum','Braum'),('Briar','Briar'),
    ('Caitlyn','Caitlyn'),('Camille','Camille'),('Cassiopeia','Cassiopeia'),('Cho’Gath','Chogath'),
    ('Corki','Corki'),('Darius','Darius'),('Diana','Diana'),('Dr. Mundo','DrMundo'),
    ('Draven','Draven'),('Ekko','Ekko'),('Elise','Elise'),('Evelynn','Evelynn'),
    ('Ezreal','Ezreal'),('Fiddlesticks','Fiddlesticks'),('Fiora','Fiora'),('Fizz','Fizz'),
    ('Galio','Galio'),('Gangplank','Gangplank'),('Garen','Garen'),('Gnar','Gnar'),
    ('Gragas','Gragas'),('Graves','Graves'),('Gwen','Gwen'),('Hecarim','Hecarim'),
    ('Heimerdinger','Heimerdinger'),('Hwei','Hwei'),('Illaoi','Illaoi'),('Irelia','Irelia'),
    ('Ivern','Ivern'),('Janna','Janna'),('Jarvan IV','JarvanIV'),('Jax','Jax'),
    ('Jayce','Jayce'),('Jhin','Jhin'),('Jinx','Jinx'),('K’Sante','KSante'),
    ('Kai’Sa','Kaisa'),('Kalista','Kalista'),('Karma','Karma'),('Karthus','Karthus'),
    ('Kassadin','Kassadin'),('Katarina','Katarina'),('Kayle','Kayle'),('Kayn','Kayn'),
    ('Kennen','Kennen'),('Kha’Zix','Khazix'),('Kindred','Kindred'),('Kled','Kled'),
    ('Kog’Maw','KogMaw'),('LeBlanc','Leblanc'),('Lee Sin','LeeSin'),('Leona','Leona'),
    ('Lillia','Lillia'),('Lissandra','Lissandra'),('Lucian','Lucian'),('Lulu','Lulu'),
    ('Lux','Lux'),('Malphite','Malphite'),('Malzahar','Malzahar'),('Maokai','Maokai'),
    ('Master Yi','MasterYi'),('Milio','Milio'),('Miss Fortune','MissFortune'),('Mordekaiser','Mordekaiser'),
    ('Morgana','Morgana'),('Naafiri','Naafiri'),('Nami','Nami'),('Nasus','Nasus'),
    ('Nautilus','Nautilus'),('Neeko','Neeko'),('Nidalee','Nidalee'),('Nilah','Nilah'),
    ('Nocturne','Nocturne'),('Nunu e Willump','Nunu'),('Olaf','Olaf'),('Orianna','Orianna'),
    ('Ornn','Ornn'),('Pantheon','Pantheon'),('Poppy','Poppy'),('Pyke','Pyke'),
    ('Qiyana','Qiyana'),('Quinn','Quinn'),('Rakan','Rakan'),('Rammus','Rammus'),
    ('Rek’Sai','RekSai'),('Rell','Rell'),('Renata Glasc','Renata'),('Renekton','Renekton'),
    ('Rengar','Rengar'),('Riven','Riven'),('Rumble','Rumble'),('Ryze','Ryze'),
    ('Samira','Samira'),('Sejuani','Sejuani'),('Senna','Senna'),('Seraphine','Seraphine'),
    ('Sett','Sett'),('Shaco','Shaco'),('Shen','Shen'),('Shyvana','Shyvana'),
    ('Singed','Singed'),('Sion','Sion'),('Sivir','Sivir'),('Skarner','Skarner'),
    ('Smolder','Smolder'),('Sona','Sona'),('Soraka','Soraka'),('Swain','Swain'),
    ('Sylas','Sylas'),('Syndra','Syndra'),('Tahm Kench','TahmKench'),('Taliyah','Taliyah'),
    ('Talon','Talon'),('Taric','Taric'),('Teemo','Teemo'),('Thresh','Thresh'),
    ('Tristana','Tristana'),('Trundle','Trundle'),('Tryndamere','Tryndamere'),('Twisted Fate','TwistedFate'),
    ('Twitch','Twitch'),('Udyr','Udyr'),('Urgot','Urgot'),('Varus','Varus'),
    ('Vayne','Vayne'),('Veigar','Veigar'),('Vel’Koz','Velkoz'),('Vex','Vex'),
    ('Vi','Vi'),('Viego','Viego'),('Viktor','Viktor'),('Vladimir','Vladimir'),
    ('Volibear','Volibear'),('Warwick','Warwick'),('Wukong','MonkeyKing'),('Xayah','Xayah'),
    ('Xerath','Xerath'),('Xin Zhao','XinZhao'),('Yasuo','Yasuo'),('Yone','Yone'),
    ('Yorick','Yorick'),('Yuumi','Yuumi'),('Zac','Zac'),('Zed','Zed'),
    ('Zeri','Zeri'),('Ziggs','Ziggs'),('Zilean','Zilean'),('Zoe','Zoe'),('Zyra','Zyra'),
    ('Locke','Locke'),('Mel','Mel'),('Yunara','Yunara'),('Zaahen','Zaahen'),
]

SEED_CARDS = {
    'comum': ['Folha do Recanto', 'Brilho do Bosque', 'Lagoa Serena', 'Raposa Curiosa',
              'Céu de Outono', 'Cogumelo Azul', 'Pequeno Guardião', 'Concha de Sol',
              'Chuva de Estrelas', 'Esquilo Mensageiro', 'Borboleta Lunar', 'Chá do Vale',
              'Jardim Suspenso', 'Sapo Saltitante', 'Nuvem de Algodão', 'Pena Dourada'],
    'raro': ['Fênix Jovem', 'Lobo de Cristal', 'Templo Oculto', 'Jardim Noturno',
             'Feiticeira do Vale', 'Cervo Celeste', 'Espelho Encantado', 'Pássaro das Marés',
             'Guardiã das Flores', 'Orvalho de Safira', 'Sentinela do Norte', 'Rosa Astral'],
    'lendário': ['Dragão do Crepúsculo', 'Rainha do Inverno', 'Relicário Eterno',
                  'Oráculo do Tempo', 'Espírito das Montanhas', 'Biblioteca Infinita',
                  'Leviatã de Prata', 'Coroa Solar', 'Cavaleiro da Aurora'],
    'prismático': ['Eclipse Prismático', 'Coração do Universo', 'Rei das Estrelas',
                   'Portal Arco-Íris', 'A Última Constelação'],
}
# Espaços reservados: artes/modelos de Pequenas Lendas devem ser fornecidos pelo administrador.
SEED_PETS = [('Pet — exemplo 1', '🐾'), ('Pet — exemplo 2', '✨')]
SHOP_EMOJI = {'pack3':'🃏','pack5':'🎴','treat3':'🍪','fruit':'🍓','feast':'🍖','vaccine':'💉'}
TREAT_TYPES = {'biscoito':{'name':'Biscoito','food':15,'emoji':'🍪'},
               'fruta':{'name':'Frutinha','food':30,'emoji':'🍓'},
               'banquete':{'name':'Banquete','food':55,'emoji':'🍖'},
               'vacina':{'name':'Vacina','food':0,'emoji':'💉'}}
MISSION_EMOJI = {'daily_card':'🃏','daily_coins':'🪙','trade':'🔄','pet':'💗','feed':'🍪','adopt':'🐾','pack':'🎁','voice_minutes':'🎙️','message_count':'💬','profile_visit':'👤','expedition_start':'🗺️','collectible_gain':'🎁','favorite_game':'🎮','favorite_champion':'⚔️'}
# Eventos de voz e mensagens só são aceitos do bot autenticado, nunca do navegador.
SEED_BADGES = [
    ('Primeira Troca', 'Troque seu primeiro card com outro membro.', '🤝', 'trade', 1),
    ('Colecionador', 'Receba 10 cards em sua coleção.', '🃏', 'card', 10),
    ('Companheiro', 'Adote seu primeiro Pet.', '🐾', 'adopt', 1),
    ('Carinho de Ouro', 'Acaricie seu Pet 10 vezes.', '💞', 'pet', 10),
    ('Rotina de Ouro', 'Resgate 10 recompensas de missões.', '🏅', 'mission', 10),
    ('Voz da Comunidade', 'Permaneça 600 minutos em canais de voz do Discord.', '🎙️', 'voice_minutes', 600),
]

TIMEZONE_NAME = os.getenv('RECANTO_TIMEZONE', 'America/Sao_Paulo')
try:
    GAME_TZ = ZoneInfo(TIMEZONE_NAME)
except ZoneInfoNotFoundError:
    GAME_TZ = timezone(timedelta(hours=-3))


def register_game(*, app, Base, engine, SessionLocal, User, Wallet, Card, OwnedCard,
                  current_user_id, utcnow, naive_to_utc, dev_request,
                  demo_enabled, root: Path, frontend: Path, mission_tracker=None):
    class UIAsset(Base):
        """Imagens personalizadas por elemento/jogo, administradas no servidor."""
        __tablename__ = 'ui_assets'
        key: Mapped[str] = mapped_column(String(70), primary_key=True)
        selector: Mapped[str] = mapped_column(String(180), default='')
        mode: Mapped[str] = mapped_column(String(14), default='background')
        image_url: Mapped[str] = mapped_column(String(512), nullable=False)

    class UiPersonalization(Base):
        """Textos e cores por modo/resolução. Migração aditiva, sem tocar em dados existentes."""
        __tablename__ = 'recanto_ui_personalization'
        kind: Mapped[str] = mapped_column(String(12), primary_key=True)
        scope: Mapped[str] = mapped_column(String(32), primary_key=True)
        key: Mapped[str] = mapped_column(String(64), primary_key=True)
        source: Mapped[str] = mapped_column(Text, nullable=False, default='')
        value: Mapped[str] = mapped_column(Text, nullable=False, default='')

    class GameSetting(Base):
        __tablename__ = 'game_settings'
        key: Mapped[str] = mapped_column(String(45), primary_key=True)
        value: Mapped[int] = mapped_column(Integer, nullable=False)

    class RecantoEvent(Base):
        """Campanhas independentes, agendadas por horário de Brasília e avaliadas pelo servidor."""
        __tablename__ = 'recanto_events'
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        name: Mapped[str] = mapped_column(String(100), nullable=False)
        description: Mapped[str] = mapped_column(String(240), nullable=False, default='')
        emoji: Mapped[str] = mapped_column(String(24), nullable=False, default='✨')
        kind: Mapped[str] = mapped_column(String(32), nullable=False)
        value: Mapped[int] = mapped_column(Integer, nullable=False)
        mode: Mapped[str] = mapped_column(String(12), nullable=False, default='manual')
        enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
        starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
        ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    class GameLock(Base):
        __tablename__ = 'game_lock'
        id: Mapped[int] = mapped_column(Integer, primary_key=True)

    class Claim(Base):
        __tablename__ = 'daily_claims'
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        kind: Mapped[str] = mapped_column(String(30), primary_key=True)
        day: Mapped[str] = mapped_column(String(10), nullable=False)

    class MissionProgress(Base):
        __tablename__ = 'mission_progress'
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        day: Mapped[str] = mapped_column(String(10), primary_key=True)
        mission: Mapped[str] = mapped_column(String(30), primary_key=True)
        progress: Mapped[int] = mapped_column(Integer, default=0)
        claimed: Mapped[bool] = mapped_column(Boolean, default=False)

    class Trade(Base):
        __tablename__ = 'card_trades'
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        sender_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False)
        receiver_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False)
        offered_id: Mapped[int] = mapped_column(ForeignKey('owned_cards.id'), nullable=False)
        wanted_id: Mapped[int] = mapped_column(ForeignKey('owned_cards.id'), nullable=False)
        status: Mapped[str] = mapped_column(String(20), default='pendente')
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
        resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    class CoinOffer(Base):
        __tablename__ = 'coin_offers'
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        buyer_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False)
        seller_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False)
        owned_id: Mapped[int] = mapped_column(ForeignKey('owned_cards.id'), nullable=False)
        amount: Mapped[int] = mapped_column(Integer, nullable=False)
        status: Mapped[str] = mapped_column(String(20), default='pendente')
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    class CardCooldown(Base):
        __tablename__ = 'card_cooldowns'
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        last_claimed: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    class FavoriteGame(Base):
        __tablename__ = 'favorite_games'
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        game_id: Mapped[str] = mapped_column(String(32), primary_key=True)
        position: Mapped[int] = mapped_column(Integer, nullable=False)

    class FavoriteChampion(Base):
        __tablename__ = 'favorite_champions'
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        champion_id: Mapped[str] = mapped_column(String(40), primary_key=True)
        position: Mapped[int] = mapped_column(Integer, nullable=False)

    class FeaturedCollection(Base):
        __tablename__ = 'featured_collections'
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        name: Mapped[str] = mapped_column(String(100), nullable=False)
        image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    class CollectionCardStyle(Base):
        """Visual separado da arte do Card: moldura e emblema por coleção."""
        __tablename__ = 'collection_card_styles'
        collection_name: Mapped[str] = mapped_column(String(100), primary_key=True)
        frame_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
        emblem_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    class PetExpedition(Base):
        __tablename__ = 'pet_expeditions'
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        mission: Mapped[str] = mapped_column(String(30), nullable=False)
        started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
        ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
        coins: Mapped[int] = mapped_column(Integer, nullable=False)
        card_award: Mapped[bool] = mapped_column(Boolean, default=False)
        reward_card_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
        reward_collectible_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
        reward_rarities: Mapped[str | None] = mapped_column(String(512), nullable=True)
        # Custos congelados no envio: uma edição do administrador não altera expedições já iniciadas.
        cost_food: Mapped[int | None] = mapped_column(Integer, nullable=True)
        cost_happiness: Mapped[int | None] = mapped_column(Integer, nullable=True)
        cost_health: Mapped[int | None] = mapped_column(Integer, nullable=True)
        display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    class MissionActionDaily(Base):
        # Impede o usuário de farmar missões recarregando perfis ou salvando os mesmos favoritos.
        __tablename__ = 'recanto_mission_action_daily'
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        day: Mapped[str] = mapped_column(String(10), primary_key=True)
        kind: Mapped[str] = mapped_column(String(40), primary_key=True)
        target: Mapped[str] = mapped_column(String(45), primary_key=True)

    class RecantoMissionExtra(Base):
        # Missões das novas ações sem depender do main.py, que não vem no pacote incremental.
        __tablename__='recanto_extra_missions'
        code: Mapped[str]=mapped_column(String(40), primary_key=True)
        title: Mapped[str]=mapped_column(String(120), nullable=False)
        kind: Mapped[str]=mapped_column(String(15), nullable=False)
        event: Mapped[str]=mapped_column(String(40), nullable=False)
        goal: Mapped[int]=mapped_column(Integer, nullable=False)
        reward: Mapped[int]=mapped_column(Integer, nullable=False)
        emoji: Mapped[str]=mapped_column(String(30), default='🎯')
        image_url: Mapped[str | None]=mapped_column(String(512), nullable=True)
        enabled: Mapped[bool]=mapped_column(Boolean, nullable=False, default=True)

    class RecantoMissionExtraProgress(Base):
        __tablename__='recanto_extra_mission_progress'
        user_id: Mapped[str]=mapped_column(ForeignKey('users.id'), primary_key=True)
        code: Mapped[str]=mapped_column(String(40), primary_key=True)
        period: Mapped[str]=mapped_column(String(10), primary_key=True)
        amount: Mapped[int]=mapped_column(Integer, nullable=False, default=0)
        claimed: Mapped[bool]=mapped_column(Boolean, nullable=False, default=False)

    class ExpeditionConfig(Base):
        __tablename__ = 'expedition_configs'
        code: Mapped[str] = mapped_column(String(30), primary_key=True)
        name: Mapped[str | None] = mapped_column(String(100), nullable=True)
        minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
        food: Mapped[int | None] = mapped_column(Integer, nullable=True)
        happiness: Mapped[int | None] = mapped_column(Integer, nullable=True)
        health: Mapped[int | None] = mapped_column(Integer, nullable=True)
        coin_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
        coin_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
        enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
        image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
        card_chance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
        rarity_weights: Mapped[str] = mapped_column(String(512), nullable=False, default='{}')
        featured_card_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
        collectible_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
        collectible_chance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    class Collectible(Base):
        __tablename__ = 'collectibles'
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        name: Mapped[str] = mapped_column(String(100), nullable=False)
        description: Mapped[str] = mapped_column(String(300), default='')
        emoji: Mapped[str] = mapped_column(String(30), default='🏆')
        image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
        active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
        rarity: Mapped[str] = mapped_column(String(18), nullable=False, default='comum')

    class InventoryCollectible(Base):
        __tablename__ = 'inventory_collectibles'
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        collectible_id: Mapped[int] = mapped_column(ForeignKey('collectibles.id'), primary_key=True)
        quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
        acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    class CollectibleDeal(Base):
        """Negociação de UM colecionável; só uma expedição gera itens novos.

        swap: proponente oferece seu item e pede item do destinatário;
        buy: proponente reserva moedas para adquirir item do destinatário;
        sell: proponente oferece item e pede moedas do destinatário.
        """
        __tablename__ = 'collectible_deals'
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        sender_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False)
        receiver_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False)
        kind: Mapped[str] = mapped_column(String(12), nullable=False)
        offered_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
        wanted_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
        amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
        status: Mapped[str] = mapped_column(String(20), default='pendente', nullable=False)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
        resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    class TradeReward(Base):
        __tablename__ = 'trade_rewards'
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        day: Mapped[str] = mapped_column(String(10), primary_key=True)
        count: Mapped[int] = mapped_column(Integer, default=0)

    class Achievement(Base):
        __tablename__ = 'achievements'
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        title: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
        description: Mapped[str] = mapped_column(String(255), nullable=False)
        icon: Mapped[str] = mapped_column(String(30), default='🏅')
        event: Mapped[str] = mapped_column(String(30), nullable=False)
        target: Mapped[int] = mapped_column(Integer, nullable=False)
        image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
        active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    class AchievementProgress(Base):
        __tablename__ = 'achievement_progress'
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        event: Mapped[str] = mapped_column(String(30), primary_key=True)
        counter: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    class FeedEvent(Base):
        __tablename__ = 'recanto_feed_events'
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
        kind: Mapped[str] = mapped_column(String(32), nullable=False)
        payload: Mapped[str] = mapped_column(String(4096), nullable=False)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    class FeedReply(Base):
        __tablename__ = 'recanto_feed_replies'
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        event_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
        user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
        message: Mapped[str] = mapped_column(String(400), nullable=False)
        payload: Mapped[str] = mapped_column(String(2048), nullable=False, default='{}')
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    class FeedLike(Base):
        __tablename__ = 'recanto_feed_likes'
        event_id: Mapped[int] = mapped_column(Integer, primary_key=True)
        user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    class FeedDailyReward(Base):
        __tablename__ = 'recanto_feed_daily_likes'
        user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
        day: Mapped[str] = mapped_column(String(10), primary_key=True)
        count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Progressão contínua, independente do saldo de moedas e do nível exibido.
    class UserExperience(Base):
        __tablename__='recanto_user_experience'
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        total_xp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    class ExperienceOnce(Base):
        __tablename__='recanto_experience_once'
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        action_key: Mapped[str] = mapped_column(String(100), primary_key=True)

    class ExperienceLog(Base):
        __tablename__='recanto_experience_log'
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False, index=True)
        event: Mapped[str] = mapped_column(String(55), nullable=False)
        delta: Mapped[int] = mapped_column(Integer, nullable=False)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    class LevelRank(Base):
        __tablename__='recanto_level_ranks'
        start_level: Mapped[int] = mapped_column(Integer, primary_key=True)
        name: Mapped[str] = mapped_column(String(80), nullable=False)
        icon: Mapped[str] = mapped_column(String(30), nullable=False, default='⭐')
        image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    class DiscordActivityEvent(Base):
        """Recibo idempotente; cada mensagem/minuto do Discord so conta uma vez."""
        __tablename__ = 'recanto_discord_activity_events'
        event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
        guild_id: Mapped[str] = mapped_column(String(32), nullable=False)
        user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
        kind: Mapped[str] = mapped_column(String(24), nullable=False)
        occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
        received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
        counted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    class DiscordRosterMember(Base):
        """Diretório mínimo enviado pela Oracle; nunca armazena mensagens ou tokens."""
        __tablename__='recanto_discord_roster'
        user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
        guild_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
        display_name: Mapped[str] = mapped_column(String(100), nullable=False)
        username: Mapped[str] = mapped_column(String(100), nullable=False, default='')
        avatar_url: Mapped[str | None] = mapped_column(String(350), nullable=True)
        bot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
        sync_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
        synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    class DiscordMessageRate(Base):
        __tablename__ = 'recanto_discord_message_rate'
        user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
        last_counted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    class UserAchievement(Base):
        __tablename__ = 'user_achievements'
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        achievement_id: Mapped[int] = mapped_column(ForeignKey('achievements.id'), primary_key=True)
        unlocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    class PetSpecies(Base):
        __tablename__ = 'pet_species'
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
        emoji: Mapped[str] = mapped_column(String(30), default='🐾')
        image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
        model_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
        idle_animation: Mapped[str | None] = mapped_column(String(80), nullable=True)
        pet_animation: Mapped[str | None] = mapped_column(String(80), nullable=True)
        feed_animation: Mapped[str | None] = mapped_column(String(80), nullable=True)
        vet_animation: Mapped[str | None] = mapped_column(String(80), nullable=True)
        active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    class ShopItemControl(Base):
        __tablename__ = 'shop_item_controls'
        sku: Mapped[str] = mapped_column(String(30), primary_key=True)
        name: Mapped[str | None] = mapped_column(String(100), nullable=True)
        active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    class ProductCover(Base):
        __tablename__ = 'product_covers'
        sku: Mapped[str] = mapped_column(String(30), primary_key=True)
        image_url: Mapped[str] = mapped_column(String(512), nullable=False)

    class MissionCover(Base):
        __tablename__ = 'mission_covers'
        code: Mapped[str] = mapped_column(String(30), primary_key=True)
        image_url: Mapped[str] = mapped_column(String(512), nullable=False)

    class UserPet(Base):
        __tablename__ = 'user_pets'
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        species_id: Mapped[int] = mapped_column(ForeignKey('pet_species.id'), nullable=False)
        nickname: Mapped[str | None] = mapped_column(String(40), nullable=True)
        equipped_collectible_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
        status: Mapped[str] = mapped_column(String(15), default='ativo')
        food: Mapped[int] = mapped_column(Integer, default=85)
        happiness: Mapped[int] = mapped_column(Integer, default=85)
        health: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
        luck: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Sorte fixa nesta adocao (1 a 10)
        adopted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
        last_action_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
        last_tick_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
        last_feed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
        last_pet_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
        vet_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
        death_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
        death_penalty_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


    # v0.7: pacotes persistem fechados; a reserva impede extrapolar copias globais.
    class InventoryPack(Base):
        __tablename__ = 'inventory_packs'
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False, index=True)
        sku: Mapped[str] = mapped_column(String(20), nullable=False)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
        opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    class ReservedCard(Base):
        __tablename__ = 'pack_reserved_cards'
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        pack_id: Mapped[int] = mapped_column(ForeignKey('inventory_packs.id'), nullable=False)
        card_id: Mapped[int] = mapped_column(ForeignKey('cards.id'), nullable=False)
        position: Mapped[int] = mapped_column(Integer, nullable=False)

    class InventoryTreat(Base):
        __tablename__ = 'inventory_treats'
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        sku: Mapped[str] = mapped_column(String(24), primary_key=True)
        quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    class FavoriteCard(Base):
        __tablename__ = 'favorite_cards'
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        owned_id: Mapped[int] = mapped_column(ForeignKey('owned_cards.id'), nullable=False)

    class AdminPermission(Base):
        __tablename__ = 'admin_permissions'
        discord_id: Mapped[str] = mapped_column(String(32), primary_key=True)

    class VisitorCare(Base):
        __tablename__ = 'visitor_pet_care'
        visitor_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        day: Mapped[str] = mapped_column(String(10), primary_key=True)
        action: Mapped[str] = mapped_column(String(10), primary_key=True)

    # 0.1.3: arquivamento reversivel. Preserva chaves estrangeiras, cards ja ganhos e pets adotados.
    for table in ('cards', 'achievements', 'pet_species'):
        if inspect(engine).has_table(table):
            cols = {c['name'] for c in inspect(engine).get_columns(table)}
            if 'active' not in cols:
                with engine.begin() as connection:
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN active BOOLEAN NOT NULL DEFAULT TRUE'))

    # Migracao aditiva de cards para v0.8. Bancos anteriores preservam colecoes e copias.
    if inspect(engine).has_table('cards'):
        present_cards = {col['name'] for col in inspect(engine).get_columns('cards')}
        with engine.begin() as connection:
            if 'collection_name' not in present_cards:
                connection.execute(text("ALTER TABLE cards ADD COLUMN collection_name VARCHAR(100) NOT NULL DEFAULT 'Recanto Original'"))
            if 'created_at' not in present_cards:
                connection.execute(text('ALTER TABLE cards ADD COLUMN created_at TIMESTAMP'))
    # Upgrade aditivo e seguro dos bancos v0.5 existentes, sem apagar colecoes.
    if inspect(engine).has_table('pet_species'):
        present = {col['name'] for col in inspect(engine).get_columns('pet_species')}
        with engine.begin() as connection:
            for field in ('model_url', 'idle_animation', 'pet_animation', 'feed_animation', 'vet_animation'):
                if field not in present:
                    connection.execute(text(f'ALTER TABLE pet_species ADD COLUMN {field} VARCHAR(512)' if field == 'model_url' else f'ALTER TABLE pet_species ADD COLUMN {field} VARCHAR(80)'))
    # 0.1.21: migracoes aditivas, sem perder Pets, expedicoes ou colecoes antigas.
    for table, fields in {
        'user_pets': {'nickname': 'VARCHAR(40)', 'equipped_collectible_id': 'INTEGER',
                      'death_at': 'TIMESTAMP', 'death_penalty_applied': 'BOOLEAN NOT NULL DEFAULT FALSE',
                      'health': 'INTEGER NOT NULL DEFAULT 100', 'luck': 'INTEGER'},
        'expedition_configs': {
            'name': 'VARCHAR(100)', 'minutes': 'INTEGER', 'food': 'INTEGER',
            'happiness': 'INTEGER', 'health': 'INTEGER',
            'coin_min': 'INTEGER', 'coin_max': 'INTEGER',
            'enabled': 'BOOLEAN NOT NULL DEFAULT TRUE',
        },
        'collectibles': {'rarity': "VARCHAR(18) NOT NULL DEFAULT 'comum'"},
        'pet_expeditions': {
            'cost_food': 'INTEGER', 'cost_happiness': 'INTEGER',
            'cost_health': 'INTEGER', 'display_name': 'VARCHAR(100)',
            'reward_card_id': 'INTEGER',
            'reward_collectible_id': 'INTEGER',
            'reward_rarities': 'VARCHAR(512)',
        },
    }.items():
        if inspect(engine).has_table(table):
            existing = {column['name'] for column in inspect(engine).get_columns(table)}
            with engine.begin() as connection:
                for field, sql_type in fields.items():
                    if field not in existing:
                        connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {field} {sql_type}'))
                # Falecimentos anteriores à atualização não são cobrados retroativamente.
                if table == 'user_pets' and 'death_penalty_applied' not in existing:
                    connection.execute(text("UPDATE user_pets SET death_penalty_applied = TRUE WHERE status = 'morto'"))
    Base.metadata.create_all(engine)
    with SessionLocal.begin() as ranks_db:
        if not ranks_db.scalar(select(func.count(LevelRank.start_level))):
            for first, name, icon in [(1,'Iniciante','🌱'),(5,'Explorador','🧭'),(10,'Guardião','🛡️'),(20,'Veterano','⚔️'),(35,'Mestre','💠'),(50,'Lendário','👑')]:
                ranks_db.add(LevelRank(start_level=first,name=name,icon=icon))
    # Atualizacao unica dos Pets ja adotados. Nenhuma visita pode rerrolar a Sorte.
    with SessionLocal.begin() as migration_db:
        old_pets=migration_db.scalars(select(UserPet).where(UserPet.luck.is_(None))).all()
        for old_pet in old_pets:
            old_pet.luck=RANDOM.randint(1,10)
    with SessionLocal.begin() as db:
        if not db.get(FeaturedCollection,1):
            db.add(FeaturedCollection(id=1, name='Celebridades'))
        if not db.get(GameLock, 1):
            db.add(GameLock(id=1))
        previous={'daily_coins':100,'trade_bonus':30,'trade_reward_limit':3,
                  'pack3_cost':250,'pack5_cost':500,'treat_bundle_cost':90,'treat_fruit_cost':75,
                  'treat_feast_cost':135,'visit_pet_reward':10,'visit_feed_reward':15,
                  'visit_owner_reward':4,'vet_cost':240}
        for k, v in DEFAULTS.items():
            old=db.get(GameSetting,k)
            if not old: db.add(GameSetting(key=k,value=v))
            elif k in previous and old.value==previous[k]: old.value=v
            # Migrar apenas os precos padrao da v0.9, preservando outros ajustes feitos pelo admin.
            elif k=='pack3_cost' and old.value==850: old.value=700
            elif k=='pack5_cost' and old.value==600: old.value=550
        # O antigo bonus fixo de 5 moedas nao e mais utilizado nem exibido na Gestao.
        legacy_bonus=db.get(GameSetting,'card_bonus')
        if legacy_bonus: db.delete(legacy_bonus)
        # 0.2.1: o catálogo vazio após uma limpeza administrativa deve continuar vazio
        # no próximo reinício, sem recriar os Cards de demonstração.
        if not db.get(GameSetting, 'cards_initialized'):
            if not (db.scalar(select(func.count(Card.id))) or 0):
                for tier, names in SEED_CARDS.items():
                    for name in names:
                        db.add(Card(name=name, rarity=tier, image_url=None))
            db.add(GameSetting(key='cards_initialized', value=1))
        if not (db.scalar(select(func.count(PetSpecies.id))) or 0):
            for name, emoji in SEED_PETS:
                db.add(PetSpecies(name=name, emoji=emoji))
        if not (db.scalar(select(func.count(Achievement.id))) or 0):
            for name, description, icon, event, threshold in SEED_BADGES:
                db.add(Achievement(title=name, description=description, icon=icon,
                                   event=event, target=threshold))

    # Retira contas de teste antigas da v0.5/v0.6, preservando pessoas reais.
    # Elas eram criadas apenas pelo login ficticio e nunca tiveram Discord ID numerico.
    with SessionLocal.begin() as db:
        demo_ids = db.scalars(select(User.id).where(User.id.like('teste_%'))).all()
        if demo_ids:
            for uid in demo_ids:
                for cls, key in ((ReservedCard, None), (VisitorCare, 'visitor_id'), (VisitorCare, 'owner_id'),
                                 (InventoryPack, 'user_id'), (InventoryTreat, 'user_id'),
                                 (FavoriteCard, 'user_id'), (Trade, 'sender_id'), (Trade, 'receiver_id'),
                                 (CollectibleDeal,'sender_id'),(CollectibleDeal,'receiver_id'),
                                 (TradeReward, 'user_id'), (MissionProgress, 'user_id'), (MissionActionDaily,'user_id'), (RecantoMissionExtraProgress,'user_id'), (UserExperience,'user_id'), (ExperienceOnce,'user_id'), (ExperienceLog,'user_id'),
                                 (Claim, 'user_id'), (UserAchievement, 'user_id'),
                                 (AchievementProgress, 'user_id'), (DiscordActivityEvent, 'user_id'), (DiscordMessageRate, 'user_id'), (UserPet, 'user_id'),
                                 (OwnedCard, 'user_id'), (CardCooldown, 'user_id'), (FavoriteGame,'user_id'), (FavoriteChampion,'user_id'), (InventoryCollectible,'user_id'),
                                 (CoinOffer,'buyer_id'), (CoinOffer,'seller_id'), (PetExpedition,'user_id')):
                    if cls is ReservedCard:
                        packids = db.scalars(select(InventoryPack.id).where(InventoryPack.user_id == uid)).all()
                        if packids: db.execute(delete(ReservedCard).where(ReservedCard.pack_id.in_(packids)))
                    else:
                        db.execute(delete(cls).where(getattr(cls,key)==uid))
                session_table = Base.metadata.tables['sessions']
                notif_table = Base.metadata.tables['notification_preferences']
                db.execute(delete(session_table).where(session_table.c.user_id==uid))
                db.execute(delete(notif_table).where(notif_table.c.user_id==uid))
                db.execute(delete(Wallet).where(Wallet.user_id==uid))
                db.execute(delete(User).where(User.id==uid))
        # Upgrade de petiscos legados para o inventario tipado.
        for w in db.scalars(select(Wallet)).all():
            if w.treats > 0 and not db.get(InventoryTreat, (w.user_id, 'biscoito')):
                db.add(InventoryTreat(user_id=w.user_id, sku='biscoito', quantity=w.treats))

    @contextmanager
    def writing():
        """Transação única para evitar compras duplicadas e emissões acima do limite."""
        db = SessionLocal()
        try:
            if engine.dialect.name == 'sqlite':
                db.connection().exec_driver_sql('BEGIN IMMEDIATE')
            else:
                db.execute(select(GameLock.id).where(GameLock.id == 1).with_for_update()).one()
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def me(request: Request):
        uid = current_user_id(request)
        if uid is None:
            raise HTTPException(401, detail='Entre na sua conta primeiro')
        return uid

    def is_admin(uid: str, request: Request):
        allowed = {x.strip() for x in os.getenv('RECANTO_ADMIN_DISCORD_IDS', '249610270069096448').split(',') if x.strip().isdigit()}
        if not uid.isdecimal(): return False
        if uid in allowed: return True
        with SessionLocal() as db:
            return db.get(AdminPermission, uid) is not None

    def only_admin(request):
        uid = me(request)
        if not is_admin(uid, request):
            raise HTTPException(403, detail='Somente o administrador pode realizar esta ação')
        return uid

    def test_admin(request):
        uid = only_admin(request)
        if not (dev_request(request) and os.getenv('APP_ENV', 'development') == 'development'):
            raise HTTPException(403, detail='Simulações apenas para administradores no PC')
        return uid

    def json_body(data, keys):
        if not isinstance(data, dict) or any(key not in data for key in keys):
            raise HTTPException(422, detail='Dados incompletos')
        return data

    def integer(value):
        if type(value) is not int:
            raise HTTPException(422, detail='Informe um número inteiro')
        return value

    def setting(db, key):
        return db.get(GameSetting, key).value

    EVENT_KINDS = {
        'card_cooldown': ('Resgate acelerado', 30, 10080),
        'double_cards': ('Resgate duplo', 2, 2),
        'shop_discount': ('Desconto na Loja (%)', 1, 90),
        'expedition_speed': ('Expedições mais rápidas (%)', 1, 90),
        'mission_xp': ('EXP extra por Missão (%)', 1, 400),
    }

    def active_events(db, now=None):
        now=now or utcnow()
        return [e for e in db.scalars(select(RecantoEvent).where(RecantoEvent.enabled.is_(True)).order_by(RecantoEvent.id)).all()
                if (e.mode!='scheduled' or (e.starts_at is not None and e.ends_at is not None))
                and (e.starts_at is None or naive_to_utc(e.starts_at)<=now)
                and (e.ends_at is None or naive_to_utc(e.ends_at)>now)]

    def event_effects(db, now=None):
        rows=active_events(db,now)
        benefits={'card_cooldown':setting(db,'card_claim_minutes'), 'double_cards':1,
                  'shop_discount':0, 'expedition_speed':0, 'mission_xp':0}
        for item in rows:
            if item.kind=='card_cooldown':benefits[item.kind]=min(benefits[item.kind],item.value)
            elif item.kind=='double_cards':benefits[item.kind]=2
            elif item.kind in benefits:benefits[item.kind]=max(benefits[item.kind],item.value)
        return benefits

    def event_dict(row, now=None):
        now=now or utcnow()
        active=bool(row.enabled and (row.mode!='scheduled' or (row.starts_at and row.ends_at))
              and (row.starts_at is None or naive_to_utc(row.starts_at)<=now)
              and (row.ends_at is None or naive_to_utc(row.ends_at)>now))
        return {'id':row.id,'name':row.name,'description':row.description,'emoji':row.emoji,
                'kind':row.kind,'value':row.value,'mode':row.mode,'enabled':bool(row.enabled),
                'starts_at':naive_to_utc(row.starts_at).isoformat() if row.starts_at else None,
                'ends_at':naive_to_utc(row.ends_at).isoformat() if row.ends_at else None,
                'active':active}

    def event_price(db, base):
        reduction=event_effects(db)['shop_discount']
        return max(1, (int(base)*(100-reduction)+99)//100) if reduction else int(base)

    def mission_claim_experience(db, uid):
        base=setting(db,'xp_mission_claim')
        extra=event_effects(db)['mission_xp']
        return grant_experience(db,uid,base*(100+extra)//100,'missao_concluida')

    def card_claim_weights(db):
        return {tier:setting(db,'card_chance_'+tier) for tier in TIERS}

    def card_bonus(db, rarity):
        if rarity not in TIERS:
            raise HTTPException(409, detail='Raridade invalida para recompensa')
        return setting(db, 'card_bonus_'+rarity)

    def next_card_available(db, uid):
        row=db.get(CardCooldown,uid)
        return naive_to_utc(row.last_claimed)+timedelta(minutes=event_effects(db)['card_cooldown']) if row else None

    def game_entry(db, row):
        key,name,emoji=row
        image=db.get(UIAsset, 'game:'+key)
        return {'id':key, 'name':name, 'icon':emoji, 'image_url':image.image_url if image else None}

    def user_games(db, uid):
        entries=sorted(db.scalars(select(FavoriteGame).where(FavoriteGame.user_id==uid)).all(),key=lambda x:x.position)
        options={g[0]:g for g in GAMES}
        return [game_entry(db,options[g.game_id]) for g in entries if g.game_id in options]

    def champion_entry(db, row, artwork=None):
        name, slug = row
        image = artwork if artwork is not None else db.get(UIAsset, 'champion:'+slug)
        image_url = image if isinstance(image,str) else (image.image_url if image else None)
        return {'id':slug, 'name':name, 'icon':'⚔️',
                'image_url': image_url or
                    'https://ddragon.leagueoflegends.com/cdn/img/champion/tiles/'+slug+'_0.jpg'}

    def user_champions(db, uid):
        entries=sorted(db.scalars(select(FavoriteChampion).where(FavoriteChampion.user_id==uid)).all(),key=lambda x:x.position)
        options={slug:row for row in CHAMPIONS for slug in [row[1]]}
        return [champion_entry(db,options[item.champion_id]) for item in entries if item.champion_id in options]

    def wallet(db, uid):
        obj = db.get(Wallet, uid)
        if obj is None:
            raise HTTPException(409, detail='Carteira não encontrada')
        return obj

    def require_coins(db, uid, price):
        item = wallet(db, uid)
        if item.coins < price:
            raise HTTPException(409, detail=f'Moedas insuficientes. Você precisa de {price}.')
        return item


    def treat_qty(db, uid, sku):
        row = db.get(InventoryTreat, (uid, sku))
        return row.quantity if row else 0

    def give_treat(db, uid, sku, count):
        row = db.get(InventoryTreat, (uid, sku))
        if row is None:
            row = InventoryTreat(user_id=uid, sku=sku, quantity=0)
            db.add(row)
        if row.quantity + count < 0:
            raise HTTPException(409, detail='Quantidade insuficiente desse petisco')
        row.quantity += count
        # Vacinas são itens médicos no inventário, não petiscos comestíveis.
        if sku != 'vacina':
            wallet(db, uid).treats += count

    def consume_treat(db, uid, sku):
        if sku not in TREAT_TYPES:
            raise HTTPException(422, detail='Tipo de petisco invalido')
        give_treat(db, uid, sku, -1)

    def favorite_info(db, uid):
        fav = db.get(FavoriteCard, uid)
        if not fav: return None
        owned = db.get(OwnedCard, fav.owned_id)
        if not owned or owned.user_id != uid: return None
        card = db.get(Card, owned.card_id)
        return {'owned_id':owned.id, 'card_id':card.id, 'name':card.name,
                'rarity':card.rarity, 'image_url':card.image_url, 'collection':card.collection_name} if card else None

    def local_day():
        return utcnow().astimezone(GAME_TZ).date().isoformat()

    def reset_iso():
        local_now = utcnow().astimezone(GAME_TZ)
        tomorrow = (local_now + timedelta(days=1)).date()
        return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=GAME_TZ).astimezone(timezone.utc).isoformat()

    def claim_exists(db, uid, kind):
        cl = db.get(Claim, (uid, kind))
        return cl is not None and cl.day == local_day()

    def record_claim(db, uid, kind):
        if claim_exists(db, uid, kind):
            raise HTTPException(409, detail='Você já resgatou esta recompensa hoje.')
        cl = db.get(Claim, (uid, kind))
        if cl is None:
            db.add(Claim(user_id=uid, kind=kind, day=local_day()))
        else:
            cl.day = local_day()

    def xp_level_floor(level):
        # Soma fechada do custo 100+25*n+3*n² por nível anterior; nível não tem teto.
        n=max(0,int(level)-1)
        return 100*n+25*n*(n+1)//2+n*(n+1)*(2*n+1)//2

    def xp_level_of(total_xp):
        xp=max(0,int(total_xp))
        high=2
        while xp_level_floor(high)<=xp:
            high*=2  # Sem limite de nível arbitrário.
        low=1
        while low+1<high:
            mid=(low+high)//2
            if xp_level_floor(mid)<=xp:low=mid
            else:high=mid
        return low

    def level_info(db, uid):
        row=db.get(UserExperience,uid)
        total=max(0,int(row.total_xp)) if row else 0
        level=xp_level_of(total)
        earned=total-xp_level_floor(level)
        needed=xp_level_floor(level+1)-xp_level_floor(level)
        ranks=db.scalars(select(LevelRank).where(LevelRank.start_level<=level).order_by(LevelRank.start_level.desc())).all()
        rank=ranks[0] if ranks else None
        return {'level':level,'total_xp':total,'xp_current':earned,'xp_needed':needed,
                'xp_percent':round(earned*100/needed,2),
                'rank':{'name':rank.name if rank else 'Iniciante',
                        'start_level':rank.start_level if rank else 1,
                        'icon':rank.icon if rank else '⭐',
                        'image_url':rank.image_url if rank else None}}

    def grant_experience(db, uid, amount, event, once_key=None):
        amount=int(amount)
        if amount<=0:return 0
        amount=min(amount,1000000)
        if once_key:
            once_key=str(once_key)[:100]
            if db.get(ExperienceOnce,(uid,once_key)):return 0
            db.add(ExperienceOnce(user_id=uid,action_key=once_key))
            db.flush()
        row=db.get(UserExperience,uid)
        if not row:
            row=UserExperience(user_id=uid,total_xp=0);db.add(row);db.flush()
        before=row.total_xp
        row.total_xp=min(2**60,before+amount)
        gained=row.total_xp-before
        if gained:db.add(ExperienceLog(user_id=uid,event=str(event)[:55],delta=gained))
        return gained

    def xp_action(db, uid, key, event=None, once_key=None):
        return grant_experience(db,uid,setting(db,'xp_'+key),event or key,once_key)

    def xp_spend(db, uid, coins):
        # O bônus só ocorre sobre gasto confirmado, e nunca em depósito de oferta cancelável.
        amount=max(0,int(coins))
        return grant_experience(db,uid,min(150,(amount//25)*setting(db,'xp_spend_per_25_coins')),'moedas_gastas')

    @app.get('/api/levels/me')
    def my_level(request:Request):
        uid=me(request)
        with SessionLocal() as db:return {'level_info':level_info(db,uid)}

    @app.get('/api/levels/{member_id}')
    def member_level(member_id:str,request:Request):
        me(request)
        with SessionLocal() as db:
            if not db.get(User,member_id):raise HTTPException(404,detail='Membro não encontrado')
            return {'level_info':level_info(db,member_id)}

    @app.get('/api/admin/levels')
    def admin_levels(request:Request):
        only_admin(request)
        with SessionLocal() as db:
            return {'ranks':[{'start_level':r.start_level,'name':r.name,'icon':r.icon,'image_url':r.image_url}
                             for r in db.scalars(select(LevelRank).order_by(LevelRank.start_level)).all()],
                    'rewards':{key:value.value for key,value in
                               ((k,db.get(GameSetting,k)) for k in DEFAULTS if k.startswith('xp_')) if value}}

    @app.post('/api/admin/levels/ranks')
    async def admin_save_rank(request:Request):
        only_admin(request)
        data=json_body(await request.json(),('start_level','name'))
        first=integer(data['start_level']);name=str(data['name']).strip();icon=str(data.get('icon') or '⭐')[:30]
        image=str(data.get('image_url') or '').strip() or None
        old_level=data.get('old_level')
        if not 1<=first<=1000000 or not 2<=len(name)<=80 or (image and not (image.startswith('https://') or image.startswith('/uploads/'))):
            raise HTTPException(422,detail='Nível, nome ou imagem inválidos')
        if old_level is not None:old_level=integer(old_level)
        with writing() as db:
            if old_level is not None and old_level!=first:
                if old_level==1:raise HTTPException(409,detail='O ranking inicial deve começar no nível 1')
                if db.get(LevelRank,first):raise HTTPException(409,detail='Já existe ranking nesse nível')
                old=db.get(LevelRank,old_level)
                if old:db.delete(old);db.flush()
            row=db.get(LevelRank,first)
            if row:row.name=name;row.icon=icon;row.image_url=image
            else:db.add(LevelRank(start_level=first,name=name,icon=icon,image_url=image))
        return {'ok':True}

    @app.post('/api/admin/levels/ranks/delete')
    async def admin_delete_rank(request:Request):
        only_admin(request);data=json_body(await request.json(),('start_level',))
        first=integer(data['start_level'])
        if first==1:raise HTTPException(409,detail='Não é possível remover o ranking inicial')
        with writing() as db:
            row=db.get(LevelRank,first)
            if not row:raise HTTPException(404,detail='Ranking não encontrado')
            db.delete(row)
        return {'ok':True}

    @app.post('/api/admin/levels/adjust')
    async def admin_adjust_level(request:Request):
        admin_id=only_admin(request);data=json_body(await request.json(),('discord_id','action','amount'))
        target=str(data['discord_id']).strip();action=str(data['action']);amount=integer(data['amount'])
        if not target.isdecimal() or len(target)<15 or len(target)>22 or action not in ('add','remove') or not 1<=amount<=1000000:
            raise HTTPException(422,detail='Informe ID, operação e EXP válidos')
        with writing() as db:
            if not db.get(User,target):raise HTTPException(404,detail='Usuário ainda não entrou no Recanto')
            if action=='add':grant_experience(db,target,amount,'admin_bonus')
            else:
                row=db.get(UserExperience,target)
                if row:
                    decrease=min(amount,row.total_xp);row.total_xp-=decrease
                    if decrease:db.add(ExperienceLog(user_id=target,event='admin_remocao',delta=-decrease))
            db.flush()
            outcome=level_info(db,target)
        logging.getLogger('recanto.admin').info('EXP alterada: admin=%s ação=%s quantidade=%s',admin_id,action,amount)
        return {'ok':True,'level_info':outcome}

    EXTRA_EVENTS={
        'profile_visit':'Visitar o perfil de outro membro',
        'expedition_start':'Enviar o Pet para uma expedição',
        'collectible_gain':'Conseguir um colecionável',
        'favorite_game':'Definir jogos favoritos',
        'favorite_champion':'Definir campeões favoritos',
    }

    def extra_period(kind):
        if kind=='unica':return 'ever'
        today=local_day()
        if kind=='diaria':return today
        today_date=datetime.strptime(today,'%Y-%m-%d').date()
        return (today_date-timedelta(days=today_date.weekday())).isoformat()

    def extra_mission_progress(db, uid, event, amount):
        for mission in db.scalars(select(RecantoMissionExtra).where(
                RecantoMissionExtra.event==event,RecantoMissionExtra.enabled.is_(True))).all():
            key=(uid,mission.code,extra_period(mission.kind))
            row=db.get(RecantoMissionExtraProgress,key)
            if not row:
                row=RecantoMissionExtraProgress(user_id=uid,code=mission.code,
                    period=key[2],amount=0,claimed=False)
                db.add(row)
            row.amount=min(mission.goal,max(0,row.amount+amount))

    def progress(db, uid, mission, amount=1):
        day = local_day()
        obj = db.get(MissionProgress, (uid, day, mission))
        if obj is None:
            db.add(MissionProgress(user_id=uid, day=day, mission=mission, progress=amount, claimed=False))
        else:
            obj.progress = min(9999, obj.progress + amount)
        if mission in EXTRA_EVENTS:
            # Novas ações usam o sistema integrado daqui; não dependem do main.py antigo.
            extra_mission_progress(db,uid,mission,amount)
        elif mission_tracker:
            mission_tracker(db, uid, mission, amount)

    def mission_action(db, uid, kind, target='once'):
        # Ação confirmada e distinta no dia; evita farmar EXP/moedas recarregando uma tela.
        day = local_day()
        key=(uid,day,kind,str(target)[:45])
        if db.get(MissionActionDaily,key): return False
        db.add(MissionActionDaily(user_id=uid,day=day,kind=kind,target=str(target)[:45]))
        progress(db,uid,kind)
        return True

    def trim_feed(db):
        # Uma única consulta de limpeza por lote de cards em vez de uma por card.
        db.flush()
        old_ids = db.scalars(select(FeedEvent.id).order_by(FeedEvent.id.desc()).offset(100)).all()
        if old_ids:
            db.execute(delete(FeedReply).where(FeedReply.event_id.in_(old_ids)))
            db.execute(delete(FeedLike).where(FeedLike.event_id.in_(old_ids)))
            db.execute(delete(FeedEvent).where(FeedEvent.id.in_(old_ids)))

    def publish_feed(db, uid, kind, *, defer_trim=False, **payload):
        # Somente ações confirmadas pelo servidor; propostas são anúncios, não transações.
        entry = FeedEvent(user_id=uid, kind=kind, payload=json.dumps(payload, ensure_ascii=False), created_at=utcnow())
        db.add(entry)
        if not defer_trim:
            trim_feed(db)

    def feed_card(card):
        return {'name': card['name'], 'rarity': card.get('rarity', 'comum'), 'image_url': card.get('image_url')}

    def feed_pet_item(db, sku):
        sku = str(sku)
        covers = {'biscoito':'treat3','fruta':'fruit','banquete':'feast','vacina':'vaccine'}
        item = TREAT_TYPES.get(sku)
        if not item:
            return {'name':'Item de Pet','emoji':'🍪','image_url':None}
        cover_sku = covers.get(sku)
        image = db.scalar(select(ProductCover.image_url).where(ProductCover.sku==cover_sku).limit(1)) if cover_sku else None
        return {'name':item.get('name') or 'Item de Pet','emoji':item.get('emoji'),'image_url':image}

    @app.get('/api/feed')
    def community_feed(request: Request):
        uid=me(request)
        with SessionLocal() as db:
            entries=db.scalars(select(FeedEvent).order_by(FeedEvent.id.desc()).limit(60)).all()
            event_ids=[entry.id for entry in entries]
            replies=db.scalars(select(FeedReply).where(FeedReply.event_id.in_(event_ids))
                               .order_by(FeedReply.created_at,FeedReply.id)).all() if entries else []
            uids=set([e.user_id for e in entries]+[r.user_id for r in replies])
            users={u.id:u for u in db.scalars(select(User).where(User.id.in_(uids))).all()} if uids else {}
            counts=dict(db.execute(select(FeedLike.event_id,func.count(FeedLike.user_id))
                                   .where(FeedLike.event_id.in_(event_ids)).group_by(FeedLike.event_id)).all()) if entries else {}
            liked=set(db.scalars(select(FeedLike.event_id).where(FeedLike.user_id==uid,
                                      FeedLike.event_id.in_(event_ids))).all()) if entries else set()
            all_replies={eid:[] for eid in event_ids}
            for reply in replies:
                who=users.get(reply.user_id)
                all_replies[reply.event_id].append({
                    'id':reply.id,'message':reply.message,'data':json.loads(reply.payload or '{}'),
                    'created_at':naive_to_utc(reply.created_at).isoformat(),
                    'mine':reply.user_id==uid,
                    'user':{'name':who.username if who else 'Membro','avatar_url':who.avatar_url if who else None}
                })
            day_state=db.get(FeedDailyReward,(uid,local_day()))
            return {'items':[{'id':e.id,'kind':e.kind,'created_at':naive_to_utc(e.created_at).isoformat(),
                'user':{'name':users[e.user_id].username if e.user_id in users else 'Membro',
                        'avatar_url':users[e.user_id].avatar_url if e.user_id in users else None},
                'mine':e.user_id==uid,
                'data':json.loads(e.payload),'likes':counts.get(e.id,0),'liked':e.id in liked,
                'replies':all_replies[e.id] if e.kind=='trade_proposal' else []}
                for e in entries],
                'reward_today':day_state.count if day_state else 0,'reward_limit':20}

    def postable_card(db, card_id):
        card=db.get(Card,card_id)
        if not card or not card.active:
            raise HTTPException(409,detail='Card indisponível no catálogo')
        return {'id':card.id,'name':card.name,'rarity':card.rarity,
                'image_url':card.image_url,'collection':card.collection_name}

    def member_offered_card(db,uid,owned_id):
        owned=db.get(OwnedCard,owned_id)
        if not owned or owned.user_id!=uid:
            raise HTTPException(409,detail='Você precisa possuir o Card oferecido')
        card=postable_card(db,owned.card_id)
        return card

    @app.post('/api/feed/proposals')
    async def create_public_trade_proposal(request:Request):
        uid=me(request)
        payload=json_body(await request.json(),('mode',))
        mode=str(payload['mode'])
        if mode not in ('card_for_card','card_for_coins','wanted_card'):
            raise HTTPException(422,detail='Tipo de proposta inválido')
        note=str(payload.get('note') or '').strip()
        if len(note)>250:raise HTTPException(422,detail='Descrição limitada a 250 caracteres')
        with writing() as db:
            day_start=utcnow()-timedelta(days=1)
            recent=db.scalars(select(FeedEvent).where(FeedEvent.user_id==uid,
                              FeedEvent.kind=='trade_proposal',FeedEvent.created_at>=day_start)).all()
            if len(recent)>=10:raise HTTPException(429,detail='Limite de 10 propostas públicas a cada 24 horas')
            offered=member_offered_card(db,uid,integer(payload.get('offered_owned_id'))) if mode!='wanted_card' else None
            wanted=postable_card(db,integer(payload.get('wanted_card_id'))) if mode!='card_for_coins' else None
            coins=integer(payload.get('wanted_coins')) if mode=='card_for_coins' else None
            if mode=='card_for_coins' and not 1<=coins<=1000000:
                raise HTTPException(422,detail='Informe de 1 a 1.000.000 moedas')
            if mode=='card_for_card' and wanted['id']==offered['id']:
                raise HTTPException(422,detail='Selecione dois Cards diferentes')
            # A oferta não reserva moedas nem entrega Cards: somente a aceitação privada poderá fazê-lo.
            publish_feed(db,uid,'trade_proposal',mode=mode,offered_card=offered,wanted_card=wanted,
                         wanted_coins=coins,note=note,status='open')
        return {'ok':True}

    @app.post('/api/feed/{event_id}/replies')
    async def reply_public_trade_proposal(event_id:int,request:Request):
        uid=me(request)
        payload=json_body(await request.json(),('message',))
        message=str(payload.get('message') or '').strip()
        interested=bool(payload.get('interested',False))
        if interested and not message:message='Tenho interesse nesta proposta!'
        if len(message)>400:raise HTTPException(422,detail='Comentário limitado a 400 caracteres')
        with writing() as db:
            post=db.get(FeedEvent,event_id)
            if not post or post.kind!='trade_proposal':raise HTTPException(404,detail='Proposta não encontrada')
            if json.loads(post.payload).get('status')!='open':
                raise HTTPException(409,detail='Esta proposta foi encerrada')
            if post.user_id==uid and interested:
                raise HTTPException(422,detail='Você não pode demonstrar interesse na própria proposta')
            count=db.scalar(select(func.count()).select_from(FeedReply).where(FeedReply.event_id==event_id)) or 0
            mine=db.scalar(select(func.count()).select_from(FeedReply).where(FeedReply.event_id==event_id,FeedReply.user_id==uid)) or 0
            if count>=50 or mine>=12:raise HTTPException(429,detail='Limite de respostas desta conversa atingido')
            offered_id=payload.get('offered_owned_id')
            offered=member_offered_card(db,uid,integer(offered_id)) if offered_id not in (None,'') else None
            proposed_coins=payload.get('offered_coins')
            coins=integer(proposed_coins) if proposed_coins not in (None,'') else None
            if coins is not None and not 1<=coins<=1000000:raise HTTPException(422,detail='Valor inválido de moedas')
            if not message and not offered and coins is None:
                raise HTTPException(422,detail='Escreva uma resposta ou indique Card/moedas')
            if interested and db.scalar(select(FeedReply.id).where(FeedReply.event_id==event_id,
                    FeedReply.user_id==uid,FeedReply.message=='Tenho interesse nesta proposta!').limit(1)):
                raise HTTPException(409,detail='Você já demonstrou interesse')
            db.add(FeedReply(event_id=event_id,user_id=uid,message=message,
                             payload=json.dumps({'offered_card':offered,'offered_coins':coins},ensure_ascii=False),
                             created_at=utcnow()))
        return {'ok':True}

    @app.post('/api/feed/{event_id}/close')
    def close_public_trade_proposal(event_id:int,request:Request):
        uid=me(request)
        with writing() as db:
            post=db.get(FeedEvent,event_id)
            if not post or post.kind!='trade_proposal':raise HTTPException(404,detail='Proposta não encontrada')
            if post.user_id!=uid:raise HTTPException(403,detail='Somente o autor pode encerrar a proposta')
            data=json.loads(post.payload)
            data['status']='closed'
            post.payload=json.dumps(data,ensure_ascii=False)
        return {'ok':True,'status':'closed'}

    @app.post('/api/admin/feed/clear')
    async def admin_clear_feed(request: Request):
        # Exclui somente as publicações e seus likes. Não altera a carteira,
        # o progresso ou o limite diário já consumido por cada membro.
        admin_id = only_admin(request)
        payload = json_body(await request.json(), ('confirmation',))
        if payload['confirmation'] != 'LIMPAR FEED':
            raise HTTPException(422, detail='Digite LIMPAR FEED para confirmar')
        with writing() as db:
            removed = db.scalar(select(func.count()).select_from(FeedEvent)) or 0
            db.execute(delete(FeedReply))
            db.execute(delete(FeedLike))
            db.execute(delete(FeedEvent))
        logging.getLogger('recanto.admin').info(
            'Limpeza do Feed: admin=%s publicacoes_removidas=%s', admin_id, removed)
        return {'ok': True, 'removed': int(removed), 'scope': 'feed',
                'detail': 'Publicações e curtidas removidas. Histórico de recompensas preservado.'}

    @app.post('/api/feed/{event_id}/like')
    def like_feed(event_id:int,request:Request):
        uid=me(request)
        with writing() as db:
            entry=db.get(FeedEvent,event_id)
            if entry is None:raise HTTPException(404,detail='Publicação não encontrada')
            if entry.user_id == uid:raise HTTPException(403,detail='Você não pode curtir sua própria publicação')
            existing=db.get(FeedLike,(event_id,uid))
            if existing:
                return {'ok':True,'liked':True,'coins_gained':0,'reward_today':(db.get(FeedDailyReward,(uid,local_day())).count if db.get(FeedDailyReward,(uid,local_day())) else 0)}
            db.add(FeedLike(event_id=event_id,user_id=uid))
            day=local_day();state=db.get(FeedDailyReward,(uid,day))
            if state is None:
                state=FeedDailyReward(user_id=uid,day=day,count=0);db.add(state)
            gained=int(state.count<20)
            if gained:
                wallet(db,uid).coins+=1
                state.count+=1
            return {'ok':True,'liked':True,'coins_gained':gained,'reward_today':state.count,'coins_balance':wallet(db,uid).coins}

    def achievement_event(db, uid, event, amount=1):
        # Progresso vem de acoes internas e de eventos autenticados do bot.
        obj = db.get(AchievementProgress, (uid, event))
        if obj is None:
            obj = AchievementProgress(user_id=uid, event=event, counter=0)
            db.add(obj)
        obj.counter += amount
        db.flush()
        for award in db.scalars(select(Achievement).where(Achievement.active.is_(True), Achievement.event == event,
                                                              Achievement.target <= obj.counter)).all():
            if not db.get(UserAchievement, (uid, award.id)):
                db.add(UserAchievement(user_id=uid, achievement_id=award.id, unlocked_at=utcnow()))
                publish_feed(db,uid,'badge',badge={'name':award.title,'icon':award.icon,'image_url':award.image_url})
                xp_action(db,uid,'achievement','selo',once_key='badge:'+str(award.id))

    # RECANTO 0.2.22 — Eventos autenticados do bot. Nenhum POST do navegador
    # pode alterar contador de voz/mensagens. A autenticacao usa HTTPS + chave
    # compartilhada e os recibos no banco impedem creditos repetidos no retry.
    def check_discord_bridge(request: Request):
        expected = os.getenv('RECANTO_BOT_SECRET', '').strip()
        if len(expected) < 32:
            raise HTTPException(503, detail='Integração Discord não configurada no Render')
        provided = request.headers.get('authorization', '')
        if not provided.startswith('Bearer ') or not hmac.compare_digest(
                provided[7:].encode('utf-8'), expected.encode('utf-8')):
            raise HTTPException(401, detail='Chave do bot inválida')

    # RECANTO v0.2.23 — Compatibilidade com o bot Oracle original.
    # Esse bot (discord.Client + bot-queue.db) ja coleta mensagens e minutos
    # completos em voz, e envia eventos idempotentes no protocolo legado.
    # Nao ativar simultaneamente a extensao discord.py em outro processo.
    # v0.2.24: no aplicativo completo o backend principal pode registrar uma
    # rota antiga para este mesmo POST *antes* de chamar register_game().
    # FastAPI usa a primeira rota correspondente, deixando a implementacao
    # compatível da 0.2.23 inacessível mesmo após um deploy bem-sucedido.
    # Substituímos somente rotas POST exatas, preservando outros métodos e URLs.
    legacy_discord_path = '/api/integrations/discord/event'
    legacy_routes_removed = []
    for route in list(app.router.routes):
        if (getattr(route, 'path', None) == legacy_discord_path
                and 'POST' in (getattr(route, 'methods', None) or set())):
            app.router.routes.remove(route)
            legacy_routes_removed.append(getattr(getattr(route, 'endpoint', None), '__name__', '(desconhecido)'))
    if legacy_routes_removed:
        app.openapi_schema = None
        logging.getLogger('recanto.discord').warning(
            'Integração Discord 0.2.24: substituída(s) %s rota(s) POST legada(s): %s',
            len(legacy_routes_removed), ', '.join(legacy_routes_removed))

    @app.post('/api/integrations/discord/event')
    async def discord_oracle_legacy_event(request: Request):
        expected = os.getenv('RECANTO_BOT_SECRET', '').strip()
        if len(expected) < 32:
            raise HTTPException(503, detail='Integração Discord não configurada no Render')
        supplied = request.headers.get('x-recanto-bot-secret', '').strip()
        if not hmac.compare_digest(supplied.encode('utf-8'), expected.encode('utf-8')):
            raise HTTPException(401, detail='Chave do bot inválida')
        guild_id = os.getenv('DISCORD_GUILD_ID', '').strip()
        if not (guild_id.isascii() and guild_id.isdigit()):
            raise HTTPException(503, detail='DISCORD_GUILD_ID não configurado no Render')
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(422, detail='JSON inválido')
        uid = str(data.get('discord_id', '')).strip()
        raw_event_id = str(data.get('event_id', '')).strip()
        kind = str(data.get('event', '')).strip()
        amount = data.get('amount')
        if not (uid.isascii() and uid.isdigit() and 15 <= len(uid) <= 22):
            raise HTTPException(422, detail='ID do membro inválido')
        if not raw_event_id or len(raw_event_id) > 128 or any(ord(c) < 33 for c in raw_event_id):
            raise HTTPException(422, detail='Identificador do evento inválido')
        if kind not in ('voice_minutes', 'message_count'):
            raise HTTPException(422, detail='Tipo de evento inválido')
        if type(amount) is not int or (kind == 'voice_minutes' and not 1 <= amount <= 15) or (kind == 'message_count' and amount != 1):
            raise HTTPException(422, detail='Quantidade do evento inválida')
        # IDs do bot Oracle pertencem ao espaço de nomes do bot legado, que
        # nao se confunde com os IDs minuto/mensagem do bridge moderno.
        receipt_id = 'oracle:' + guild_id + ':' + hashlib.sha256(
            raw_event_id.encode('utf-8')).hexdigest()
        now = utcnow()
        with writing() as db:
            prior = db.get(DiscordActivityEvent, receipt_id)
            if prior:
                return {'ok': True, 'duplicate': True, 'counted': bool(prior.counted)}
            user = db.get(User, uid)
            counted = user is not None
            db.add(DiscordActivityEvent(event_id=receipt_id, guild_id=guild_id,
                user_id=uid, kind=kind, occurred_at=now,
                received_at=now, counted=counted))
            if counted:
                # O protocolo legado nao inclui o horario original do evento:
                # a missao diaria recebe credito na data do recebimento.
                progress(db, uid, kind, amount)
                achievement_event(db, uid, kind, amount)
                # O bot Oracle já descarta AFK e aplica cooldown nas mensagens.
                # O recibo único impede EXP repetida em tentativas de reenvio.
                xp_key = 'xp_discord_voice_minute' if kind == 'voice_minutes' else 'xp_discord_message'
                grant_experience(db,uid,setting(db,xp_key)*amount,'discord_'+kind)
            return {'ok': True, 'duplicate': False, 'counted': counted,
                    'registered': counted, 'credited': amount if counted else 0,
                    'reason': None if counted else 'membro ainda não entrou no Recanto'}

    @app.post('/api/integrations/discord/activity')
    async def discord_bridge_activity(request: Request):
        check_discord_bridge(request)
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(422, detail='JSON inválido')
        gid = str(data.get('guild_id', '')).strip()
        uid = str(data.get('discord_id', '')).strip()
        kind = str(data.get('kind', '')).strip()
        event_id = str(data.get('event_id', '')).strip()
        guild_expected = os.getenv('DISCORD_GUILD_ID', '').strip()
        if not guild_expected or gid != guild_expected:
            raise HTTPException(403, detail='Servidor Discord não autorizado')
        if not (uid.isascii() and uid.isdigit() and 15 <= len(uid) <= 22):
            raise HTTPException(422, detail='ID do membro inválido')
        if kind not in ('voice_minutes', 'message_count'):
            raise HTTPException(422, detail='Tipo de evento inválido')
        try:
            stamp = str(data.get('occurred_at', '')).replace('Z', '+00:00')
            moment = datetime.fromisoformat(stamp)
            if moment.tzinfo is None: raise ValueError('Time zone missing')
            moment = moment.astimezone(timezone.utc)
        except (ValueError, TypeError):
            raise HTTPException(422, detail='occurred_at deve ser ISO8601 com fuso UTC')
        age = (utcnow() - moment).total_seconds()
        if age < -300 or age > 86400:
            raise HTTPException(422, detail='Evento muito antigo ou no futuro (máximo 24h)')
        if kind == 'voice_minutes':
            wanted = f'voice:{gid}:{uid}:{int(moment.timestamp() // 60)}'
        else:
            mid = str(data.get('message_id', '')).strip()
            if not mid.isascii() or not mid.isdigit() or not 15 <= len(mid) <= 22:
                raise HTTPException(422, detail='ID da mensagem inválido')
            wanted = f'message:{gid}:{mid}'
        if event_id != wanted:
            raise HTTPException(422, detail='Identificador do evento inconsistente')
        with writing() as db:
            prior = db.get(DiscordActivityEvent, event_id)
            if prior:
                return {'ok': True, 'duplicate': True, 'counted': bool(prior.counted)}
            user = db.get(User, uid)
            counted = user is not None
            reason = None
            if counted and kind == 'message_count':
                last = db.get(DiscordMessageRate, uid)
                if last and (moment - naive_to_utc(last.last_counted_at)).total_seconds() < 10:
                    counted = False
                    reason = 'intervalo mínimo de 10 segundos entre mensagens'
                elif last:
                    last.last_counted_at = moment
                else:
                    db.add(DiscordMessageRate(user_id=uid, last_counted_at=moment))
            db.add(DiscordActivityEvent(event_id=event_id, guild_id=gid, user_id=uid,
                kind=kind, occurred_at=moment, received_at=utcnow(), counted=counted))
            # Retenção: a API rejeita eventos acima de 24h; recibos de mais de
            # 36h podem ser removidos sem permitir contagem duplicada.
            if kind == 'voice_minutes' and int(moment.timestamp() // 60) % 60 == 0:
                db.execute(delete(DiscordActivityEvent).where(
                    DiscordActivityEvent.received_at < utcnow() - timedelta(hours=36),
                    DiscordActivityEvent.event_id.notlike('oracle:%')))
            if counted:
                # Evento atrasado de ontem conta para o selo permanente, mas
                # nunca ganha crédito indevido na missão diária de hoje.
                if moment.astimezone(GAME_TZ).date().isoformat() == local_day():
                    progress(db, uid, kind, 1)
                achievement_event(db, uid, kind, 1)
                xp_key = 'xp_discord_voice_minute' if kind == 'voice_minutes' else 'xp_discord_message'
                grant_experience(db,uid,setting(db,xp_key),'discord_'+kind)
            elif user is None:
                reason = 'membro ainda não entrou no Recanto'
            return {'ok': True, 'duplicate': False, 'counted': bool(counted),
                    'registered': bool(user), 'reason': reason}

    @app.get('/api/admin/discord-activity/status')
    def discord_bridge_status(request: Request):
        only_admin(request)
        with SessionLocal() as db:
            last = db.scalar(select(func.max(DiscordActivityEvent.received_at)))
            cutoff = utcnow() - timedelta(hours=1)
            recent = db.execute(select(DiscordActivityEvent.kind,
                func.count(DiscordActivityEvent.event_id)).where(
                DiscordActivityEvent.received_at >= cutoff,
                DiscordActivityEvent.counted.is_(True)
            ).group_by(DiscordActivityEvent.kind)).all()
            totals = db.execute(select(DiscordActivityEvent.kind,
                DiscordActivityEvent.counted, func.count(DiscordActivityEvent.event_id)
            ).group_by(DiscordActivityEvent.kind, DiscordActivityEvent.counted)).all()
            route_owners = [getattr(getattr(route, 'endpoint', None), '__name__', '(sem nome)')
                for route in app.router.routes
                if getattr(route, 'path', None) == legacy_discord_path
                and 'POST' in (getattr(route, 'methods', None) or set())]
            return {'configured': len(os.getenv('RECANTO_BOT_SECRET', '').strip()) >= 32,
                    'guild_configured': bool(os.getenv('DISCORD_GUILD_ID', '').strip()),
                    'member_search_configured': bool(os.getenv('DISCORD_BOT_TOKEN', '').strip()),
                    'roster_snapshot_count': db.scalar(select(func.count(DiscordRosterMember.user_id)).where(DiscordRosterMember.guild_id==os.getenv('DISCORD_GUILD_ID','').strip())) or 0,
                    'last_event_at': naive_to_utc(last).isoformat() if last else None,
                    'counted_last_hour': dict(recent),
                    'bridge_version': '0.2.25',
                    'legacy_endpoint_handler': route_owners[0] if route_owners else None,
                    'legacy_endpoint_route_count': len(route_owners),
                    'legacy_routes_replaced_at_startup': len(legacy_routes_removed),
                    'received_total': sum(int(x[2]) for x in totals),
                    'counted_total': sum(int(x[2]) for x in totals if x[1]),
                    'uncounted_total': sum(int(x[2]) for x in totals if not x[1]),
                    'counted_by_type': {kind: sum(int(n) for k, counted, n in totals if k == kind and counted)
                                        for kind in ('voice_minutes', 'message_count')}}

    @app.get('/api/achievements')
    def achievements(request: Request):
        uid = me(request)
        with SessionLocal() as db:
            goals = db.scalars(select(Achievement).where(Achievement.active.is_(True)).order_by(Achievement.id)).all()
            progresses = {row.event: row.counter for row in db.scalars(
                select(AchievementProgress).where(AchievementProgress.user_id == uid)).all()}
            unlocks = {row.achievement_id: row.unlocked_at for row in db.scalars(
                select(UserAchievement).where(UserAchievement.user_id == uid)).all()}
            return {'unlocked': len(unlocks), 'total': len(goals), 'items': [
                {'id': g.id, 'title': g.title, 'description': g.description,
                 'icon': g.icon, 'image_url': g.image_url, 'event': g.event,
                 'target': g.target, 'progress': min(g.target, progresses.get(g.event, 0)),
                 'locked': g.id not in unlocks, 'available': g.event not in ('voice_minutes','message_count') or len(os.getenv('RECANTO_BOT_SECRET','')) >= 32,
                 'unlocked_at': unlocks[g.id].isoformat() if g.id in unlocks else None}
                for g in goals]}

    def stock(db):
        # Emissão global: 3 cópias por título Comum; 2 Raro; 1 Lendário/Prismático.
        rows = db.execute(select(Card.id, Card.name, Card.rarity, Card.image_url, Card.collection_name, Card.created_at).where(Card.active.is_(True))).all()
        counts = dict(db.execute(select(OwnedCard.card_id, func.count(OwnedCard.id)).group_by(OwnedCard.card_id)).all())
        reserved = dict(db.execute(select(ReservedCard.card_id, func.count(ReservedCard.id)).join(InventoryPack, InventoryPack.id == ReservedCard.pack_id).where(InventoryPack.opened_at.is_(None)).group_by(ReservedCard.card_id)).all())
        return [{'id': r[0], 'name': r[1], 'rarity': r[2], 'image_url': r[3],
                 'collection': r[4] or 'Recanto Original', 'created_at': naive_to_utc(r[5]).isoformat() if r[5] else None,
                 'max_copies': TIERS.get(r[2], 1), 'minted': counts.get(r[0], 0),
                 'reserved': reserved.get(r[0], 0),
                 'remaining': max(0, TIERS.get(r[2], 1) - counts.get(r[0], 0) - reserved.get(r[0], 0))} for r in rows]

    def random_card(pool, weight_key, overrides=None):
        eligible = [c for c in pool if c['remaining'] > 0]
        if not eligible:
            raise HTTPException(409, detail='Todos os cards se esgotaram; cadastre novos no painel de gestão.')
        tiers = sorted({x['rarity'] for x in eligible})
        weights = overrides if overrides is not None else WEIGHTS[weight_key]
        weighted = [max(0, weights.get(t, 0)) for t in tiers]
        if not sum(weighted):
            raise HTTPException(409, detail='Não há cards habilitados para sorteio')
        chosen_tier = RANDOM.choices(tiers, weights=weighted, k=1)[0]
        chosen = RANDOM.choice([c for c in eligible if c['rarity'] == chosen_tier])
        chosen['remaining'] -= 1
        chosen['minted'] += 1
        return chosen

    def grant_card(db, uid, chosen):
        own = OwnedCard(user_id=uid, card_id=chosen['id'], acquired_at=utcnow())
        db.add(own)
        db.flush()
        achievement_event(db, uid, 'card')
        xp_action(db,uid,'card_'+str(chosen['rarity']),'card_'+str(chosen['rarity']))
        return {'owned_id': own.id, 'card_id': chosen['id'], 'name': chosen['name'],
                'rarity': chosen['rarity'], 'image_url': chosen['image_url'], 'collection': chosen.get('collection','Recanto Original')}

    def pet_tick(db, obj, rules=None):
        if obj is None:
            return
        now = utcnow()
        if obj.status == 'missao': return
        if obj.status == 'ativo':
            then = naive_to_utc(obj.last_tick_at)
            hours = max(0, int((now - then).total_seconds() // 3600))
            if hours:
                obj.food = max(0, obj.food - hours * 4)
                obj.happiness = max(0, obj.happiness - hours * 3)
                # Saude piora se o Pet passa horas em fome extrema ou tristeza severa.
                if obj.food == 0 or obj.happiness == 0:
                    obj.health = max(0, (obj.health if obj.health is not None else 100) - hours * 2)
                obj.last_tick_at = then + timedelta(hours=hours)
            threshold = timedelta(hours=setting(db, 'neglect_hours'))
            last = naive_to_utc(obj.last_action_at)
            if now - last >= threshold:
                obj.status = 'vet'
                obj.vet_since = last + threshold
                obj.health = min(obj.health if obj.health is not None else 100, 35)
        if obj.status == 'vet':
            deadline = naive_to_utc(obj.vet_since) + timedelta(days=setting(db, 'vet_dead_days'))
            if now >= deadline:
                obj.status = 'morto'
                obj.death_at = deadline  # A espera começa na morte, não na próxima visita.
                obj.health = 0
        if obj.status == 'morto':
            obj.health = 0
            if obj.death_at is None:
                # Dados antigos sem data exata: usar o prazo do veterinário quando houver.
                obj.death_at = (naive_to_utc(obj.vet_since) + timedelta(days=setting(db, 'vet_dead_days'))) if obj.vet_since else now
            if not obj.death_penalty_applied:
                # Penalidade única e transacional; saldo negativo representa dívida a pagar
                # com as próximas moedas recebidas, sem perdoar parte dos 150.
                wallet(db, obj.user_id).coins -= setting(db, 'pet_death_penalty')
                obj.death_penalty_applied = True

    def pet_dict(db, obj):
        if obj is None:
            return None
        sp = db.get(PetSpecies, obj.species_id)
        nextfeed = (naive_to_utc(obj.last_feed_at) + timedelta(minutes=15)).isoformat() if obj.last_feed_at else None
        nextpet = (naive_to_utc(obj.last_pet_at) + timedelta(minutes=5)).isoformat() if obj.last_pet_at else None
        deadline = (naive_to_utc(obj.vet_since) + timedelta(days=setting(db, 'vet_dead_days'))).isoformat() if obj.vet_since and obj.status == 'vet' else None
        equipped = None
        if obj.equipped_collectible_id is not None:
            owned = db.get(InventoryCollectible, (obj.user_id, obj.equipped_collectible_id))
            item = db.get(Collectible, obj.equipped_collectible_id) if owned and owned.quantity > 0 else None
            if item:
                equipped = collectible_dict(item, owned.quantity, owned.acquired_at)
        allowed=(naive_to_utc(obj.death_at)+timedelta(hours=24)).isoformat() if obj.status=='morto' and obj.death_at else None
        swap_available=(naive_to_utc(obj.adopted_at)+timedelta(hours=48)).isoformat() if obj.status=='ativo' else None
        return {'species_id': sp.id, 'name': sp.name, 'emoji': sp.emoji, 'image_url': sp.image_url, **model_fields(sp),
                'nickname': obj.nickname or sp.name, 'equipped_collectible': equipped, 'status': obj.status, 'food': obj.food, 'happiness': obj.happiness,
                'health': max(0,min(100,int(obj.health if obj.health is not None else 100))),
                'luck': max(1,min(10,int(obj.luck if obj.luck is not None else 1))),
                'luck_bonus_pct': round(max(1,min(10,int(obj.luck if obj.luck is not None else 1)))*0.5,1),
                'change_available_at': swap_available,

                'rescue_cost': setting(db, 'vet_cost'), 'vet_deadline': deadline,
                'death_at': naive_to_utc(obj.death_at).isoformat() if obj.death_at else None,
                'adoption_available_at': allowed, 'death_penalty': setting(db,'pet_death_penalty'),
                'next_feed': nextfeed, 'next_pet': nextpet}

    def model_fields(s):
        return {key: getattr(s, key) for key in ('model_url', 'idle_animation', 'pet_animation', 'feed_animation', 'vet_animation')}

    def safe_artwork(value, allow_model=False):
        val = str(value or '').strip()
        if len(val) > 512 or (val and not (val.startswith('/uploads/') or (allow_model and val.startswith('/models/')) or val.startswith('https://'))):
            raise HTTPException(422, detail='Use HTTPS ou um arquivo carregado no painel')
        return val or None

    def coin_offer_details(db, offer):
        buyer=db.get(User, offer.buyer_id);seller=db.get(User, offer.seller_id)
        owned=db.get(OwnedCard,offer.owned_id);card=db.get(Card,owned.card_id) if owned else None
        return {'id':offer.id, 'buyer_name':buyer.username if buyer else 'Membro',
                'seller_name':seller.username if seller else 'Membro', 'amount':offer.amount,
                'card_name':card.name if card else 'Card indisponível', 'owned_id':offer.owned_id,
                'status':offer.status}

    def trade_details(db, t):
        a = db.get(User, t.sender_id)
        b = db.get(User, t.receiver_id)
        offer = db.get(OwnedCard, t.offered_id)
        want = db.get(OwnedCard, t.wanted_id)
        oc = db.get(Card, offer.card_id) if offer else None
        wc = db.get(Card, want.card_id) if want else None
        return {'id': t.id, 'from_name': a.username if a else 'Desconhecido',
                'to_name': b.username if b else 'Desconhecido',
                'from_me': None, 'offered': {'name': oc.name, 'rarity': oc.rarity, 'image_url': oc.image_url} if oc else None,
                'wanted': {'name': wc.name, 'rarity': wc.rarity, 'image_url': wc.image_url} if wc else None,
                'status': t.status, 'created_at': t.created_at.isoformat() if t.created_at else None,
                'offered_owned_id': t.offered_id, 'wanted_owned_id': t.wanted_id}

    def collectible_dict(obj, quantity=None, acquired_at=None):
        payload={'id':obj.id, 'name':obj.name, 'description':obj.description,
                 'image_url':obj.image_url, 'emoji':obj.emoji, 'rarity':obj.rarity or 'comum'}
        if quantity is not None:payload['quantity']=quantity
        if acquired_at is not None:payload['acquired_at']=naive_to_utc(acquired_at).isoformat()
        return payload

    def owned_collectibles(db, uid):
        rows=db.execute(select(InventoryCollectible,Collectible).join(Collectible,
            InventoryCollectible.collectible_id==Collectible.id).where(
            InventoryCollectible.user_id==uid,InventoryCollectible.quantity>0).order_by(
            Collectible.name)).all()
        return [collectible_dict(item,row.quantity,row.acquired_at) for row,item in rows]

    def expedition_codes(db, include_disabled=False):
        # Compatibilidade com as três expedições antigas; as personalizadas ficam no DB.
        keys=list(EXPEDITIONS)
        for row in db.scalars(select(ExpeditionConfig.code).order_by(ExpeditionConfig.code)):
            if row not in keys: keys.append(row)
        if include_disabled: return keys
        return [code for code in keys if expedition_settings(db,code)['enabled']]

    def expedition_settings(db, code):
        base=EXPEDITIONS.get(code,{})
        obj=db.get(ExpeditionConfig,code)
        if not base and not obj: raise HTTPException(404,detail='Expedição desconhecida')
        try:
            weights=json.loads(obj.rarity_weights) if obj and obj.rarity_weights else WEIGHTS['expedition']
            weights={tier:max(0,float(weights.get(tier,0))) for tier in TIERS}
        except (ValueError,TypeError,AttributeError):weights=WEIGHTS['expedition'].copy()
        def field(name, default):
            value=getattr(obj,name,None) if obj else None
            return default if value is None else value
        coins=(int(field('coin_min',(base.get('coins') or (10,20))[0])),
               int(field('coin_max',(base.get('coins') or (10,20))[1])))
        return {'id':code, 'name':field('name',base.get('name',code)),
            'minutes':int(field('minutes',base.get('minutes',60))),
            'food':int(field('food',base.get('food',12))),
            'happiness':int(field('happiness',base.get('happiness',6))),
            'health':int(field('health',base.get('health',0))),
            'coins':coins,'enabled':bool(field('enabled',True)),
            'image_url':obj.image_url if obj else None,
            'card_chance':obj.card_chance if obj else base.get('card_chance',0),
            'rarity_weights':weights,
            'featured_card_id':obj.featured_card_id if obj else None,
            'collectible_id':obj.collectible_id if obj else None,
            'collectible_chance':obj.collectible_chance if obj else 0}

    def lucky_expedition_weights(weights, luck):
        """Aumenta a chance de raridade acima de Comum em 0,5 pp por Sorte.

        Conserva a proporcao entre Raro, Lendario e Prismatico. Nao altera
        a chance de encontrar um Card nem cria cartas fora do estoque.
        """
        result={tier:max(0.0,float(weights.get(tier,0) or 0)) for tier in TIERS}
        total=sum(result.values())
        if total<=0:return result
        common=result['comum']
        rare_total=total-common
        if common<=0 or rare_total<=0:return result
        bonus=min(common, total*(max(1,min(10,int(luck)))*0.005))
        result['comum']-=bonus
        for tier in TIERS:
            if tier!='comum':result[tier]+=bonus*(result[tier]/rare_total)
        return result

    def weighted_expedition_card(pool, weights):
        eligible=[x for x in pool if x['remaining']>0]
        if not eligible:return None
        tiers=list({x['rarity'] for x in eligible})
        chances=[max(0,float(weights.get(t,0))) for t in tiers]
        if not sum(chances):return None
        tier=RANDOM.choices(tiers,weights=chances,k=1)[0]
        return RANDOM.choice([x for x in eligible if x['rarity']==tier])

    @app.get('/api/game/config')
    def game_config(request: Request):
        uid = me(request)
        with SessionLocal() as db:
            cfg = {x.key: x.value for x in db.scalars(select(GameSetting)).all()}
            return {'rules': cfg, 'chances': dict(WEIGHTS,diario=card_claim_weights(db)), 'max_copies': TIERS,
                    'reset_timezone': TIMEZONE_NAME, 'card_claim_minutes':event_effects(db)['card_cooldown'],
                    'claim_rates':card_claim_weights(db), 'admin': is_admin(uid, request),
                    'demo': False, 'local_development': os.getenv('APP_ENV','development').strip().lower()=='development'}

    @app.get('/api/daily/status')
    def daily_status(request: Request):
        uid = me(request)
        with SessionLocal() as db:
            at=next_card_available(db,uid)
            return {'card_claimed': bool(at and at>utcnow()),
                    'card_next_at':at.isoformat() if at else None,
                    'coins_claimed': claim_exists(db, uid, 'coins'),
                    'next_reset': reset_iso(), 'reward': setting(db, 'daily_coins'),
                    'card_rewards': {tier:card_bonus(db,tier) for tier in TIERS},
                    'card_claim_minutes':event_effects(db)['card_cooldown'],
                    'double_cards':event_effects(db)['double_cards'],
                    'claim_rates':card_claim_weights(db)}

    @app.post('/api/daily/coins')
    def daily_coins(request: Request):
        uid = me(request)
        with writing() as db:
            record_claim(db, uid, 'coins')
            gain = setting(db, 'daily_coins')
            balance=wallet(db, uid)
            balance.coins += gain
            progress(db, uid, 'daily_coins')
            balance_after=balance.coins
        return {'ok': True, 'coins_gained': gain, 'coins_balance': balance_after}

    @app.post('/api/daily/card')
    def daily_card(request: Request):
        uid = me(request)
        with writing() as db:
            # Evita consultar os mesmos eventos duas vezes nesta solicitação.
            effects=event_effects(db)
            cooldown=db.get(CardCooldown,uid)
            at=(naive_to_utc(cooldown.last_claimed)+timedelta(minutes=effects['card_cooldown'])) if cooldown else None
            if at and at>utcnow():
                raise HTTPException(409, detail=f'Aguarde {effects["card_cooldown"]} minutos entre resgates de cartas.')
            pool=stock(db)
            quantity=effects['double_cards']
            if sum(card['remaining'] for card in pool)<quantity:
                raise HTTPException(409,detail=f'Estoque insuficiente para resgatar {quantity} Cards neste evento.')
            obtained=[]
            reward=0
            weights=card_claim_weights(db)
            bonuses={}
            for _ in range(quantity):
                chosen=random_card(pool,'diario',weights)
                granted=grant_card(db,uid,chosen)
                rarity=granted['rarity']
                if rarity not in bonuses: bonuses[rarity]=card_bonus(db,rarity)
                granted['bonus_coins']=bonuses[rarity]
                reward+=granted['bonus_coins']
                obtained.append(granted)
                publish_feed(db,uid,'daily_card',card=feed_card(granted),defer_trim=True)
            trim_feed(db)
            balance=wallet(db, uid)
            balance.coins += reward
            now=utcnow()
            if cooldown: cooldown.last_claimed=now
            else: db.add(CardCooldown(user_id=uid,last_claimed=now))
            progress(db, uid, 'daily_card')
        return {'ok': True, 'card': obtained[0], 'cards':obtained,
                'coins_balance':balance.coins, 'bonus_coins':reward,
                'next_at':(now+timedelta(minutes=effects['card_cooldown'])).isoformat()}

    @app.get('/api/catalog')
    def catalog(request: Request):
        me(request)
        with SessionLocal() as db:
            pool = stock(db)
            owned = db.execute(select(OwnedCard.card_id, User.username, func.count(OwnedCard.id))
                               .join(User, OwnedCard.user_id == User.id)
                               .group_by(OwnedCard.card_id, User.id, User.username)).all()
            lookup = {}
            for cardid, name, n in owned:
                lookup.setdefault(cardid, []).append({'name': name, 'count': n})
            return {'items': [{**c, 'owners': lookup.get(c['id'], [])} for c in pool]}

    @app.get('/api/community')
    def community(request: Request):
        uid = me(request)
        with SessionLocal() as db:
            users = db.scalars(select(User).where(User.id != uid).order_by(User.username)).all()
            out = []
            for u in users:
                holdings = db.execute(select(OwnedCard.id, Card.name, Card.rarity, Card.image_url)
                          .join(Card, OwnedCard.card_id == Card.id)
                          .where(OwnedCard.user_id == u.id).order_by(Card.name)).all()
                out.append({'key': u.id, 'name': u.username, 'cards': [
                    {'owned_id': x[0], 'name': x[1], 'rarity': x[2], 'image_url': x[3]} for x in holdings],
                    'collectibles':owned_collectibles(db,u.id)})
            return {'members': out}

    @app.get('/api/trades')
    def trades(request: Request):
        uid = me(request)
        with SessionLocal() as db:
            listed = db.scalars(select(Trade).where((Trade.sender_id == uid) | (Trade.receiver_id == uid))
                                .order_by(Trade.id.desc()).limit(100)).all()
            return {'items': [{**trade_details(db, t), 'from_me': t.sender_id == uid,
                               'can_accept': t.receiver_id == uid and t.status == 'pendente',
                               'can_cancel': t.status == 'pendente' and t.sender_id == uid} for t in listed]}

    @app.post('/api/trades')
    async def make_trade(request: Request):
        uid = me(request)
        data = json_body(await request.json(), ('to_user', 'offered_owned_id', 'wanted_owned_id'))
        partner = str(data['to_user'])
        offered_id = integer(data['offered_owned_id'])
        wanted_id = integer(data['wanted_owned_id'])
        if partner == uid:
            raise HTTPException(422, detail='Não é possível trocar com você mesmo')
        with writing() as db:
            if db.get(User, partner) is None:
                raise HTTPException(404, detail='Membro não encontrado')
            a, b = db.get(OwnedCard, offered_id), db.get(OwnedCard, wanted_id)
            if a is None or b is None or a.user_id != uid or b.user_id != partner:
                raise HTTPException(409, detail='Uma das cartas não pertence mais ao dono informado')
            duplicate = db.scalar(select(Trade.id).where(Trade.sender_id == uid, Trade.receiver_id == partner,
                Trade.offered_id == offered_id, Trade.wanted_id == wanted_id, Trade.status == 'pendente'))
            if duplicate:
                raise HTTPException(409, detail='Esta proposta já está pendente')
            trade = Trade(sender_id=uid, receiver_id=partner, offered_id=offered_id,
                          wanted_id=wanted_id, status='pendente', created_at=utcnow())
            db.add(trade)
            db.flush()
            tid = trade.id
        return {'ok': True, 'trade_id': tid}

    @app.post('/api/trades/{trade_id}/decide')
    async def decide_trade(trade_id: int, request: Request):
        uid = me(request)
        data = json_body(await request.json(), ('action',))
        action = str(data['action'])
        if action not in ('accept', 'reject', 'cancel'):
            raise HTTPException(422, detail='Ação desconhecida')
        bonuses = {}
        with writing() as db:
            t = db.get(Trade, trade_id)
            if t is None or t.status != 'pendente':
                raise HTTPException(409, detail='Esta proposta não está mais pendente')
            if action == 'cancel':
                if t.sender_id != uid:
                    raise HTTPException(403, detail='Somente o remetente pode cancelar')
                t.status = 'cancelada'
            else:
                if t.receiver_id != uid:
                    raise HTTPException(403, detail='Somente o destinatário pode responder')
                if action == 'reject':
                    t.status = 'recusada'
                else:
                    offer, want = db.get(OwnedCard, t.offered_id), db.get(OwnedCard, t.wanted_id)
                    if not offer or not want or offer.user_id != t.sender_id or want.user_id != t.receiver_id:
                        t.status = 'expirada'
                        raise HTTPException(409, detail='Carta indisponível; a troca não pode ser concluída')
                    offer.user_id, want.user_id = t.receiver_id, t.sender_id
                    offer.acquired_at = want.acquired_at = utcnow()
                    t.status = 'aceita'
                    publish_feed(db,t.sender_id,'trade_cards',card_a=feed_card({'name':db.get(Card,offer.card_id).name,'rarity':db.get(Card,offer.card_id).rarity,'image_url':db.get(Card,offer.card_id).image_url}),card_b=feed_card({'name':db.get(Card,want.card_id).name,'rarity':db.get(Card,want.card_id).rarity,'image_url':db.get(Card,want.card_id).image_url}),other=db.get(User,t.receiver_id).username)
                    for user in (t.sender_id, t.receiver_id):
                        day = local_day()
                        reward_state = db.get(TradeReward, (user, day))
                        if reward_state is None:
                            reward_state = TradeReward(user_id=user, day=day, count=0)
                            db.add(reward_state)
                        bonus = setting(db, 'trade_bonus') if reward_state.count < setting(db, 'trade_reward_limit') else 0
                        if bonus:
                            wallet(db, user).coins += bonus
                            reward_state.count += 1
                        bonuses[user] = bonus
                        progress(db, user, 'trade')
                        achievement_event(db, user, 'trade')
                        xp_action(db,user,'trade_cards','troca_de_cards')
            t.resolved_at = utcnow()
        return {'ok': True, 'status': t.status, 'my_coin_bonus': bonuses.get(uid, 0)}

    @app.get('/api/coin-offers')
    def coin_offers(request: Request):
        uid=me(request)
        with SessionLocal() as db:
            rows=db.scalars(select(CoinOffer).where((CoinOffer.buyer_id==uid)|(CoinOffer.seller_id==uid)).order_by(CoinOffer.id.desc()).limit(100)).all()
            return {'min_by_tier':COIN_OFFER_MIN,'items':[{**coin_offer_details(db,x), 'from_me':x.buyer_id==uid,
                     'can_accept':x.seller_id==uid and x.status=='pendente',
                     'can_cancel':x.buyer_id==uid and x.status=='pendente'} for x in rows]}

    @app.post('/api/coin-offers')
    async def create_coin_offer(request: Request):
        uid=me(request)
        data=json_body(await request.json(),('to_user','wanted_owned_id','amount'))
        seller=str(data['to_user']);oid=integer(data['wanted_owned_id']);amount=integer(data['amount'])
        if seller==uid or amount>1000000:raise HTTPException(422,detail='Proposta inválida')
        with writing() as db:
            if not db.get(User,seller):raise HTTPException(404,detail='Membro não encontrado')
            own=db.get(OwnedCard,oid)
            if not own or own.user_id!=seller:raise HTTPException(409,detail='Card não está mais disponível')
            card=db.get(Card,own.card_id)
            if amount<COIN_OFFER_MIN[card.rarity]:raise HTTPException(422,detail=f'Oferta mínima: {COIN_OFFER_MIN[card.rarity]} moedas')
            if db.scalar(select(func.count(CoinOffer.id)).where(CoinOffer.owned_id==oid,CoinOffer.buyer_id==uid,CoinOffer.status=='pendente')):
                raise HTTPException(409,detail='Você já tem uma oferta pendente por esta cópia')
            # Escrow: o dinheiro sai imediatamente do comprador; cancelamento/recusa devolve.
            require_coins(db,uid,amount).coins-=amount
            offer=CoinOffer(buyer_id=uid,seller_id=seller,owned_id=oid,amount=amount,status='pendente',created_at=utcnow())
            db.add(offer);db.flush()
            return {'ok':True,'id':offer.id,'escrowed':amount}

    @app.post('/api/coin-offers/{offer_id}/decide')
    async def decide_coin_offer(offer_id:int,request:Request):
        uid=me(request);data=json_body(await request.json(),('action',))
        action=str(data['action'])
        if action not in ('accept','reject','cancel'):raise HTTPException(422,detail='Ação inválida')
        with writing() as db:
            offer=db.get(CoinOffer,offer_id)
            if not offer or offer.status!='pendente':raise HTTPException(409,detail='Oferta indisponível')
            if (action=='cancel' and offer.buyer_id!=uid) or (action!='cancel' and offer.seller_id!=uid):
                raise HTTPException(403,detail='Você não pode responder a esta oferta')
            owned=db.get(OwnedCard,offer.owned_id)
            if action=='accept' and owned and owned.user_id==offer.seller_id:
                owned.user_id=offer.buyer_id;owned.acquired_at=utcnow()
                wallet(db,offer.seller_id).coins+=offer.amount
                # Outras ofertas pendentes pela mesma cópia são reembolsadas imediatamente.
                other_offers=db.scalars(select(CoinOffer).where(CoinOffer.owned_id==offer.owned_id,
                                      CoinOffer.status=='pendente',CoinOffer.id!=offer.id)).all()
                for other in other_offers:
                    wallet(db,other.buyer_id).coins+=other.amount
                    other.status='expirada'
                fav=db.get(FavoriteCard,offer.seller_id)
                if fav and fav.owned_id==owned.id:db.delete(fav)
                offer.status='aceita'
                card_row=db.get(Card,owned.card_id)
                if card_row:publish_feed(db,offer.seller_id,'trade_coins',card=feed_card({'name':card_row.name,'rarity':card_row.rarity,'image_url':card_row.image_url}),coins=offer.amount,other=db.get(User,offer.buyer_id).username)
                for who in (offer.buyer_id,offer.seller_id):
                    progress(db,who,'trade');achievement_event(db,who,'trade')
                    xp_action(db,who,'trade_coins','troca_por_moedas')
                xp_spend(db,offer.buyer_id,offer.amount)
            else:
                wallet(db,offer.buyer_id).coins+=offer.amount
                offer.status='cancelada' if action=='cancel' else ('recusada' if action=='reject' else 'expirada')
            return {'ok':True,'status':offer.status}

    # 0.3.8 — trocas de colecionáveis de expedições (sem gerar itens).
    # A transação writing() serializa mudanças no banco também em multiusuário.
    def transferable_collectible(db, uid, collectible_id):
        if not collectible_id:return 0
        row=db.get(InventoryCollectible,(uid,collectible_id))
        if not row:return 0
        pet=db.get(UserPet,uid)
        # A última unidade equipada não pode sair do inventário do Pet.
        equipped=1 if pet and pet.equipped_collectible_id==collectible_id else 0
        return max(0,int(row.quantity)-equipped)

    def move_collectible(db, origin, destination, item_id):
        if transferable_collectible(db,origin,item_id)<1:
            raise HTTPException(409,detail='Colecionável indisponível ou única cópia equipada')
        former=db.get(InventoryCollectible,(origin,item_id))
        former.quantity-=1
        receiver=db.get(InventoryCollectible,(destination,item_id))
        if receiver:
            receiver.quantity+=1
            receiver.acquired_at=utcnow()
        else:
            db.add(InventoryCollectible(user_id=destination,collectible_id=item_id,quantity=1,acquired_at=utcnow()))

    def item_for_feed(db,item_id):
        item=db.get(Collectible,item_id)
        return collectible_dict(item) if item else {'name':'Colecionável indisponível','rarity':'comum'}

    def collectible_deal_dict(db,deal,uid):
        names={x.id:x.username for x in db.scalars(select(User).where(User.id.in_([deal.sender_id,deal.receiver_id]))).all()}
        return {'id':deal.id,'kind':deal.kind,'status':deal.status,'amount':deal.amount,
                'sender_name':names.get(deal.sender_id,'Membro'),
                'receiver_name':names.get(deal.receiver_id,'Membro'),
                'offered':item_for_feed(db,deal.offered_item_id) if deal.offered_item_id else None,
                'wanted':item_for_feed(db,deal.wanted_item_id) if deal.wanted_item_id else None,
                'from_me':deal.sender_id==uid,
                'can_accept':deal.status=='pendente' and deal.receiver_id==uid,
                'can_cancel':deal.status=='pendente' and deal.sender_id==uid}

    @app.get('/api/collectible-deals')
    def list_collectible_deals(request:Request):
        uid=me(request)
        with SessionLocal() as db:
            deals=db.scalars(select(CollectibleDeal).where(
                (CollectibleDeal.sender_id==uid)|(CollectibleDeal.receiver_id==uid))
                .order_by(CollectibleDeal.id.desc()).limit(100)).all()
            return {'items':[collectible_deal_dict(db,row,uid) for row in deals],
                    'minimums':COIN_OFFER_MIN}

    @app.post('/api/collectible-deals')
    async def create_collectible_deal(request:Request):
        uid=me(request)
        data=json_body(await request.json(),('to_user','kind'))
        recipient=str(data['to_user']).strip()
        kind=str(data['kind']).strip()
        if kind not in ('swap','buy','sell') or recipient==uid:
            raise HTTPException(422,detail='Tipo de negociação ou destinatário inválido')
        for field in (('offered_item_id',) if kind=='sell' else ('wanted_item_id',) if kind=='buy' else ('offered_item_id','wanted_item_id')):
            if field not in data:raise HTTPException(422,detail='Selecione o colecionável da proposta')
        if kind in ('buy','sell') and 'amount' not in data:
            raise HTTPException(422,detail='Informe a quantidade de moedas')
        offered=integer(data['offered_item_id']) if kind in ('swap','sell') else None
        wanted=integer(data['wanted_item_id']) if kind in ('swap','buy') else None
        amount=integer(data['amount']) if kind in ('buy','sell') else 0
        if (offered is not None and offered<1) or (wanted is not None and wanted<1) or (kind=='swap' and offered==wanted):
            raise HTTPException(422,detail='Selecione dois itens diferentes e válidos')
        with writing() as db:
            if not db.get(User,recipient):raise HTTPException(404,detail='Membro não encontrado')
            if offered and transferable_collectible(db,uid,offered)<1:
                raise HTTPException(409,detail='Você não possui uma cópia disponível deste item')
            if wanted and transferable_collectible(db,recipient,wanted)<1:
                raise HTTPException(409,detail='O destinatário não possui uma cópia disponível deste item')
            chosen=db.get(Collectible,offered if kind=='sell' else wanted)
            if not chosen:raise HTTPException(404,detail='Colecionável não encontrado')
            if kind in ('buy','sell') and not COIN_OFFER_MIN[chosen.rarity or 'comum']<=amount<=1000000:
                raise HTTPException(422,detail='Oferta de moedas fora do mínimo por raridade ou acima do limite')
            number=db.scalar(select(func.count(CollectibleDeal.id)).where(
                CollectibleDeal.sender_id==uid,CollectibleDeal.status=='pendente')) or 0
            if number>=25:raise HTTPException(429,detail='Limite de 25 propostas pendentes. Cancele propostas antigas.')
            if kind=='buy':require_coins(db,uid,amount).coins-=amount
            deal=CollectibleDeal(sender_id=uid,receiver_id=recipient,kind=kind,
                offered_item_id=offered,wanted_item_id=wanted,amount=amount,status='pendente',created_at=utcnow())
            db.add(deal);db.flush()
            return {'ok':True,'id':deal.id,'escrowed':amount if kind=='buy' else 0}

    @app.post('/api/collectible-deals/{deal_id}/decide')
    async def decide_collectible_deal(deal_id:int,request:Request):
        uid=me(request);data=json_body(await request.json(),('action',))
        action=str(data['action'])
        if action not in ('accept','reject','cancel'):raise HTTPException(422,detail='Ação inválida')
        with writing() as db:
            deal=db.get(CollectibleDeal,deal_id)
            if not deal or deal.status!='pendente':raise HTTPException(409,detail='Proposta não está pendente')
            if (action=='cancel' and deal.sender_id!=uid) or (action!='cancel' and deal.receiver_id!=uid):
                raise HTTPException(403,detail='Você não pode responder a esta proposta')
            if action=='accept':
                sender,receiver=deal.sender_id,deal.receiver_id
                if deal.kind=='swap':
                    if transferable_collectible(db,sender,deal.offered_item_id)<1 or transferable_collectible(db,receiver,deal.wanted_item_id)<1:
                        raise HTTPException(409,detail='Um dos itens não está mais disponível')
                    move_collectible(db,sender,receiver,deal.offered_item_id)
                    move_collectible(db,receiver,sender,deal.wanted_item_id)
                    feed={'kind':'trade_collectibles','item_a':item_for_feed(db,deal.offered_item_id),
                          'item_b':item_for_feed(db,deal.wanted_item_id)}
                else:
                    seller=receiver if deal.kind=='buy' else sender
                    buyer=sender if deal.kind=='buy' else receiver
                    target=deal.wanted_item_id if deal.kind=='buy' else deal.offered_item_id
                    if transferable_collectible(db,seller,target)<1:
                        raise HTTPException(409,detail='O item não está mais disponível')
                    if deal.kind=='sell':require_coins(db,buyer,deal.amount).coins-=deal.amount
                    move_collectible(db,seller,buyer,target)
                    wallet(db,seller).coins+=deal.amount
                    if deal.kind=='buy':xp_spend(db,buyer,deal.amount)
                    feed={'kind':'trade_collectible_coins','item':item_for_feed(db,target),'coins':deal.amount}
                deal.status='aceita'
                for member in (sender,receiver):
                    progress(db,member,'trade');achievement_event(db,member,'trade')
                    xp_action(db,member,'trade_cards' if deal.kind=='swap' else 'trade_coins',
                              'troca_de_colecionaveis')
                publish_feed(db,sender,feed.pop('kind'),other=db.get(User,receiver).username,**feed)
                # Uma cópia não pode ser vendida várias vezes; devolver moedas de propostas
                # concorrentes somente quando todas as cópias negociáveis se esgotarem.
                if deal.kind in ('buy','sell'):
                    target=deal.wanted_item_id if deal.kind=='buy' else deal.offered_item_id
                    seller=receiver if deal.kind=='buy' else sender
                    if transferable_collectible(db,seller,target)==0:
                        other=db.scalars(select(CollectibleDeal).where(
                            CollectibleDeal.status=='pendente',CollectibleDeal.id!=deal.id,
                            ((CollectibleDeal.kind=='buy') & (CollectibleDeal.receiver_id==seller) & (CollectibleDeal.wanted_item_id==target))|
                            ((CollectibleDeal.kind=='sell') & (CollectibleDeal.sender_id==seller) & (CollectibleDeal.offered_item_id==target)))).all()
                        for duplicate in other:
                            if duplicate.kind=='buy':wallet(db,duplicate.sender_id).coins+=duplicate.amount
                            duplicate.status='expirada';duplicate.resolved_at=utcnow()
            else:
                if deal.kind=='buy':wallet(db,deal.sender_id).coins+=deal.amount
                deal.status='cancelada' if action=='cancel' else 'recusada'
            deal.resolved_at=utcnow()
            return {'ok':True,'status':deal.status}

    @app.get('/api/card-economy')
    def card_economy(request:Request):
        me(request)
        return {'minimum_offers':COIN_OFFER_MIN,'duplicate_sale':DUPLICATE_SALE}

    @app.post('/api/cards/sell-duplicate')
    async def sell_duplicate(request:Request):
        uid=me(request);data=json_body(await request.json(),('owned_id',))
        oid=integer(data['owned_id'])
        with writing() as db:
            obj=db.get(OwnedCard,oid)
            if not obj or obj.user_id!=uid:raise HTTPException(403,detail='Cópia não pertence a você')
            qty=db.scalar(select(func.count(OwnedCard.id)).where(OwnedCard.user_id==uid,OwnedCard.card_id==obj.card_id)) or 0
            if qty<2:raise HTTPException(409,detail='Você precisa manter uma cópia desta carta')
            card=db.get(Card,obj.card_id)
            if db.scalar(select(func.count(Trade.id)).where(Trade.status=='pendente',((Trade.offered_id==oid)|(Trade.wanted_id==oid)))):
                raise HTTPException(409,detail='Cancele as trocas pendentes desta carta antes de vender')
            if db.scalar(select(func.count(CoinOffer.id)).where(CoinOffer.status=='pendente',CoinOffer.owned_id==oid)):
                raise HTTPException(409,detail='Existem ofertas pendentes por esta carta')
            fav=db.get(FavoriteCard,uid)
            if fav and fav.owned_id==oid:db.delete(fav)
            db.delete(obj)
            earned=DUPLICATE_SALE[card.rarity]
            wallet(db,uid).coins+=earned
            return {'ok':True,'coins_gained':earned}

    @app.get('/api/collections/card-styles')
    def collection_card_styles(request: Request):
        # Molduras prontas por coleção/raridade; o logo já faz parte da própria arte.
        me(request)
        with SessionLocal() as db:
            rows=db.scalars(select(CollectionCardStyle).order_by(CollectionCardStyle.collection_name)).all()
            return {'styles': {row.collection_name: {
                'frame_url': row.frame_url
            } for row in rows}}

    @app.post('/api/admin/collections/card-styles')
    async def save_collection_card_style(request: Request):
        only_admin(request)
        data=json_body(await request.json(), ('collection',))
        name=str(data['collection'] or '').strip()
        allowed_rarity_keys={'__rarity__comum','__rarity__raro','__rarity__lendário','__rarity__prismático'}
        if name not in allowed_rarity_keys and not 2<=len(name)<=100:
            raise HTTPException(422,detail='Informe uma coleção válida ou uma raridade padrão')
        if len(name)>100:
            raise HTTPException(422,detail='Nome da coleção muito longo')
        frame=safe_artwork(data.get('frame_url'))
        with writing() as db:
            current=db.get(CollectionCardStyle,name)
            if current is None:
                db.add(CollectionCardStyle(collection_name=name,frame_url=frame,emblem_url=None))
            else:
                current.frame_url=frame
                current.emblem_url=None
        return {'ok':True,'collection':name,'frame_url':frame}

    @app.get('/api/collections/featured')
    def featured_collection(request:Request):
        me(request)
        with SessionLocal() as db:
            obj=db.get(FeaturedCollection,1)
            options=sorted(set(DEFAULT_COLLECTIONS)|set(db.scalars(select(Card.collection_name).distinct()).all()))
            return {'name':obj.name if obj else 'Celebridades','image_url':obj.image_url if obj else None,'collections':options}

    @app.post('/api/admin/collections/featured')
    async def set_featured_collection(request:Request):
        only_admin(request);data=json_body(await request.json(),('name',))
        name=str(data['name']).strip()[:100]
        if not name:raise HTTPException(422,detail='Informe uma coleção')
        image=safe_artwork(data.get('image_url')) if data.get('image_url') else None
        with writing() as db:
            obj=db.get(FeaturedCollection,1)
            if not obj:db.add(FeaturedCollection(id=1,name=name,image_url=image))
            else:obj.name=name;obj.image_url=image
        return {'ok':True}

    @app.get('/api/ui/personalization')
    def public_ui_personalization():
        # Configurações são públicas para a tela de login também; só admins editam.
        with SessionLocal() as db:
            rows=db.scalars(select(UiPersonalization)).all()
            return {'texts':[{'source':row.source,'value':row.value}
                             for row in rows if row.kind=='text'],
                    'colors':[{'scope':row.scope,'token':row.key,'value':row.value}
                              for row in rows if row.kind=='color']}

    @app.post('/api/admin/ui/personalization')
    async def save_ui_personalization(request: Request):
        only_admin(request)
        data=await request.json()
        if not isinstance(data,dict):raise HTTPException(422,detail='Envie dados válidos')
        kind=data.get('kind')
        action=data.get('action','save')
        if kind not in ('text','color') or action not in ('save','delete','reset'):
            raise HTTPException(422,detail='Personalização inválida')
        scope='global' if kind=='text' else str(data.get('scope',''))
        if kind=='color' and scope not in ('light-mobile','light-desktop','dark-mobile','dark-desktop'):
            raise HTTPException(422,detail='Selecione tema e dispositivo')
        # Apagar tudo é sempre operação explícita, separada das demais mudanças.
        if action=='reset':
            with writing() as db:
                db.execute(delete(UiPersonalization).where(UiPersonalization.kind==kind))
            return {'ok':True,'action':'reset','kind':kind}
        if kind=='text':
            original=data.get('source','')
            if not isinstance(original,str) or not 1<=len(original.strip())<=280:
                raise HTTPException(422,detail='Informe o texto original (máximo 280 caracteres)')
            original=original.strip()
            key=hashlib.sha256(original.encode('utf-8')).hexdigest()
            replacement=data.get('value','')
            if action=='save' and (not isinstance(replacement,str) or len(replacement)>800):
                raise HTTPException(422,detail='Novo texto inválido (máximo 800 caracteres)')
        else:
            key=str(data.get('token',''))
            if not re.fullmatch(r'[a-f0-9]{10}',key):
                raise HTTPException(422,detail='Identificador de cor inválido')
            original=''
            replacement=str(data.get('value','')).strip()
            if action=='save' and not re.fullmatch(r'#[a-fA-F0-9]{6}(?:[a-fA-F0-9]{2})?',replacement):
                raise HTTPException(422,detail='Cor inválida. Use #RRGGBB ou #RRGGBBAA')
        with writing() as db:
            row=db.get(UiPersonalization,(kind,scope,key))
            if action=='delete':
                if row:db.delete(row)
            elif row:
                row.source=original;row.value=replacement
            else:
                db.add(UiPersonalization(kind=kind,scope=scope,key=key,source=original,value=replacement))
        return {'ok':True,'kind':kind,'scope':scope,'action':action}

    @app.get('/api/assets')
    def ui_assets(request: Request):
        # Imagens publicas para permitir logo/fundo personalizados antes do login.
        # Apenas admin pode modificar os dados.
        with SessionLocal() as db:
            return {'items': [{'key':a.key, 'selector':a.selector,
                               'mode':a.mode, 'image_url':a.image_url}
                              for a in db.scalars(select(UIAsset)).all()]}

    # 0.2.17 — cenários dos Pets guardados em UIAsset (sem migração de banco).
    # Não são seletores CSS; o frontend aplica por espécie ao próprio visualizador 3D.
    @app.get('/api/pets/backgrounds')
    def pet_backgrounds(request: Request):
        me(request)
        with SessionLocal() as db:
            records=db.scalars(select(UIAsset).where(UIAsset.key.like('petbg-%'))).all()
            global_url=''
            species={}
            for row in records:
                if row.key=='petbg-global':
                    global_url=row.image_url
                elif re.fullmatch(r'petbg-[1-9][0-9]*',row.key):
                    species[row.key[6:]]=row.image_url
            return {'global_url':global_url,'species':species}

    @app.post('/api/admin/pets/backgrounds')
    async def save_pet_background(request: Request):
        only_admin(request)
        payload=json_body(await request.json(),('species_id','image_url'))
        species_id=payload['species_id']
        if species_id is not None and (type(species_id) is not int or species_id < 1):
            raise HTTPException(422,detail='Selecione uma espécie válida')
        url=safe_artwork(payload['image_url'])
        key='petbg-global' if species_id is None else f'petbg-{species_id}'
        with writing() as db:
            if species_id is not None and db.get(PetSpecies,species_id) is None:
                raise HTTPException(404,detail='Espécie não encontrada')
            entry=db.get(UIAsset,key)
            if not url:
                if entry: db.delete(entry)
            elif entry:
                entry.image_url=url
            else:
                db.add(UIAsset(key=key,selector='',mode='background',image_url=url))
        return {'ok':True,'species_id':species_id,'image_url':url}

    @app.post('/api/admin/assets')
    async def update_ui_asset(request: Request):
        only_admin(request)
        data=json_body(await request.json(),('key','selector','mode','image_url'))
        key=str(data['key']).strip()
        selector=str(data['selector']).strip()
        mode=str(data['mode']).strip()
        if not re.fullmatch(r'(?:game:[a-z0-9_-]{1,40}|champion:[a-zA-Z0-9_-]{1,40}|[a-z0-9][a-z0-9_-]{0,62})',key):
            raise HTTPException(422,detail='Chave do asset invalida')
        if key.startswith('game:') and key[5:] not in {g[0] for g in GAMES}:
            raise HTTPException(422,detail='Jogo nao encontrado')
        if key.startswith('champion:') and key[9:] not in {champ[1] for champ in CHAMPIONS}:
            raise HTTPException(422,detail='Campeao nao encontrado')
        # Seletores sao apenas alvos visuais; rejeita caracteres CSS usados em
        # valores/scripts ou em combinacoes de pseudo-classes perigosas.
        if (len(selector)>180 or '\n' in selector or '\r' in selector or
            any(mark in selector for mark in ('{','}',';','\\','/*','*/'))):
            raise HTTPException(422,detail='Seletor CSS nao permitido')
        if mode not in ('image','icon','background'):
            raise HTTPException(422,detail='Modo desconhecido')
        if key.startswith(('game:', 'champion:')):
            selector=''
            mode='icon'
        elif key=='favicon':
            selector='link[rel="icon"]'
            mode='image'
        elif not selector:
            raise HTTPException(422,detail='Informe um seletor de elemento')
        url=safe_artwork(data['image_url'])
        with writing() as db:
            row=db.get(UIAsset,key)
            if not url:
                if row: db.delete(row)
            elif row:
                row.image_url=url
                row.selector=selector
                row.mode=mode
            else:
                db.add(UIAsset(key=key,selector=selector,mode=mode,image_url=url))
        return {'ok':True,'key':key,'image_url':url}

    @app.get('/api/games/preferences')
    def game_preferences(request:Request):
        uid=me(request)
        with SessionLocal() as db:return {'catalog':[game_entry(db,row) for row in GAMES], 'selected':user_games(db,uid),'max':6}

    @app.post('/api/games/preferences')
    async def save_game_preferences(request:Request):
        uid=me(request);data=json_body(await request.json(),('games',))
        chosen=data['games'];options={k for k,_,_ in GAMES}
        if not isinstance(chosen,list) or len(chosen)>6 or len(set(map(str,chosen)))!=len(chosen) or any(not isinstance(x,str) or x not in options for x in chosen):
            raise HTTPException(422,detail='Selecione até 6 jogos diferentes da lista')
        with writing() as db:
            previous=[x.game_id for x in db.scalars(select(FavoriteGame).where(FavoriteGame.user_id==uid).order_by(FavoriteGame.position))]
            if chosen and chosen!=previous:mission_action(db,uid,'favorite_game')
            db.execute(delete(FavoriteGame).where(FavoriteGame.user_id==uid))
            for order,game in enumerate(chosen):
                db.add(FavoriteGame(user_id=uid,game_id=game,position=order))
                xp_action(db,uid,'favorite_game','favorito_jogo',once_key='favgame:'+game)
        return {'ok':True}

    @app.get('/api/champions/preferences')
    def champion_preferences(request: Request):
        uid=me(request)
        with SessionLocal() as db:
            arts={art.key[9:]:art.image_url for art in db.scalars(select(UIAsset).where(UIAsset.key.like('champion:%')))}
            return {'catalog':[champion_entry(db,row,arts.get(row[1]) or '') for row in CHAMPIONS],
                    'selected':user_champions(db,uid), 'max':6}

    @app.post('/api/champions/preferences')
    async def save_champion_preferences(request: Request):
        uid=me(request)
        data=json_body(await request.json(),('champions',))
        chosen=data['champions']
        allowed={slug for _,slug in CHAMPIONS}
        if (not isinstance(chosen,list) or len(chosen)>6 or
            len(set(map(str,chosen)))!=len(chosen) or
            any(not isinstance(item,str) or item not in allowed for item in chosen)):
            raise HTTPException(422,detail='Selecione até 6 campeões diferentes da lista')
        with writing() as db:
            previous=[x.champion_id for x in db.scalars(select(FavoriteChampion).where(FavoriteChampion.user_id==uid).order_by(FavoriteChampion.position))]
            if chosen and chosen!=previous:mission_action(db,uid,'favorite_champion')
            db.execute(delete(FavoriteChampion).where(FavoriteChampion.user_id==uid))
            for order,champion_id in enumerate(chosen):
                db.add(FavoriteChampion(user_id=uid,champion_id=champion_id,position=order))
        return {'ok':True}

    @app.get('/api/shop')
    def shop(request: Request):
        me(request)
        with SessionLocal() as db:
            products = [
                {'sku': 'pack3', 'name': 'Pacote com 3 cards', 'price': event_price(db,setting(db, 'pack3_cost')), 'original_price':setting(db,'pack3_cost'), 'amount': 3,
                 'rates': WEIGHTS['pack3'], 'kind': 'cards'},
                {'sku': 'pack5', 'name': 'Pacote com 5 cards', 'price': event_price(db,setting(db, 'pack5_cost')), 'original_price':setting(db,'pack5_cost'), 'amount': 5,
                 'rates': WEIGHTS['pack5'], 'kind': 'cards'},
                {'sku': 'treat3', 'name': '3 Biscoitos', 'price': event_price(db,setting(db, 'treat_bundle_cost')), 'original_price':setting(db,'treat_bundle_cost'),
                 'amount': 3, 'kind': 'treats','food':15,'treat_sku':'biscoito'},
                {'sku': 'fruit', 'name': 'Frutinha', 'price':event_price(db,setting(db,'treat_fruit_cost')), 'original_price':setting(db,'treat_fruit_cost'), 'amount':1,'kind':'treats','food':30,'treat_sku':'fruta'},
                {'sku': 'feast', 'name':'Banquete', 'price':event_price(db,setting(db,'treat_feast_cost')), 'original_price':setting(db,'treat_feast_cost'), 'amount':1,'kind':'treats','food':55,'treat_sku':'banquete'},
                {'sku': 'vaccine', 'name':'Vacina para Pet', 'price':event_price(db,setting(db,'vaccine_cost')), 'original_price':setting(db,'vaccine_cost'), 'amount':1,'kind':'treats','food':0,'treat_sku':'vacina'},
            ]
            covers = {c.sku:c.image_url for c in db.scalars(select(ProductCover)).all()}
            controls = {c.sku:c for c in db.scalars(select(ShopItemControl)).all()}
            visible = []
            for item in products:
                control = controls.get(item['sku'])
                if control and not control.active: continue
                if control and control.name: item['name'] = control.name
                item['image_url'] = covers.get(item['sku'])
                item['emoji'] = SHOP_EMOJI[item['sku']]
                visible.append(item)
            return {'products': visible}

    @app.post('/api/shop/purchase')
    async def purchase(request: Request):
        uid = me(request)
        data = json_body(await request.json(), ('sku',))
        sku = str(data['sku'])
        if sku not in ('pack3', 'pack5', 'treat3', 'fruit', 'feast', 'vaccine'):
            raise HTTPException(422, detail='Produto desconhecido')
        with writing() as db:
            item_control = db.get(ShopItemControl, sku)
            if item_control and not item_control.active:
                raise HTTPException(409, detail='Este item foi removido da Loja')
            w = wallet(db, uid)
            if sku in ('treat3', 'fruit', 'feast', 'vaccine'):
                foodsku,qty,key = {'treat3':('biscoito',3,'treat_bundle_cost'),
                                   'fruit':('fruta',1,'treat_fruit_cost'),
                                   'feast':('banquete',1,'treat_feast_cost'),
                                   'vaccine':('vacina',1,'vaccine_cost')}[sku]
                cost = event_price(db,setting(db, key))
                require_coins(db, uid, cost)
                w.coins -= cost
                xp_spend(db,uid,cost)
                give_treat(db, uid, foodsku, qty)
                result = {'ok':True, 'treats_gained':qty, 'item':foodsku, 'spent':cost}
            else:
                qty = 3 if sku=='pack3' else 5
                cost = event_price(db,setting(db, sku+'_cost'))
                require_coins(db, uid, cost)
                pool = stock(db)
                if sum(x['remaining'] for x in pool) < qty:
                    raise HTTPException(409, detail='Estoque insuficiente para reservar este pacote')
                choices = [random_card(pool, sku) for _ in range(qty)]
                pack=InventoryPack(user_id=uid, sku=sku, created_at=utcnow())
                db.add(pack)
                db.flush()
                for position,chosen in enumerate(choices):
                    db.add(ReservedCard(pack_id=pack.id, card_id=chosen['id'], position=position))
                w.coins -= cost
                xp_spend(db,uid,cost)
                result={'ok':True,'pack_id':pack.id,'pack_amount':qty,'spent':cost}
        return result

    @app.get('/api/inventory')
    def inventory(request: Request):
        uid=me(request)
        with SessionLocal() as db:
            packs=db.scalars(select(InventoryPack).where(InventoryPack.user_id==uid, InventoryPack.opened_at.is_(None)).order_by(InventoryPack.id.desc())).all()
            covers={x.sku:x.image_url for x in db.scalars(select(ProductCover)).all()}
            treats=db.scalars(select(InventoryTreat).where(InventoryTreat.user_id==uid, InventoryTreat.quantity>0)).all()
            return {'packs':[{'id':p.id,'sku':p.sku,'amount':3 if p.sku=='pack3' else 5,'image_url':covers.get(p.sku),'created_at':p.created_at.isoformat()} for p in packs],
                    'treats':[{'sku':t.sku,'quantity':t.quantity,'image_url':covers.get('vaccine' if t.sku=='vacina' else {'biscoito':'treat3','fruta':'fruit','banquete':'feast'}.get(t.sku)),**TREAT_TYPES[t.sku]} for t in treats if t.sku in TREAT_TYPES],
                    'collectibles':owned_collectibles(db,uid)}

    @app.post('/api/inventory/packs/{pack_id}/open')
    def open_pack(pack_id: int, request: Request):
        uid=me(request)
        with writing() as db:
            pack=db.get(InventoryPack,pack_id)
            if not pack or pack.user_id!=uid: raise HTTPException(404, detail='Pacote não encontrado')
            if pack.opened_at is not None: raise HTTPException(409,detail='Pacote já aberto')
            reserved=db.scalars(select(ReservedCard).where(ReservedCard.pack_id==pack_id).order_by(ReservedCard.position)).all()
            quantity = 3 if pack.sku=='pack3' else 5
            positions = {r.position:r for r in reserved}
            missing = [position for position in range(quantity) if position not in positions]
            if missing:
                # A remoção administrativa de Cards pode invalidar reservas de
                # pacotes já comprados. Sorteamos substituições na abertura.
                pool = stock(db)
                if sum(card['remaining'] for card in pool) < len(missing):
                    raise HTTPException(409,detail='Catálogo sem estoque para completar seu pacote. O pacote foi preservado; tente após o administrador cadastrar novos Cards.')
                for position in missing:
                    chosen = random_card(pool, pack.sku)
                    db.add(ReservedCard(pack_id=pack.id, card_id=chosen['id'], position=position))
                db.flush()
                reserved=db.scalars(select(ReservedCard).where(ReservedCard.pack_id==pack_id).order_by(ReservedCard.position)).all()
            if len(reserved)!=quantity: raise HTTPException(409, detail='Pacote incompleto; contacte o administrador')
            result=[]
            bonus=0
            bonuses={}
            for r in reserved:
                card=db.get(Card,r.card_id)
                if not card: raise HTTPException(409, detail='Card indisponível')
                # Reutiliza o valor por raridade dentro da mesma transação.
                if card.rarity not in bonuses: bonuses[card.rarity]=card_bonus(db,card.rarity)
                reward=bonuses[card.rarity]
                granted=grant_card(db,uid,{'id':card.id,'name':card.name,'rarity':card.rarity,'image_url':card.image_url,'collection':card.collection_name})
                granted['bonus_coins']=reward
                result.append(granted)
                bonus+=reward
            pack.opened_at=utcnow()
            balance=wallet(db,uid)
            balance.coins+=bonus
            coins_balance=balance.coins
            progress(db,uid,'pack')
            for card in result:
                publish_feed(db,uid,'pack_card',card=feed_card(card),pack_size=quantity,defer_trim=True)
            trim_feed(db)
        return {'ok':True,'cards':result,'bonus_coins':bonus,'coins_balance':coins_balance}

    @app.get('/api/cards/favorite')
    def get_favorite(request: Request):
        uid=me(request)
        with SessionLocal() as db: return {'card':favorite_info(db,uid)}

    @app.post('/api/cards/favorite')
    async def set_favorite(request: Request):
        uid=me(request)
        body=json_body(await request.json(),('owned_id',))
        owned_id=integer(body['owned_id']) if body['owned_id'] is not None else None
        with writing() as db:
            if owned_id is not None:
                card=db.get(OwnedCard,owned_id)
                if not card or card.user_id!=uid: raise HTTPException(403,detail='Card não pertence à sua coleção')
            fav=db.get(FavoriteCard,uid)
            if owned_id is not None:
                xp_action(db,uid,'favorite_card','favorito_card',once_key='favcard:'+str(card.card_id))
            if owned_id is None:
                if fav: db.delete(fav)
            elif fav: fav.owned_id=owned_id
            else: db.add(FavoriteCard(user_id=uid,owned_id=owned_id))
        return {'ok':True,'owned_id':owned_id}

    # 0.2.21: listagem opcional de TODOS os membros do Discord, inclusive os que
    # ainda não abriram o Recanto. O token do bot nunca é enviado ao cliente.
    # Cache evita consultar a API do Discord a cada tecla digitada na busca.
    _guild_cache={'data':None, 'until':0.0}
    _guild_cache_lock=asyncio.Lock()

    async def discord_server_members():
        token=os.getenv('DISCORD_BOT_TOKEN','').strip()
        guild=os.getenv('DISCORD_GUILD_ID','958567158479208458').strip()
        if not token or not guild.isdecimal():
            return None
        now=time.monotonic()
        if _guild_cache['data'] is not None and now < _guild_cache['until']:
            return _guild_cache['data']
        async with _guild_cache_lock:
            now=time.monotonic()
            if _guild_cache['data'] is not None and now < _guild_cache['until']:
                return _guild_cache['data']
            members=[]
            after='0'
            try:
                # Endpoint oficial, com paginação de 1.000 registros.
                # Exige bot no servidor e Server Members Intent habilitado.
                async with httpx.AsyncClient(timeout=12.0) as client:
                    for _ in range(100):
                        response=await client.get(
                            f'https://discord.com/api/v10/guilds/{guild}/members',
                            headers={'Authorization':'Bot '+token},
                            params={'limit':1000,'after':after},
                        )
                        response.raise_for_status()
                        batch=response.json()
                        if not isinstance(batch,list):
                            raise ValueError('Resposta inesperada do Discord')
                        members.extend(batch)
                        if len(batch)<1000:
                            break
                        previous=after
                        after=max((str(m.get('user',{}).get('id','0')) for m in batch), key=lambda x:int(x))
                        if after==previous:
                            break
                # Cache válido por 10 min; permissões da API são verificadas
                # novamente quando o cache expirar.
                _guild_cache.update(data=members, until=time.monotonic()+600)
                return members
            except (httpx.HTTPError,ValueError,TypeError):
                logging.getLogger('recanto.discord').warning(
                    'Listagem de membros indisponível. Verifique bot, servidor e Server Members Intent.'
                )
                # Caso haja cache anterior, usa dados antigos por mais 60 s.
                if _guild_cache['data'] is not None:
                    _guild_cache['until']=time.monotonic()+60
                    return _guild_cache['data']
                return None

    def discord_member_brief(member, guild_id):
        user=member.get('user') or {}
        user_id=str(user.get('id') or '')
        if not user_id.isdecimal():return None
        display=(member.get('nick') or user.get('global_name') or user.get('username') or 'Membro').strip()
        username=str(user.get('username') or '')
        avatar_hash=member.get('avatar')
        if 'recanto_avatar_url' in member:
            return {'key':user_id,'name':display,'username':username,'avatar_url':member.get('recanto_avatar_url'),'bot':bool(user.get('bot'))}
        if avatar_hash:
            ext='gif' if avatar_hash.startswith('a_') else 'png'
            avatar=f'https://cdn.discordapp.com/guilds/{guild_id}/users/{user_id}/avatars/{avatar_hash}.{ext}?size=128'
        else:
            avatar_hash=user.get('avatar')
            ext='gif' if avatar_hash and avatar_hash.startswith('a_') else 'png'
            avatar=f'https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size=128' if avatar_hash else None
        return {'key':user_id,'name':display,'username':username,'avatar_url':avatar,'bot':bool(user.get('bot'))}

    async def discord_member_search(prefix, amount=40):
        token=os.getenv('DISCORD_BOT_TOKEN','').strip()
        guild=os.getenv('DISCORD_GUILD_ID','').strip()
        if not token or not guild.isdecimal() or not prefix:return None
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r=await client.get(f'https://discord.com/api/v10/guilds/{guild}/members/search',
                    headers={'Authorization':'Bot '+token},params={'query':prefix,'limit':min(100,max(amount,1))})
                r.raise_for_status()
                out=r.json()
                return out if isinstance(out,list) else None
        except (httpx.HTTPError,ValueError,TypeError):return None

    # 0.3.1: a Oracle já dispõe do token Discord; o diretório pode ser
    # sincronizado por um script local sem expor esse token ao Render.
    @app.post('/api/integrations/discord/roster')
    async def sync_discord_roster(request: Request):
        secret=os.getenv('RECANTO_BOT_SECRET','').strip()
        guild=os.getenv('DISCORD_GUILD_ID','').strip()
        if len(secret)<32 or not guild.isdecimal():
            raise HTTPException(503,detail='Integração Discord indisponível')
        supplied=request.headers.get('x-recanto-bot-secret','').strip()
        if not hmac.compare_digest(supplied.encode(),secret.encode()):
            raise HTTPException(401,detail='Chave do bot inválida')
        data=await request.json()
        if not isinstance(data,dict) or str(data.get('guild_id',''))!=guild:
            raise HTTPException(403,detail='Servidor Discord incorreto')
        sync_id=str(data.get('sync_id','')).strip()
        if not re.fullmatch(r'[a-f0-9]{32}',sync_id):
            raise HTTPException(422,detail='Identificador da sincronização inválido')
        batch=data.get('members')
        final=data.get('final')
        if not isinstance(batch,list) or len(batch)>250 or type(final) is not bool:
            raise HTTPException(422,detail='Lote inválido (até 250 membros)')
        validated=[]
        for item in batch:
            if not isinstance(item,dict):raise HTTPException(422,detail='Membro inválido')
            member_id=str(item.get('id','')).strip()
            if not member_id.isascii() or not member_id.isdigit() or not 15<=len(member_id)<=22:
                raise HTTPException(422,detail='ID do membro inválido')
            name=str(item.get('name') or 'Membro').strip()[:100]
            username=str(item.get('username') or '').strip()[:100]
            avatar=str(item.get('avatar_url') or '')[:350]
            if avatar and not (avatar.startswith('https://cdn.discordapp.com/') or avatar.startswith('https://media.discordapp.net/')):
                avatar=''
            validated.append((member_id,name or 'Membro',username,avatar or None,bool(item.get('bot',False))))
        with writing() as db:
            now=utcnow()
            for member_id,name,username,avatar,bot in validated:
                row=db.get(DiscordRosterMember,member_id)
                if not row:
                    db.add(DiscordRosterMember(user_id=member_id,guild_id=guild,
                        display_name=name,username=username,avatar_url=avatar,
                        bot=bot,sync_id=sync_id,synced_at=now))
                else:
                    row.guild_id=guild;row.display_name=name;row.username=username
                    row.avatar_url=avatar;row.bot=bot;row.sync_id=sync_id;row.synced_at=now
            db.flush()
            if final:
                # Só remove membros que saíram do servidor após receber TODOS os lotes.
                db.execute(delete(DiscordRosterMember).where(
                    DiscordRosterMember.guild_id==guild,DiscordRosterMember.sync_id!=sync_id))
            count=db.scalar(select(func.count(DiscordRosterMember.user_id)).where(
                DiscordRosterMember.guild_id==guild)) or 0
        return {'ok':True,'received':len(validated),'total_cached':count,'completed':final}

    @app.get('/api/community/profiles')
    async def community_profiles(request: Request, q: str='', offset: int=0, limit: int=8, registered_only: bool=False):
        uid=me(request)
        q=q.strip()[:80].casefold()
        offset=max(0,min(int(offset),100000))
        limit=max(1,min(int(limit),8))  # Nunca retornar listas enormes ao navegador.
        roster=None if registered_only else await discord_server_members()
        # Busca remota por prefixo mantém membros recém-chegados pesquisáveis.
        # Sem query, o navegador nunca recebe a lista completa de membros.
        extra=await discord_member_search(q,60) if q and not registered_only else None
        if roster is not None and extra:
            roster=roster+extra
        elif roster is None and extra:
            roster=extra
        with SessionLocal() as db:
            from_oracle=False
            if not roster and not registered_only:
                # Diretório persistente sincronizado pelo bot da Oracle.
                # Isso funciona mesmo sem DISCORD_BOT_TOKEN configurado no Render.
                guild=os.getenv('DISCORD_GUILD_ID','').strip()
                cached=db.scalars(select(DiscordRosterMember).where(
                    DiscordRosterMember.guild_id==guild,DiscordRosterMember.bot.is_(False))).all()
                if cached:
                    roster=[{'user':{'id':r.user_id,'username':r.username,'bot':r.bot},
                             'nick':r.display_name,'recanto_avatar_url':r.avatar_url}
                            for r in cached]
                    from_oracle=True
            if roster is None:
                # Fallback preserva o comportamento anterior quando o bot não
                # estiver configurado ou a API do Discord estiver indisponível.
                all_users=db.scalars(select(User).where(User.id!=uid).order_by(User.username)).all()
                found=[u for u in all_users if not q or q in u.username.casefold()]
                shown=found[offset:offset+limit]
                count_map=dict(db.execute(select(OwnedCard.user_id,func.count(OwnedCard.id))
                    .where(OwnedCard.user_id.in_([u.id for u in shown]))
                    .group_by(OwnedCard.user_id)).all()) if shown else {}
                return {'members':[{'key':u.id,'name':u.username,'avatar_url':u.avatar_url,
                    'card_count':count_map.get(u.id,0),'registered':True} for u in shown],
                    'total':len(found),'has_more':offset+limit<len(found),'discord_enabled':False,
                    'discord_reason':'registered_only' if registered_only else ('missing_bot_token' if not os.getenv('DISCORD_BOT_TOKEN','').strip() else 'discord_unavailable')}
            guild=os.getenv('DISCORD_GUILD_ID','958567158479208458').strip()
            normalized=[]
            seen=set()
            for m in roster:
                brief=discord_member_brief(m,guild)
                if not brief or brief['key']==uid or brief['key'] in seen or brief['bot']:continue
                seen.add(brief['key'])
                if q and q not in brief['name'].casefold() and q not in brief['username'].casefold():continue
                normalized.append(brief)
            normalized.sort(key=lambda v:(v['name'].casefold(),v['key']))
            shown=normalized[offset:offset+limit]
            ids=[m['key'] for m in shown]
            users={u.id:u for u in db.scalars(select(User).where(User.id.in_(ids))).all()} if ids else {}
            counts=dict(db.execute(select(OwnedCard.user_id,func.count(OwnedCard.id))
                .where(OwnedCard.user_id.in_(ids)).group_by(OwnedCard.user_id)).all()) if ids else {}
            for m in shown:
                u=users.get(m['key'])
                m['registered']=u is not None
                m['card_count']=counts.get(m['key'],0) if u else 0
                # Nome e avatar mais recentes do Discord têm prioridade;
                # perfil completo do Recanto só existe após o primeiro login.
            return {'members':shown,'total':len(normalized),
                'has_more':offset+limit<len(normalized),'discord_enabled':True,'discord_reason':'oracle_synced' if from_oracle else 'ok'}

    @app.get('/api/community/profiles/{member_id}')
    def public_profile(member_id: str, request: Request):
        visitor=me(request)
        with writing() as db:
            user=db.get(User,member_id)
            if not user or member_id.startswith('teste_'): raise HTTPException(404,detail='Membro não encontrado')
            if visitor!=member_id:mission_action(db,visitor,'profile_visit',member_id)
            obj=db.get(UserPet,member_id)
            pet_tick(db,obj)
            badges=db.execute(select(Achievement.title,Achievement.icon,Achievement.image_url).join(UserAchievement,UserAchievement.achievement_id==Achievement.id).where(UserAchievement.user_id==member_id)).all()
            # Coleção do membro visível somente após autenticação; cada exemplar
            # aparece uma vez, inclusive cópias repetidas. Não expomos owned_id
            # para impedir ações de favoritar/vender no visualizador público.
            holdings=db.execute(
                select(Card.id,Card.name,Card.rarity,Card.image_url,Card.collection_name)
                .select_from(OwnedCard)
                .join(Card,Card.id==OwnedCard.card_id)
                .where(OwnedCard.user_id==member_id)
                .order_by(OwnedCard.acquired_at.desc(),OwnedCard.id.desc())
            ).all()
            public_cards=[{'card_id':row[0], 'name':row[1], 'rarity':row[2],
                           'image_url':row[3], 'collection':row[4] or 'Recanto Original'}
                          for row in holdings]
            # Totais públicos necessários para que o resumo do perfil visitado
            # tenha a mesma composição de Moedas / Cards / Petiscos do perfil próprio.
            # Não expor histórico da carteira, IDs de itens ou dados de transações.
            public_wallet=db.get(Wallet,member_id)
            public_coins=max(0,int(public_wallet.coins or 0)) if public_wallet else 0
            public_treats=max(0,int(public_wallet.treats or 0)) if public_wallet else 0
            return {'key':user.id,'name':user.username,'avatar_url':user.avatar_url,
                    'coins':public_coins,'treats':public_treats,
                    'cards':len(public_cards),'collection_cards':public_cards,
                    'badges':[{'title':x[0],'icon':x[1],'image_url':x[2]} for x in badges],
                    'favorite':favorite_info(db,member_id),
                    'pet':pet_dict(db,obj), 'favorite_games':user_games(db,member_id),
                    'favorite_champions':user_champions(db,member_id),
                    'collectibles':owned_collectibles(db,member_id),
                    'level_info':level_info(db,member_id)}

    @app.post('/api/pets/visit/{owner_id}')
    async def visit_pet(owner_id: str,request: Request):
        visitor=me(request)
        payload=json_body(await request.json(),('action',))
        action=str(payload['action'])
        sku=str(payload.get('treat_sku','biscoito'))
        if action not in ('pet','feed'): raise HTTPException(422,detail='Interação inválida')
        if owner_id==visitor: raise HTTPException(422,detail='Use sua própria aba Pets')
        with writing() as db:
            if not db.get(User,owner_id): raise HTTPException(404,detail='Membro não encontrado')
            obj=db.get(UserPet,owner_id)
            pet_tick(db,obj)
            if obj is None or obj.status!='ativo': raise HTTPException(409,detail='Este Pet não está disponível')
            key=(visitor,owner_id,local_day(),action)
            if db.get(VisitorCare,key): raise HTTPException(409,detail='Você já realizou essa interação hoje com este Pet')
            if action=='feed':
                consume_treat(db,visitor,sku)
                obj.food=min(100,obj.food+TREAT_TYPES[sku]['food'])
                obj.health=min(100,(obj.health if obj.health is not None else 100)+3)
            else:
                obj.happiness=min(100,obj.happiness+15)
                obj.health=min(100,(obj.health if obj.health is not None else 100)+1)
            obj.last_action_at=utcnow()
            db.add(VisitorCare(visitor_id=visitor,owner_id=owner_id,day=local_day(),action=action))
            species=db.get(PetSpecies,obj.species_id)
            owner=db.get(User,owner_id)
            publish_feed(db,visitor,'visitor_pet_care',action=action,owner=owner.username if owner else 'um membro',
                         pet={'name':obj.nickname or (species.name if species else 'Pet'),
                              'image_url':species.image_url if species else None,
                              'emoji':species.emoji if species else '🐾'})
            gain=setting(db,'visit_pet_reward' if action=='pet' else 'visit_feed_reward')
            owner_gain=setting(db,'visit_owner_reward')
            wallet(db,visitor).coins+=gain
            wallet(db,owner_id).coins+=owner_gain
            progress(db,visitor,'pet' if action=='pet' else 'feed')
            xp_action(db,visitor,'pet_visit' if action=='pet' else 'feed_visit','visita_pet')
            achievement_event(db,visitor,'pet' if action=='pet' else 'feed')
            result=pet_dict(db,obj)
            visitor_balance=wallet(db,visitor).coins
            visitor_treats=wallet(db,visitor).treats
            remaining=treat_qty(db,visitor,sku) if action=='feed' else None
        return {'ok':True,'visitor_coins':gain,'owner_coins':owner_gain,'pet':result,
                'visitor_balance':visitor_balance,'visitor_treats':visitor_treats,'treat_quantity':remaining}

    @app.post('/api/inventory/gift')
    async def gift_treat(request: Request):
        uid=me(request)
        data=json_body(await request.json(),('to_user','sku','quantity'))
        to_user=str(data['to_user']);sku=str(data['sku']);qty=integer(data['quantity'])
        if sku not in TREAT_TYPES or qty<1 or qty>100: raise HTTPException(422,detail='Petisco ou quantidade inválida')
        if to_user==uid: raise HTTPException(422,detail='Você não pode presentear a si mesmo')
        with writing() as db:
            recipient=db.get(User,to_user)
            if not recipient: raise HTTPException(404,detail='Destinatário não encontrado')
            give_treat(db,uid,sku,-qty)
            give_treat(db,to_user,sku,qty)
            publish_feed(db,uid,'gift_pet_item',to_user=recipient.username,item=feed_pet_item(db,sku),quantity=qty)
        return {'ok':True,'quantity':qty,'sku':sku}

    @app.get('/api/pets')
    def pets(request: Request):
        uid = me(request)
        with writing() as db:
            obj = db.get(UserPet, uid)
            pet_tick(db, obj)
            types = db.scalars(select(PetSpecies).where(PetSpecies.active.is_(True)).order_by(PetSpecies.id)).all()
            return {'pet': pet_dict(db, obj), 'species': [
                {'id': s.id, 'name': s.name, 'emoji': s.emoji, 'image_url': s.image_url, **model_fields(s)} for s in types],
                    'treats': wallet(db, uid).treats,
                    'coins_balance': wallet(db, uid).coins,
                    'expedition':({'mission':mission.mission,'name':mission.display_name or expedition_settings(db,mission.mission)['name'],
                       'ends_at':naive_to_utc(mission.ends_at).isoformat(),'ready':utcnow()>=naive_to_utc(mission.ends_at)}
                       if (mission:=db.get(PetExpedition,uid)) else None),
                    'expedition_options':[dict(expedition_settings(db,k),effective_minutes=max(1,
                        (expedition_settings(db,k)['minutes']*(100-event_effects(db)['expedition_speed'])+99)//100))
                        for k in expedition_codes(db)]}

    @app.post('/api/pets/expedition/start')
    async def start_expedition(request:Request):
        uid=me(request);data=json_body(await request.json(),('mission',));key=str(data['mission'])
        with writing() as db:
            info=expedition_settings(db,key)
            if not info['enabled']:raise HTTPException(409,detail='Expedição indisponível')
            obj=db.get(UserPet,uid)
            if not obj:raise HTTPException(409,detail='Adote um Pet antes')
            pet_tick(db,obj)
            if obj.status!='ativo':raise HTTPException(409,detail='Seu Pet está indisponível')
            if db.get(PetExpedition,uid):raise HTTPException(409,detail='Já existe uma expedição pendente')
            if obj.food<info['food']+15:raise HTTPException(409,detail='Seu Pet precisa de mais fome para partir e voltar em segurança')
            if obj.happiness<info['happiness']+10:raise HTTPException(409,detail='Seu Pet precisa de mais felicidade para partir')
            if (obj.health if obj.health is not None else 100)<info['health']+10:
                raise HTTPException(409,detail='Seu Pet precisa de mais saúde para partir')
            now=utcnow();obj.status='missao';obj.last_tick_at=now;obj.last_action_at=now
            coins=RANDOM.randint(*info['coins'])
            card_award=RANDOM.randrange(10000)<int(info['card_chance'])*100
            collect_id=info['collectible_id'] if RANDOM.randrange(10000)<int(info['collectible_chance'])*100 else None
            species=db.get(PetSpecies,obj.species_id)
            publish_feed(db,uid,'expedition_start',pet={'name':obj.nickname or species.name,'image_url':species.image_url,'emoji':species.emoji})
            db.add(PetExpedition(user_id=uid,mission=key,started_at=now,
                ends_at=now+timedelta(minutes=max(1,(info['minutes']*(100-event_effects(db)['expedition_speed'])+99)//100)),coins=coins,
                card_award=card_award,reward_card_id=info['featured_card_id'] if card_award else None,
                reward_collectible_id=collect_id,reward_rarities=json.dumps(lucky_expedition_weights(info['rarity_weights'],obj.luck or 1)),
                cost_food=info['food'],cost_happiness=info['happiness'],cost_health=info['health'],display_name=info['name']))
            progress(db,uid,'expedition_start')
        return {'ok':True,'ends_at':(now+timedelta(minutes=max(1,(info['minutes']*(100-event_effects(db)['expedition_speed'])+99)//100))).isoformat()}

    @app.post('/api/pets/expedition/collect')
    def collect_expedition(request:Request):
        uid=me(request)
        with writing() as db:
            row=db.get(PetExpedition,uid);obj=db.get(UserPet,uid)
            if not row or not obj or obj.status!='missao':raise HTTPException(409,detail='Nenhuma expedição em andamento')
            if utcnow()<naive_to_utc(row.ends_at):raise HTTPException(409,detail='Seu Pet ainda está em expedição')
            info=expedition_settings(db,row.mission)
            obj.food=max(0,obj.food-(row.cost_food if row.cost_food is not None else info['food']))
            obj.happiness=max(0,obj.happiness-(row.cost_happiness if row.cost_happiness is not None else info['happiness']))
            obj.health=max(0,(obj.health if obj.health is not None else 100)-
                            (row.cost_health if row.cost_health is not None else info['health']))
            obj.status='ativo';obj.last_tick_at=utcnow();obj.last_action_at=utcnow()
            earned=row.coins;wallet(db,uid).coins+=earned
            granted=None;converted_coins=0;new_collectible=None
            if row.card_award:
                pool=stock(db)
                chosen=None
                if row.reward_card_id:
                    chosen=next((c for c in pool if c['id']==row.reward_card_id),None)
                    ref=db.get(Card,row.reward_card_id)
                    if ref and db.scalar(select(OwnedCard.id).where(OwnedCard.user_id==uid,OwnedCard.card_id==ref.id).limit(1)):
                        converted_coins=COIN_OFFER_MIN.get(ref.rarity,COIN_OFFER_MIN['comum'])
                        wallet(db,uid).coins+=converted_coins
                        chosen=None
                    elif chosen is None or chosen['remaining']<=0:
                        chosen=None
                else:
                    try:weights=json.loads(row.reward_rarities) if row.reward_rarities else WEIGHTS['expedition']
                    except (ValueError,TypeError):weights=WEIGHTS['expedition']
                    chosen=weighted_expedition_card(pool,weights)
                if chosen and chosen['remaining']>0 and converted_coins==0:
                    granted=grant_card(db,uid,chosen)
                    wallet(db,uid).coins+=card_bonus(db,granted['rarity'])
                    species=db.get(PetSpecies,obj.species_id)
                    publish_feed(db,uid,'expedition_card',pet={'name':obj.nickname or species.name,
                        'image_url':species.image_url,'emoji':species.emoji},card=feed_card(granted))
            if row.reward_collectible_id:
                item=db.get(Collectible,row.reward_collectible_id)
                if item:
                    owned=db.get(InventoryCollectible,(uid,item.id))
                    if owned:owned.quantity+=1
                    else:db.add(InventoryCollectible(user_id=uid,collectible_id=item.id,quantity=1))
                    new_collectible=collectible_dict(item)
                    progress(db,uid,'collectible_gain')
            db.delete(row)
        return {'ok':True,'coins_gained':earned,'card':granted,'converted_coins':converted_coins,
                'collectible':new_collectible}

    @app.post('/api/pets/adopt')
    async def adopt(request: Request):
        uid = me(request)
        data = json_body(await request.json(), ('species_id',))
        sid = integer(data['species_id'])
        nickname=str(data.get('nickname') or '').strip()
        if not 2<=len(nickname)<=40 or any(ord(ch)<32 for ch in nickname):
            raise HTTPException(422,detail='Escolha um nome para o Pet, entre 2 e 40 caracteres')
        with writing() as db:
            specie = db.get(PetSpecies, sid)
            if not specie or not specie.active:
                raise HTTPException(404, detail='Pet indisponível para adoção')
            pet = db.get(UserPet, uid)
            if pet:
                pet_tick(db, pet)
                if pet.status != 'morto':
                    raise HTTPException(409, detail='Cada jogador pode ter apenas um Pet')
                death_at=naive_to_utc(pet.death_at) if pet.death_at else utcnow()
                if utcnow() < death_at + timedelta(hours=24):
                    until=(death_at+timedelta(hours=24)).isoformat()
                    raise HTTPException(409, detail='Após o falecimento, espere 24 horas para adotar outro Pet. Disponível em: '+until)
                db.delete(pet)
                db.flush()
            db.add(UserPet(user_id=uid, species_id=sid, nickname=nickname, status='ativo',
                           food=85, happiness=85, health=100, luck=RANDOM.randint(1,10), adopted_at=utcnow(),
                           last_action_at=utcnow(), last_tick_at=utcnow()))
            publish_feed(db,uid,'adopt_pet',pet={'name':nickname or specie.name,'image_url':specie.image_url,'emoji':specie.emoji})
            progress(db, uid, 'adopt')
            achievement_event(db, uid, 'adopt')
        return {'ok': True, 'message': f'{nickname} foi adotado!'}

    @app.post('/api/pets/change')
    async def change_poro(request: Request):
        uid=me(request)
        data=json_body(await request.json(),('species_id','nickname'))
        sid=integer(data['species_id'])
        nickname=str(data['nickname'] or '').strip()
        if not 2<=len(nickname)<=40 or any(ord(ch)<32 or ord(ch)==127 for ch in nickname):
            raise HTTPException(422,detail='Nome do novo Pet: entre 2 e 40 caracteres')
        with writing() as db:
            obj=db.get(UserPet,uid)
            if obj is None:raise HTTPException(409,detail='Você ainda não tem um Pet')
            pet_tick(db,obj)
            if obj.status!='ativo':
                raise HTTPException(409,detail='Só é possível trocar um Pet em casa, fora de expedições e do veterinário')
            if db.get(PetExpedition,uid):
                raise HTTPException(409,detail='Conclua a expedição antes de trocar de Pet')
            specie=db.get(PetSpecies,sid)
            if not specie or not specie.active:raise HTTPException(404,detail='Pet indisponível para adoção')
            now=utcnow()
            ready_at=naive_to_utc(obj.adopted_at)+timedelta(hours=48)
            if now<ready_at:
                raise HTTPException(409,detail='A troca de Pet fica disponível 48 horas após a última adoção ou troca. Disponível em: '+ready_at.isoformat())
            obj.species_id=sid;obj.nickname=nickname;obj.status='ativo'
            obj.food=85;obj.happiness=85;obj.health=100;obj.luck=RANDOM.randint(1,10);obj.adopted_at=now
            obj.last_tick_at=now;obj.last_action_at=now
            obj.last_pet_at=None;obj.last_feed_at=None;obj.vet_since=None
            obj.death_at=None;obj.death_penalty_applied=False
            obj.equipped_collectible_id=None  # O colecionável permanece no inventário.
            updated=pet_dict(db,obj)
        return {'ok':True,'pet':updated}

    @app.post('/api/pets/rename')
    async def rename_poro(request: Request):
        uid=me(request)
        data=json_body(await request.json(), ('nickname',))
        nickname=str(data['nickname'] or '').strip()
        if not 2 <= len(nickname) <= 40 or any(ord(ch) < 32 or ord(ch) == 127 for ch in nickname):
            raise HTTPException(422, detail='Nome do Pet deve ter de 2 a 40 caracteres, sem caracteres de controle')
        with writing() as db:
            pet=db.get(UserPet,uid)
            if pet is None or pet.status=='morto':
                raise HTTPException(409, detail='Adote um Pet antes de mudar o nome')
            pet.nickname=nickname
        return {'ok':True,'nickname':nickname}

    @app.post('/api/pets/equip-collectible')
    async def equip_poro_collectible(request: Request):
        uid=me(request)
        data=json_body(await request.json(), ('collectible_id',))
        raw_id=data['collectible_id']
        item_id=None if raw_id is None else integer(raw_id)
        if item_id is not None and item_id <= 0:
            raise HTTPException(422, detail='Colecionável inválido')
        with writing() as db:
            pet=db.get(UserPet,uid)
            if pet is None or pet.status=='morto':
                raise HTTPException(409, detail='Você precisa de um Pet para equipar itens')
            item=None
            if item_id is not None:
                owned=db.get(InventoryCollectible,(uid,item_id))
                item=db.get(Collectible,item_id)
                if not owned or owned.quantity < 1 or not item:
                    raise HTTPException(403, detail='Este colecionável não pertence ao seu inventário')
            pet.equipped_collectible_id=item_id
        return {'ok':True,'collectible_id':item_id,'equipped':item_id is not None}

    @app.post('/api/pets/care')
    async def care(request: Request):
        uid = me(request)
        data = json_body(await request.json(), ('action',))
        action = str(data['action'])
        if action not in ('feed', 'pet'):
            raise HTTPException(422, detail='Cuidado desconhecido')
        with writing() as db:
            obj = db.get(UserPet, uid)
            if not obj:
                raise HTTPException(409, detail='Adote um Pet primeiro')
            pet_tick(db, obj)
            if obj.status != 'ativo':
                raise HTTPException(409, detail='Seu Pet não está disponível para cuidados')
            now = utcnow()
            if action == 'feed':
                if obj.last_feed_at and now < naive_to_utc(obj.last_feed_at) + timedelta(minutes=15):
                    raise HTTPException(409, detail='Aguarde 15 minutos antes de alimentar novamente')
                sku = str(data.get('treat_sku', 'biscoito'))
                if sku == 'vacina':
                    raise HTTPException(422, detail='Vacinas só podem ser usadas no veterinário')
                consume_treat(db, uid, sku)
                obj.food = min(100, obj.food + TREAT_TYPES[sku]['food'])
                obj.health = min(100,(obj.health if obj.health is not None else 100)+3)
                obj.last_feed_at = now
            else:
                if obj.last_pet_at and now < naive_to_utc(obj.last_pet_at) + timedelta(minutes=5):
                    raise HTTPException(409, detail='Aguarde 5 minutos antes de acariciar novamente')
                obj.happiness = min(100, obj.happiness + 25)
                obj.health = min(100,(obj.health if obj.health is not None else 100)+1)
                obj.last_pet_at = now
            obj.last_action_at = now
            progress(db, uid, action)
            xp_action(db,uid,'pet_self' if action=='pet' else 'feed_self','cuidado_pet')
            achievement_event(db, uid, action)
            result = pet_dict(db, obj)
            remaining_treats = wallet(db, uid).treats
            selected_quantity = treat_qty(db, uid, sku) if action == 'feed' else None
        return {'ok': True, 'pet': result, 'treats': remaining_treats, 'treat_quantity': selected_quantity}

    @app.post('/api/pets/vaccinate')
    def vaccinate_poro(request:Request):
        uid=me(request)
        with writing() as db:
            obj=db.get(UserPet,uid)
            if not obj:raise HTTPException(404,detail='Pet não encontrado')
            pet_tick(db,obj)
            if obj.status!='vet':raise HTTPException(409,detail='Vacina disponível quando o Pet está no veterinário')
            consume_treat(db,uid,'vacina')
            obj.status='ativo';obj.vet_since=None
            obj.food=max(obj.food,75);obj.happiness=max(obj.happiness,75);obj.health=max(obj.health or 0,70)
            obj.last_action_at=obj.last_tick_at=utcnow()
        return {'ok':True}

    @app.post('/api/pets/rescue')
    def rescue(request: Request):
        uid = me(request)
        with writing() as db:
            obj = db.get(UserPet, uid)
            if not obj:
                raise HTTPException(409, detail='Nenhum Pet encontrado')
            pet_tick(db, obj)
            if obj.status != 'vet':
                raise HTTPException(409, detail='Este Pet não está aguardando resgate no veterinário')
            price = setting(db, 'vet_cost')
            require_coins(db, uid, price).coins -= price
            xp_spend(db,uid,price)
            obj.status = 'ativo'
            obj.vet_since = None
            obj.food = 70
            obj.happiness = 65
            obj.health = max(obj.health or 0,70)
            obj.last_action_at = obj.last_tick_at = utcnow()
        return {'ok': True, 'spent': price}

    @app.get('/api/missions')
    def missions(request: Request):
        uid = me(request)
        with SessionLocal() as db:
            rows = {m.mission: m for m in db.scalars(select(MissionProgress).where(
                 MissionProgress.user_id == uid, MissionProgress.day == local_day())).all()}
            covers = {c.code:c.image_url for c in db.scalars(select(MissionCover)).all()}
            return {'next_reset': reset_iso(), 'items': [
                {'code': code, 'title': title, 'goal': goal, 'reward': reward,
                 'image_url': covers.get(code), 'emoji': MISSION_EMOJI.get(code, '🎯'),
                 'progress': min(goal, rows[code].progress) if code in rows else 0,
                 'claimed': rows[code].claimed if code in rows else False}
                for code, title, goal, reward in MISSIONS]}

    @app.post('/api/missions/{code}/claim')
    def mission_claim(code: str, request: Request):
        uid = me(request)
        definitions = {x[0]: x for x in MISSIONS}
        if code not in definitions:
            raise HTTPException(404, detail='Missão inexistente')
        with writing() as db:
            record = db.get(MissionProgress, (uid, local_day(), code))
            if not record or record.progress < definitions[code][2]:
                raise HTTPException(409, detail='A missão ainda não foi concluída')
            if record.claimed:
                raise HTTPException(409, detail='Recompensa já resgatada')
            record.claimed = True
            balance=wallet(db, uid)
            balance.coins += definitions[code][3]
            achievement_event(db, uid, 'mission')
            mission_claim_experience(db,uid)
            balance_after=balance.coins
        return {'ok': True, 'coins_gained': definitions[code][3], 'coins_balance': balance_after}

    @app.get('/api/admin/authorized-ids')
    def admin_ids(request: Request):
        only_admin(request)
        fixed=sorted({x.strip() for x in os.getenv('RECANTO_ADMIN_DISCORD_IDS','249610270069096448').split(',') if x.strip().isdecimal()})
        with SessionLocal() as db:
            extra=sorted(x.discord_id for x in db.scalars(select(AdminPermission)).all())
        return {'permanent':fixed,'additional':[x for x in extra if x not in fixed]}

    @app.post('/api/admin/authorized-ids')
    async def admin_change_id(request: Request):
        only_admin(request)
        data=json_body(await request.json(),('discord_id','action'))
        discord_id=str(data['discord_id']).strip()
        action=str(data['action'])
        if not discord_id.isdecimal() or not 15<=len(discord_id)<=22:
            raise HTTPException(422,detail='Informe um ID de usuário Discord válido')
        if action not in ('add','remove'):
            raise HTTPException(422, detail='Ação inválida')
        fixed={x.strip() for x in os.getenv('RECANTO_ADMIN_DISCORD_IDS','249610270069096448').split(',')}
        if action=='remove' and discord_id in fixed:
            raise HTTPException(409,detail='Este administrador é permanente e deve ser alterado no arquivo .env')
        with writing() as db:
            row=db.get(AdminPermission,discord_id)
            if action=='add' and not row: db.add(AdminPermission(discord_id=discord_id))
            if action=='remove' and row: db.delete(row)
        return {'ok':True,'discord_id':discord_id,'action':action}

    @app.get('/api/events')
    def community_events(request:Request):
        me(request)
        with SessionLocal() as db:
            now=utcnow()
            return {'active':[event_dict(row,now) for row in active_events(db,now)],
                    'effects':event_effects(db,now),'server_time':now.isoformat()}

    @app.get('/api/admin/events')
    def admin_events(request:Request):
        only_admin(request)
        with SessionLocal() as db:
            return {'items':[event_dict(row) for row in db.scalars(select(RecantoEvent).order_by(RecantoEvent.id.desc())).all()],
                    'kinds':{key:{'label':label,'min':minimum,'max':maximum}
                             for key,(label,minimum,maximum) in EVENT_KINDS.items()},
                    'timezone':TIMEZONE_NAME}

    def parse_event_date(value):
        if value in (None,''):return None
        if not isinstance(value,str):raise HTTPException(422,detail='Data/hora inválida')
        try:
            stamp=datetime.fromisoformat(value)
            if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=GAME_TZ)
            return stamp.astimezone(timezone.utc)
        except (ValueError,OverflowError):raise HTTPException(422,detail='Data/hora inválida')

    @app.post('/api/admin/events')
    async def save_event(request:Request):
        only_admin(request)
        payload=json_body(await request.json(),('name','description','kind','value','mode','enabled'))
        name=str(payload['name']).strip();description=str(payload['description']).strip()
        kind=str(payload['kind']);mode=str(payload['mode']);value=integer(payload['value'])
        enabled=payload['enabled'];emoji=str(payload.get('emoji') or '✨').strip()[:24]
        if not 2<=len(name)<=100 or len(description)>240 or kind not in EVENT_KINDS or mode not in ('manual','scheduled') or type(enabled) is not bool:
            raise HTTPException(422,detail='Informe nome, descrição, efeito e modo válidos')
        low,high=EVENT_KINDS[kind][1:]
        if not low<=value<=high:raise HTTPException(422,detail=f'Valor de evento entre {low} e {high}')
        starts=parse_event_date(payload.get('starts_at'));ends=parse_event_date(payload.get('ends_at'))
        if mode=='scheduled' and (not starts or not ends):
            raise HTTPException(422,detail='Eventos programados precisam de início e término')
        if starts and ends and ends<=starts:raise HTTPException(422,detail='O término precisa ser posterior ao início')
        if starts and ends and ends-starts>timedelta(days=366):
            raise HTTPException(422,detail='Duração máxima de um evento: 366 dias')
        candidate=payload.get('id')
        if candidate is not None and (type(candidate) is not int or candidate<1):
            raise HTTPException(422,detail='ID de evento inválido')
        with writing() as db:
            row=db.get(RecantoEvent,candidate) if candidate else None
            if candidate and row is None:raise HTTPException(404,detail='Evento não encontrado')
            if row is None:row=RecantoEvent();db.add(row)
            row.name=name;row.description=description;row.emoji=emoji or '✨'
            row.kind=kind;row.value=value;row.mode=mode;row.enabled=enabled
            row.starts_at=starts;row.ends_at=ends
            db.flush();event_id=row.id
        return {'ok':True,'id':event_id}

    @app.post('/api/admin/events/delete')
    async def delete_event(request:Request):
        only_admin(request)
        data=json_body(await request.json(),('id',))
        ident=integer(data['id'])
        with writing() as db:
            row=db.get(RecantoEvent,ident)
            if not row:raise HTTPException(404,detail='Evento não encontrado')
            db.delete(row)
        return {'ok':True}

    @app.get('/api/admin/settings')
    def admin_settings(request: Request):
        only_admin(request)
        with SessionLocal() as db:
            return {'settings': {x.key: x.value for x in db.scalars(select(GameSetting)).all()}}

    @app.post('/api/admin/settings')
    async def admin_update_settings(request: Request):
        only_admin(request)
        data = await request.json()
        json_body(data, ('key', 'value'))
        key = str(data['key'])
        value = integer(data['value'])
        # As recompensas por raridade são independentes dos demais limites de
        # economia. Zero desativa a recompensa e valores altos são aceitos.
        if key not in DEFAULTS:
            raise HTTPException(422, detail='Configuração inválida')
        ceiling=1000000 if key.startswith('card_bonus_') else 100000
        if not 0 <= value <= ceiling:
            raise HTTPException(422, detail=f'Informe um valor inteiro entre 0 e {ceiling:,}'.replace(',', '.'))
        if key=='card_claim_minutes' and not 15<=value<=10080:
            raise HTTPException(422,detail='Intervalo de resgate entre 15 e 10.080 minutos')
        if key.startswith('card_chance_'):
            raise HTTPException(422,detail='Edite as quatro raridades juntas para totalizar 100%')
        if key in ('neglect_hours', 'vet_dead_days') and value < 1:
            raise HTTPException(422, detail='O prazo deve ser no mínimo 1')
        with writing() as db:
            db.get(GameSetting, key).value = value
        return {'ok': True, 'key': key, 'value': value}

    @app.post('/api/admin/cards/claim-settings')
    async def save_claim_settings(request: Request):
        only_admin(request)
        data=json_body(await request.json(),('minutes','chances'))
        minutes=integer(data['minutes']);chances=data['chances']
        if not 15<=minutes<=10080 or not isinstance(chances,dict) or set(chances)!=set(TIERS):
            raise HTTPException(422,detail='Defina intervalo válido e quatro raridades')
        if any(type(chances[t]) is not int or not 0<=chances[t]<=100 for t in TIERS) or sum(chances.values())!=100:
            raise HTTPException(422,detail='As chances precisam somar exatamente 100%')
        with writing() as db:
            db.get(GameSetting,'card_claim_minutes').value=minutes
            for tier in TIERS:db.get(GameSetting,'card_chance_'+tier).value=chances[tier]
        return {'ok':True,'minutes':minutes,'chances':chances}

    @app.post('/api/admin/cards')
    async def admin_add_card(request: Request):
        only_admin(request)
        data = json_body(await request.json(), ('name', 'rarity'))
        name = str(data['name']).strip()
        rarity = str(data['rarity']).lower().strip()
        picture = str(data.get('image_url', '')).strip() or None
        collection = str(data.get('collection') or 'Recanto Original').strip()
        if not 2 <= len(collection) <= 100:
            raise HTTPException(422, detail='Coleção deve ter entre 2 e 100 caracteres')
        if not 2 <= len(name) <= 120 or rarity not in TIERS:
            raise HTTPException(422, detail='Informe nome (2–120 caracteres) e raridade válida')
        if picture and not (picture.startswith('/uploads/') or picture.startswith('https://')):
            raise HTTPException(422, detail='Imagem deve usar HTTPS ou arquivo enviado')
        with writing() as db:
            # Menor ID positivo ainda disponível, inclusive lacunas deixadas por
            # exclusões anteriores. A transação escrita serializa dois admins.
            candidate = 1
            for existing_id in db.scalars(select(Card.id).where(Card.id > 0).order_by(Card.id)).all():
                if existing_id > candidate:
                    break
                candidate = existing_id + 1
            card = Card(id=candidate, name=name, rarity=rarity,
                        image_url=safe_artwork(picture), collection_name=collection)
            db.add(card)
            db.flush()
            cid = card.id
        return {'ok': True, 'id': cid}

    @app.post('/api/admin/cards/collection')
    async def admin_update_card_collection(request: Request):
        only_admin(request)
        data = json_body(await request.json(), ('card_id', 'collection'))
        card_id = integer(data['card_id'])
        collection = str(data['collection']).strip()
        if not 2 <= len(collection) <= 100:
            raise HTTPException(422, detail='Coleção deve ter entre 2 e 100 caracteres')
        with writing() as db:
            card = db.get(Card, card_id)
            if not card:
                raise HTTPException(404, detail='Card não encontrado')
            card.collection_name = collection
        return {'ok': True, 'card_id': card_id, 'collection': collection}

    @app.post('/api/admin/pets')
    async def admin_add_pet(request: Request):
        only_admin(request)
        data = json_body(await request.json(), ('name',))
        name = str(data['name']).strip()
        emo = str(data.get('emoji', '🐾'))[:30]
        picture = str(data.get('image_url', '')).strip() or None
        if not 2 <= len(name) <= 100:
            raise HTTPException(422, detail='Nome inválido')
        if picture and not (picture.startswith('/uploads/') or picture.startswith('https://')):
            raise HTTPException(422, detail='Imagem deve usar HTTPS ou arquivo enviado')
        model = safe_artwork(data.get('model_url'), allow_model=True)
        if model and not model.lower().split('?')[0].endswith(('.glb', '.gltf')):
            raise HTTPException(422, detail='Modelo deve ser .glb ou .gltf')
        animations = {}
        for key in ('idle_animation', 'pet_animation', 'feed_animation', 'vet_animation'):
            value = str(data.get(key) or '').strip()
            if len(value) > 80:
                raise HTTPException(422, detail='Nome da animação é muito longo')
            animations[key] = value or None
        with writing() as db:
            if db.scalar(select(PetSpecies.id).where(PetSpecies.name == name)):
                raise HTTPException(409, detail='Este Pet já existe')
            obj = PetSpecies(name=name, emoji=emo or '🐾', image_url=picture,
                             model_url=model, **animations)
            db.add(obj)
            db.flush()
            sid = obj.id
        return {'ok': True, 'id': sid}

    # 0.3.2 — Extensão autônoma de missões para novas ações do Recanto.
    # Não intercepta as rotas atuais de Missões do backend/main.py.
    @app.get('/api/recanto-extra-missions')
    def extra_missions(request:Request):
        uid=me(request)
        with SessionLocal() as db:
            missions=db.scalars(select(RecantoMissionExtra).where(
                RecantoMissionExtra.enabled.is_(True)).order_by(RecantoMissionExtra.code)).all()
            items=[]
            for mission in missions:
                period=extra_period(mission.kind)
                row=db.get(RecantoMissionExtraProgress,(uid,mission.code,period))
                items.append({'code':mission.code,'title':mission.title,'goal':mission.goal,
                    'kind':mission.kind,'event':mission.event,'reward':mission.reward,
                    'emoji':mission.emoji,'image_url':mission.image_url,
                    'progress':min(mission.goal,row.amount) if row else 0,
                    'claimed':row.claimed if row else False,'source':'extra'})
            return {'items':items}

    @app.post('/api/recanto-extra-missions/{code}/claim')
    def claim_extra_mission(code:str,request:Request):
        uid=me(request)
        with writing() as db:
            mission=db.get(RecantoMissionExtra,code)
            if not mission or not mission.enabled:raise HTTPException(404,detail='Missão indisponível')
            row=db.get(RecantoMissionExtraProgress,(uid,code,extra_period(mission.kind)))
            if not row or row.amount<mission.goal:raise HTTPException(409,detail='Missão ainda não concluída')
            if row.claimed:raise HTTPException(409,detail='Recompensa já resgatada')
            row.claimed=True
            coins=wallet(db,uid);coins.coins+=mission.reward
            achievement_event(db,uid,'mission')
            mission_claim_experience(db,uid)
            return {'ok':True,'coins_gained':mission.reward,'coins_balance':coins.coins}

    @app.get('/api/admin/recanto-extra-missions')
    def admin_extra_missions(request:Request):
        only_admin(request)
        with SessionLocal() as db:
            rows=db.scalars(select(RecantoMissionExtra).order_by(RecantoMissionExtra.code)).all()
            return {'events':EXTRA_EVENTS,'items':[
                {'code':m.code,'title':m.title,'kind':m.kind,'event':m.event,
                 'goal':m.goal,'reward':m.reward,'emoji':m.emoji,
                 'image_url':m.image_url,'enabled':m.enabled,'source':'extra'} for m in rows]}

    @app.post('/api/admin/recanto-extra-missions')
    async def admin_save_extra_mission(request:Request):
        only_admin(request)
        data=json_body(await request.json(),('code','title','kind','event','goal','reward'))
        code=str(data['code']).strip().lower()
        title=str(data['title']).strip();kind=str(data['kind']);event=str(data['event'])
        goal=integer(data['goal']);reward=integer(data['reward'])
        enabled=data.get('enabled',True)
        emoji=str(data.get('emoji') or '🎯')[:30]
        if (not re.fullmatch(r'[a-z][a-z0-9_-]{2,39}',code) or code in {m[0] for m in MISSIONS}
            or not 2<=len(title)<=120 or kind not in ('unica','diaria','semanal')
            or event not in EXTRA_EVENTS or not 1<=goal<=100000 or not 0<=reward<=100000
            or type(enabled) is not bool):
            raise HTTPException(422,detail='Código, título, tipo, evento ou metas inválidos')
        image=safe_artwork(data.get('image_url'))
        with writing() as db:
            row=db.get(RecantoMissionExtra,code)
            if row:
                # Não alterar evento/tipo/meta de uma missão com progresso já existente.
                has_progress=db.scalar(select(RecantoMissionExtraProgress.user_id).where(
                    RecantoMissionExtraProgress.code==code).limit(1)) is not None
                if has_progress and (row.kind!=kind or row.event!=event or row.goal!=goal):
                    raise HTTPException(409,detail='Missão já iniciada: mantenha evento, tipo e meta. Para alterar, crie outra missão.')
                row.title=title;row.kind=kind;row.event=event;row.goal=goal;row.reward=reward
                row.emoji=emoji;row.image_url=image;row.enabled=enabled
            else:
                db.add(RecantoMissionExtra(code=code,title=title,kind=kind,event=event,
                    goal=goal,reward=reward,emoji=emoji,image_url=image,enabled=enabled))
        return {'ok':True,'code':code}

    @app.post('/api/admin/recanto-extra-missions/{code}/visibility')
    async def extra_mission_visibility(code:str,request:Request):
        only_admin(request)
        data=json_body(await request.json(),('enabled',))
        if type(data['enabled']) is not bool:raise HTTPException(422,detail='Situação inválida')
        with writing() as db:
            row=db.get(RecantoMissionExtra,code)
            if not row:raise HTTPException(404,detail='Missão não encontrada')
            row.enabled=data['enabled']
        return {'ok':True,'code':code,'enabled':data['enabled']}

    # 0.1.21 — expedicoes e colecionaveis, gerenciados apenas por administradores.
    @app.get('/api/admin/expeditions')
    def admin_expeditions(request: Request):
        only_admin(request)
        with SessionLocal() as db:
            return {
                'items':[expedition_settings(db,key) for key in expedition_codes(db,True)],
                'cards':[{'id':card.id,'name':card.name,'rarity':card.rarity} for card in db.scalars(
                    select(Card).where(Card.active.is_(True)).order_by(Card.name)).all()],
                'collectibles':[collectible_dict(c) for c in db.scalars(
                    select(Collectible).where(Collectible.active.is_(True)).order_by(Collectible.name)).all()],
            }

    @app.post('/api/admin/expeditions/{code}')
    async def admin_save_expedition(code: str, request: Request):
        only_admin(request)
        if not re.fullmatch(r'[a-z][a-z0-9_-]{2,29}',code):
            raise HTTPException(422,detail='Código deve ter de 3 a 30 caracteres: letras, números, _ ou -')
        payload=await request.json()
        json_body(payload, ('card_chance','rarity_weights','collectible_chance'))
        existing_defaults=EXPEDITIONS.get(code,{})
        name=str(payload.get('name') or existing_defaults.get('name') or '').strip()
        minutes=integer(payload.get('minutes',existing_defaults.get('minutes',60)))
        food=integer(payload.get('food',existing_defaults.get('food',12)))
        happiness=integer(payload.get('happiness',6))
        health=integer(payload.get('health',0))
        coin_min=integer(payload.get('coin_min',(existing_defaults.get('coins') or (10,20))[0]))
        coin_max=integer(payload.get('coin_max',(existing_defaults.get('coins') or (10,20))[1]))
        enabled=payload.get('enabled',True)
        if not 2<=len(name)<=100 or not 1<=minutes<=43200 or not 0<=food<=85 or not 0<=happiness<=90 or not 0<=health<=90 or not (0<=coin_min<=coin_max<=100000) or type(enabled) is not bool:
            raise HTTPException(422,detail='Informe nome, duração (1 a 43200 minutos), fome (0 a 85), felicidade/saúde (0 a 90), moedas e situação válidos')
        chance=integer(payload['card_chance'])
        collectible_chance=integer(payload['collectible_chance'])
        if not 0<=chance<=100 or not 0<=collectible_chance<=100:
            raise HTTPException(422,detail='A chance deve estar entre 0 e 100%')
        incoming=payload['rarity_weights']
        if not isinstance(incoming,dict) or set(incoming)!=set(TIERS):
            raise HTTPException(422,detail='Informe as chances de todas as quatro raridades')
        if any(type(incoming[key]) not in (int,float) or not 0<=incoming[key]<=100 for key in TIERS):
            raise HTTPException(422,detail='Probabilidades devem estar entre 0 e 100')
        weights={key:float(incoming[key]) for key in TIERS}
        if chance and not sum(weights.values()) and not payload.get('featured_card_id'):
            raise HTTPException(422,detail='Configure ao menos uma raridade com chance positiva')
        image_url=safe_artwork(payload.get('image_url'))
        card_id=payload.get('featured_card_id') or None
        collectible_id=payload.get('collectible_id') or None
        if collectible_chance>0 and collectible_id is None:
            raise HTTPException(422,detail='Selecione um colecionável para configurar sua chance')
        if card_id is not None: card_id=integer(card_id)
        if collectible_id is not None: collectible_id=integer(collectible_id)
        with writing() as db:
            if card_id:
                card=db.get(Card,card_id)
                if not card or not card.active:raise HTTPException(422,detail='Card específico inválido ou arquivado')
            if collectible_id:
                collectible=db.get(Collectible,collectible_id)
                if not collectible or not collectible.active:
                    raise HTTPException(422,detail='Colecionável inválido ou arquivado')
            obj=db.get(ExpeditionConfig,code)
            if not obj:
                obj=ExpeditionConfig(code=code);db.add(obj)
            obj.name=name;obj.minutes=minutes;obj.food=food;obj.happiness=happiness;obj.health=health
            obj.coin_min=coin_min;obj.coin_max=coin_max;obj.enabled=enabled
            obj.image_url=image_url
            obj.card_chance=chance
            obj.rarity_weights=json.dumps(weights,ensure_ascii=False)
            obj.featured_card_id=card_id
            obj.collectible_id=collectible_id
            obj.collectible_chance=collectible_chance
        return {'ok':True,'expedition':code}

    @app.get('/api/admin/collectibles')
    def admin_collectibles(request: Request):
        only_admin(request)
        with SessionLocal() as db:
            items=db.scalars(select(Collectible).order_by(Collectible.id.desc())).all()
            return {'items':[{**collectible_dict(item),'active':bool(item.active)} for item in items]}

    @app.post('/api/admin/collectibles')
    async def admin_save_collectible(request: Request):
        only_admin(request)
        data=json_body(await request.json(),('name',))
        name=str(data['name']).strip()
        if not 2<=len(name)<=100:raise HTTPException(422,detail='Nome entre 2 e 100 caracteres')
        description=str(data.get('description') or '').strip()
        if len(description)>300:raise HTTPException(422,detail='Descrição muito longa')
        emoji=str(data.get('emoji') or '🏆')[:30]
        picture=safe_artwork(data.get('image_url'))
        rarity=str(data.get('rarity') or 'comum').strip().lower()
        if rarity not in TIERS:raise HTTPException(422,detail='Raridade deve ser Comum, Raro, Lendário ou Prismático')
        item_id=data.get('id') or None
        if item_id is not None:item_id=integer(item_id)
        with writing() as db:
            if item_id:
                item=db.get(Collectible,item_id)
                if not item:raise HTTPException(404,detail='Colecionável não encontrado')
            else:
                item=Collectible();db.add(item)
            item.name=name;item.description=description;item.emoji=emoji;item.image_url=picture;item.rarity=rarity
            if 'active' in data:
                if type(data['active']) is not bool:raise HTTPException(422,detail='Ativo precisa ser verdadeiro ou falso')
                item.active=data['active']
            elif not item_id:item.active=True
            db.flush()
            result_id=item.id
        return {'ok':True,'id':result_id}

    @app.get('/api/admin/covers')
    def admin_covers(request: Request):
        only_admin(request)
        with SessionLocal() as db:
            return {'shop': {r.sku:r.image_url for r in db.scalars(select(ProductCover)).all()},
                    'missions': {r.code:r.image_url for r in db.scalars(select(MissionCover)).all()}}

    @app.post('/api/admin/covers')
    async def admin_covers_update(request: Request):
        only_admin(request)
        data = json_body(await request.json(), ('kind','key','image_url'))
        kind, key = str(data['kind']), str(data['key'])
        valid_shop = {'pack3', 'pack5', 'treat3', 'fruit', 'feast', 'vaccine'}
        valid_missions = {x[0] for x in MISSIONS}
        if (kind == 'shop' and key not in valid_shop) or (kind == 'mission' and key not in valid_missions) or kind not in ('shop','mission'):
            raise HTTPException(422, detail='Produto ou missão desconhecido')
        picture = safe_artwork(data['image_url'])
        model, pk = (ProductCover, key) if kind == 'shop' else (MissionCover, key)
        with writing() as db:
            row = db.get(model, pk)
            if not picture:
                if row: db.delete(row)
            elif row:
                row.image_url = picture
            else:
                db.add(model(**({'sku':key} if kind=='shop' else {'code':key}), image_url=picture))
        return {'ok': True, 'image_url': picture}

    @app.post('/api/admin/model-upload')
    async def admin_upload_model(request: Request, files: list[UploadFile] = File(...)):
        """GLB único ou GLTF acompanhado dos .bin e texturas no mesmo pacote."""
        only_admin(request)
        production = os.getenv('APP_ENV','development').strip().lower() == 'production'
        if not files or len(files) > 35:
            raise HTTPException(422, detail='Envie até 35 arquivos por modelo')
        permitted = {'.glb','.gltf','.bin','.png','.jpg','.jpeg','.webp'}
        gathered = {}
        total = 0
        mainfiles = []
        for f in files:
            name = f.filename or ''
            if not re.fullmatch(r'[A-Za-z0-9_+(). -]{1,100}', name) or name.startswith('.') or '..' in name:
                raise HTTPException(422, detail='Use nomes simples, sem pastas, acentos ou caminhos')
            ext = Path(name).suffix.lower()
            if ext not in permitted or name in gathered:
                raise HTTPException(422, detail='Extensão inválida ou arquivo duplicado')
            blob = await f.read(15 * 1024 * 1024 + 1)
            if len(blob) > 15 * 1024 * 1024:
                raise HTTPException(413, detail='Cada arquivo deve ter até 15 MB')
            total += len(blob)
            if total > 40 * 1024 * 1024:
                raise HTTPException(413, detail='Modelo completo maior que 40 MB')
            if ext in ('.glb','.gltf'): mainfiles.append(name)
            gathered[name] = blob
        if len(mainfiles) != 1:
            raise HTTPException(422, detail='Envie exatamente um arquivo principal .glb ou .gltf')
        primary = mainfiles[0]
        blob = gathered[primary]
        if production and not primary.lower().endswith('.glb'):
            raise HTTPException(422, detail='Em produção, envie um GLB único (GLTF com arquivos externos é apenas para testes locais).')
        if primary.lower().endswith('.glb'):
            if len(blob) < 20 or blob[:4] != b'glTF' or int.from_bytes(blob[4:8],'little') != 2 or int.from_bytes(blob[8:12],'little') != len(blob):
                raise HTTPException(422, detail='GLB inválido (esperado formato glTF 2.0)')
        else:
            try:
                doc = json.loads(blob)
                assert doc['asset']['version'].startswith('2.')
                refs = [r.get('uri','') for group in ('buffers','images') for r in doc.get(group,[]) if r.get('uri')]
                for ref in refs:
                    if ref.startswith('data:'): continue
                    if ref not in gathered or '/' in ref or '\\' in ref or '..' in ref:
                        raise ValueError('Arquivo auxiliar ausente')
            except (ValueError, KeyError, TypeError, AssertionError, UnicodeDecodeError):
                raise HTTPException(422, detail='GLTF inválido ou arquivos .bin/texturas ausentes')
        if production:
            cloud=os.getenv('CLOUDINARY_CLOUD_NAME','').strip()
            api_key=os.getenv('CLOUDINARY_API_KEY','').strip()
            api_secret=os.getenv('CLOUDINARY_API_SECRET','').strip()
            if not all((cloud,api_key,api_secret)):
                raise HTTPException(503, detail='Para hospedar GLB permanentemente, configure CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY e CLOUDINARY_API_SECRET no Render; ou utilize uma URL HTTPS pública de .glb.')
            # Cloudinary RAW preserva bytes GLB; o Render nao guarda uploads entre deploys.
            try:
                async with httpx.AsyncClient(timeout=75) as client:
                    response=await client.post(
                        f'https://api.cloudinary.com/v1_1/{cloud}/raw/upload',
                        auth=(api_key,api_secret),
                        data={'folder':'recanto/models'},
                        files={'file': (primary,blob,'model/gltf-binary')},
                    )
                    response.raise_for_status()
                    model_url=response.json().get('secure_url','')
                    if not model_url.startswith('https://') or not model_url.lower().split('?')[0].endswith('.glb'):
                        raise ValueError('O armazenamento não retornou uma URL pública GLB')
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                raise HTTPException(502, detail='Falha ao guardar GLB no Cloudinary. Verifique credenciais, disponibilidade de arquivos RAW e limites da conta.') from exc
            return {'ok':True, 'model_url':model_url, 'files':1}
        folder = frontend / 'models' / uuid.uuid4().hex
        folder.mkdir(parents=True, exist_ok=False)
        for name, contents in gathered.items():
            (folder / name).write_bytes(contents)
        return {'ok':True, 'model_url':f'/models/{folder.name}/{primary}', 'files':len(gathered)}

    @app.get('/models/{folder}/{filename}')
    def view_model(folder: str, filename: str):
        if (folder != 'public' and not re.fullmatch(r'[0-9a-f]{32}', folder)) or not re.fullmatch(r'[A-Za-z0-9_+(). -]{1,100}',filename) or '..' in filename:
            raise HTTPException(404, detail='Modelo não encontrado')
        path=frontend/'models'/folder/filename
        if not path.is_file():
            raise HTTPException(404, detail='Modelo não encontrado')
        from fastapi.responses import FileResponse
        mime = {'.glb':'model/gltf-binary','.gltf':'model/gltf+json','.bin':'application/octet-stream','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp'}.get(path.suffix.lower())
        if not mime: raise HTTPException(404,detail='Arquivo não suportado')
        return FileResponse(path, media_type=mime, headers={'Cache-Control':'public, max-age=3600'})

    @app.post('/api/admin/achievements')
    async def admin_add_achievement(request: Request):
        only_admin(request)
        data = json_body(await request.json(), ('title', 'description', 'event', 'target'))
        title = str(data['title']).strip()
        description = str(data['description']).strip()
        event = str(data['event']).strip()
        target = integer(data['target'])
        icon = str(data.get('icon', '🏅'))[:30]
        image_url = str(data.get('image_url', '')).strip() or None
        if not 2 <= len(title) <= 100 or not 4 <= len(description) <= 255 or not 1 <= target <= 1000000:
            raise HTTPException(422, detail='Nome, descrição ou meta inválida')
        if event not in {'trade', 'card', 'adopt', 'pet', 'feed', 'mission', 'voice_minutes', 'message_count'}:
            raise HTTPException(422, detail='Tipo de conquista inválido')
        if image_url and not (image_url.startswith('/uploads/') or image_url.startswith('https://')):
            raise HTTPException(422, detail='Imagem precisa usar HTTPS ou upload local')
        with writing() as db:
            if db.scalar(select(Achievement.id).where(Achievement.title == title)):
                raise HTTPException(409, detail='Selo com esse nome já existe')
            item = Achievement(title=title, description=description, event=event,
                               icon=icon, image_url=image_url, target=target)
            db.add(item)
            db.flush()
            new_id = item.id
            # Conquistas adicionadas depois contam progresso já acumulado.
            if event not in ('voice_minutes', 'message_count'):
                for row in db.scalars(select(AchievementProgress).where(
                    AchievementProgress.event == event, AchievementProgress.counter >= target)).all():
                    db.add(UserAchievement(user_id=row.user_id, achievement_id=new_id, unlocked_at=utcnow()))
        return {'ok': True, 'id': new_id, 'available': event not in ('voice_minutes', 'message_count') or len(os.getenv('RECANTO_BOT_SECRET','')) >= 32}

    # 0.1.3: editor centralizado. Remover = arquivar (nao quebra referencias antigas).
    @app.get('/api/admin/catalog-management')
    def admin_catalog_management(request: Request):
        only_admin(request)
        with SessionLocal() as db:
            cards = db.scalars(select(Card).order_by(Card.id.desc())).all()
            pets = db.scalars(select(PetSpecies).order_by(PetSpecies.id.desc())).all()
            seals = db.scalars(select(Achievement).order_by(Achievement.id.desc())).all()
            prices = {x.key:x.value for x in db.scalars(select(GameSetting)).all()}
            controls = {x.sku:x for x in db.scalars(select(ShopItemControl)).all()}
            covers = {x.sku:x.image_url for x in db.scalars(select(ProductCover)).all()}
            items=[]
            labels={'pack3':'Pacote com 3 cards','pack5':'Pacote com 5 cards','treat3':'3 Biscoitos','fruit':'Frutinha','feast':'Banquete','vaccine':'Vacina para Pet'}
            price_keys={'pack3':'pack3_cost','pack5':'pack5_cost','treat3':'treat_bundle_cost','fruit':'treat_fruit_cost','feast':'treat_feast_cost','vaccine':'vaccine_cost'}
            for sku,name in labels.items():
                ctrl=controls.get(sku)
                items.append({'id':sku,'name':ctrl.name if ctrl and ctrl.name else name,
                    'price':prices.get(price_keys[sku],DEFAULTS[price_keys[sku]]),
                    'image_url':covers.get(sku),'active':bool(ctrl.active) if ctrl else True})
            return {
                'cards':[{'id':c.id,'name':c.name,'rarity':c.rarity,'collection':c.collection_name,'image_url':c.image_url,'active':bool(c.active)} for c in cards],
                'pets':[{'id':p.id,'name':p.name,'emoji':p.emoji,'image_url':p.image_url,'active':bool(p.active),**model_fields(p)} for p in pets],
                'achievements':[{'id':a.id,'title':a.title,'description':a.description,'icon':a.icon,'event':a.event,'target':a.target,'image_url':a.image_url,'active':bool(a.active)} for a in seals],
                'items':items,
            }

    def card_deletion_summary(db, card_id=None):
        """Preview consistente para 1 Card ou para todo o catálogo."""
        if card_id is None:
            # Limpeza geral: inclui quaisquer referências órfãs de versões antigas.
            tables = ((Card,'cards'), (OwnedCard,'owned'), (ReservedCard,'reservations'),
                      (FavoriteCard,'favorites'), (Trade,'trades'), (CoinOffer,'coin_offers'))
            summary = {key: db.scalar(select(func.count()).select_from(model)) or 0
                       for model,key in tables}
            summary['escrow_coins'] = db.scalar(select(func.coalesce(func.sum(CoinOffer.amount),0)).where(
                CoinOffer.status == 'pendente')) or 0
            return summary
        selected_owned = select(OwnedCard.id)
        selected_reserved = select(ReservedCard.id)
        selected_cards = select(Card.id)
        if card_id is not None:
            selected_owned = selected_owned.where(OwnedCard.card_id == card_id)
            selected_reserved = selected_reserved.where(ReservedCard.card_id == card_id)
            selected_cards = selected_cards.where(Card.id == card_id)
        offer_filter = CoinOffer.owned_id.in_(selected_owned)
        trade_filter = ((Trade.offered_id.in_(selected_owned)) | (Trade.wanted_id.in_(selected_owned)))
        return {
            'cards': db.scalar(select(func.count()).select_from(Card).where(Card.id.in_(selected_cards))) or 0,
            'owned': db.scalar(select(func.count()).select_from(OwnedCard).where(OwnedCard.id.in_(selected_owned))) or 0,
            'reservations': db.scalar(select(func.count()).select_from(ReservedCard).where(ReservedCard.id.in_(selected_reserved))) or 0,
            'favorites': db.scalar(select(func.count()).select_from(FavoriteCard).where(FavoriteCard.owned_id.in_(selected_owned))) or 0,
            'trades': db.scalar(select(func.count()).select_from(Trade).where(trade_filter)) or 0,
            'coin_offers': db.scalar(select(func.count()).select_from(CoinOffer).where(offer_filter)) or 0,
            'escrow_coins': db.scalar(select(func.coalesce(func.sum(CoinOffer.amount), 0)).where(
                offer_filter, CoinOffer.status == 'pendente')) or 0,
        }

    def delete_cards_with_references(db, card_id=None):
        """Exclui Cards sem deixar referências órfãs ou moedas em escrow presas."""
        if card_id is None:
            refundable = db.execute(select(CoinOffer.buyer_id, func.sum(CoinOffer.amount)).where(
                CoinOffer.status == 'pendente').group_by(CoinOffer.buyer_id)).all()
            refunded = 0
            for buyer_id, total in refundable:
                amount = int(total or 0)
                if amount:
                    wallet(db, buyer_id).coins += amount
                    refunded += amount
            for model in (Trade, CoinOffer, FavoriteCard, ReservedCard, OwnedCard):
                db.execute(delete(model))
            db.execute(update(PetExpedition).where(PetExpedition.reward_card_id.is_not(None))
                       .values(reward_card_id=None))
            db.execute(update(ExpeditionConfig).where(ExpeditionConfig.featured_card_id.is_not(None))
                       .values(featured_card_id=None))
            removed = db.execute(delete(Card)).rowcount or 0
            return {'cards_deleted': removed, 'refunded_coins': refunded}
        selected_owned = select(OwnedCard.id)
        selected_cards = select(Card.id)
        if card_id is not None:
            selected_owned = selected_owned.where(OwnedCard.card_id == card_id)
            selected_cards = selected_cards.where(Card.id == card_id)
        trade_filter = (Trade.offered_id.in_(selected_owned) | Trade.wanted_id.in_(selected_owned))
        offers_filter = CoinOffer.owned_id.in_(selected_owned)
        # Devolve todas as moedas reservadas em negociações ainda pendentes.
        refundable = db.execute(select(CoinOffer.buyer_id, func.sum(CoinOffer.amount)).where(
            offers_filter, CoinOffer.status == 'pendente').group_by(CoinOffer.buyer_id)).all()
        refunded = 0
        for buyer_id, total in refundable:
            amount = int(total or 0)
            if amount:
                wallet(db, buyer_id).coins += amount
                refunded += amount
        db.execute(delete(Trade).where(trade_filter))
        db.execute(delete(CoinOffer).where(offers_filter))
        db.execute(delete(FavoriteCard).where(FavoriteCard.owned_id.in_(selected_owned)))
        db.execute(delete(ReservedCard).where(ReservedCard.card_id.in_(selected_cards)))
        db.execute(delete(OwnedCard).where(OwnedCard.id.in_(selected_owned)))
        # IDs podem ser reutilizados: nunca os mantenha como recompensa específica
        # em expedições ou configurações antigas.
        db.execute(update(PetExpedition).where(PetExpedition.reward_card_id.in_(selected_cards))
                   .values(reward_card_id=None))
        db.execute(update(ExpeditionConfig).where(ExpeditionConfig.featured_card_id.in_(selected_cards))
                   .values(featured_card_id=None))
        removed = db.execute(delete(Card).where(Card.id.in_(selected_cards))).rowcount or 0
        return {'cards_deleted': removed, 'refunded_coins': refunded}

    @app.get('/api/admin/cards/delete-all-preview')
    def admin_cards_delete_all_preview(request: Request):
        only_admin(request)
        with SessionLocal() as db:
            return card_deletion_summary(db)

    @app.post('/api/admin/cards/delete-all')
    async def admin_cards_delete_all(request: Request):
        admin_id = only_admin(request)
        data = json_body(await request.json(), ('confirmation',))
        if data['confirmation'] != 'EXCLUIR TODOS OS CARDS':
            raise HTTPException(422, detail='Digite EXCLUIR TODOS OS CARDS para confirmar')
        with writing() as db:
            summary = card_deletion_summary(db)
            result = delete_cards_with_references(db)
            # A marca impede que os cards de demonstração reapareçam ao reiniciar.
            marker = db.get(GameSetting, 'cards_initialized')
            if marker: marker.value = 1
            else: db.add(GameSetting(key='cards_initialized', value=1))
        logging.getLogger('recanto.admin').warning(
            'Exclusão TOTAL de Cards: admin=%s quantidade=%s reembolsos=%s',
            admin_id, result['cards_deleted'], result['refunded_coins'])
        return {'ok': True, **summary, **result,
                'note': 'Pacotes não abertos são mantidos e recebem novas reservas na abertura após o catálogo ser reposto.'}

    @app.get('/api/admin/cards/{card_id}/delete-preview')
    def admin_card_delete_preview(card_id: int, request: Request):
        only_admin(request)
        with SessionLocal() as db:
            card = db.get(Card, card_id)
            if not card:
                raise HTTPException(404, detail='Card não encontrado')
            return {'id': card.id, 'name': card.name, **card_deletion_summary(db, card_id)}

    @app.post('/api/admin/catalog-management/{group}/{ident}')
    async def admin_manage_catalog(group: str, ident: str, request: Request):
        only_admin(request)
        if group not in ('cards','pets','achievements','items'):
            raise HTTPException(404,detail='Catálogo desconhecido')
        payload=await request.json()
        if not isinstance(payload,dict):raise HTTPException(422,detail='Dados inválidos')
        action=str(payload.get('action','save'))
        if action not in ('save','archive','restore','delete'):
            raise HTTPException(422,detail='Ação inválida')
        with writing() as db:
            if group=='items':
                price_keys={'pack3':'pack3_cost','pack5':'pack5_cost','treat3':'treat_bundle_cost','fruit':'treat_fruit_cost','feast':'treat_feast_cost','vaccine':'vaccine_cost'}
                if ident not in price_keys:raise HTTPException(404,detail='Item inexistente')
                ctrl=db.get(ShopItemControl,ident)
                if not ctrl:ctrl=ShopItemControl(sku=ident);db.add(ctrl)
                if action=='archive':ctrl.active=False
                elif action=='restore':ctrl.active=True
                else:
                    name=str(payload.get('name') or '').strip()
                    price=integer(payload.get('price'))
                    if not 2<=len(name)<=100 or not 0<=price<=100000:
                        raise HTTPException(422,detail='Nome ou preço inválido')
                    ctrl.name=name
                    conf=db.get(GameSetting,price_keys[ident]);conf.value=price
                    if 'image_url' in payload:
                        image_url=safe_artwork(payload.get('image_url'))
                        cover=db.get(ProductCover,ident)
                        if not image_url and cover:db.delete(cover)
                        elif image_url and cover:cover.image_url=image_url
                        elif image_url:db.add(ProductCover(sku=ident,image_url=image_url))
            else:
                try:item_id=int(ident)
                except ValueError:raise HTTPException(422,detail='ID numérico inválido')
                kind={'cards':Card,'pets':PetSpecies,'achievements':Achievement}[group]
                obj=db.get(kind,item_id)
                if not obj:raise HTTPException(404,detail='Registro não encontrado')
                if action == 'delete':
                    if group != 'cards':
                        raise HTTPException(422, detail='Exclusão permanente disponível somente para cards')
                    if payload.get('confirmation') != f'EXCLUIR {item_id}' or payload.get('card_name') != obj.name:
                        raise HTTPException(422, detail='Confirmação de exclusão inválida')
                    delete_cards_with_references(db, card_id=item_id)
                elif action=='archive':obj.active=False
                elif action=='restore':obj.active=True
                elif group=='cards':
                    name=str(payload.get('name','')).strip()
                    rarity=str(payload.get('rarity','')).strip()
                    collection=str(payload.get('collection','')).strip()
                    if not 2<=len(name)<=120 or rarity not in TIERS or not 2<=len(collection)<=100:
                        raise HTTPException(422,detail='Nome, raridade ou coleção inválidos')
                    obj.name=name;obj.rarity=rarity;obj.collection_name=collection
                    obj.image_url=safe_artwork(payload.get('image_url'))
                elif group=='pets':
                    name=str(payload.get('name','')).strip()
                    if not 2<=len(name)<=100:raise HTTPException(422,detail='Nome inválido')
                    if db.scalar(select(PetSpecies.id).where(PetSpecies.name==name,PetSpecies.id!=item_id)):
                        raise HTTPException(409,detail='Outro Pet já usa este nome')
                    obj.name=name;obj.emoji=str(payload.get('emoji') or '🐾')[:30]
                    obj.image_url=safe_artwork(payload.get('image_url'))
                    model=safe_artwork(payload.get('model_url'),allow_model=True)
                    if model and not model.lower().split('?')[0].endswith(('.glb','.gltf')):
                        raise HTTPException(422,detail='Modelo deve ser .glb ou .gltf')
                    obj.model_url=model
                    for field in ('idle_animation','pet_animation','feed_animation','vet_animation'):
                        value=str(payload.get(field) or '').strip()
                        if len(value)>80:raise HTTPException(422,detail='Nome de animação muito longo')
                        setattr(obj,field,value or None)
                else:
                    title=str(payload.get('title','')).strip()
                    description=str(payload.get('description','')).strip()
                    event=str(payload.get('event','')).strip()
                    target=integer(payload.get('target'))
                    if not 2<=len(title)<=100 or not 4<=len(description)<=255 or not 1<=target<=1000000:
                        raise HTTPException(422,detail='Nome, descrição ou meta inválidos')
                    if event not in {'trade','card','adopt','pet','feed','mission','voice_minutes','message_count'}:
                        raise HTTPException(422,detail='Evento inválido')
                    if db.scalar(select(Achievement.id).where(Achievement.title==title,Achievement.id!=item_id)):
                        raise HTTPException(409,detail='Outro selo já possui este título')
                    obj.title=title;obj.description=description;obj.event=event;obj.target=target
                    obj.icon=str(payload.get('icon') or '🏅')[:30]
                    obj.image_url=safe_artwork(payload.get('image_url'))
        if action == 'delete':
            logging.getLogger('recanto.admin').warning('Card permanentemente excluído: admin=%s id=%s nome=%s', me(request), ident, payload.get('card_name'))
        return {'ok':True,'group':group,'id':ident,'action':action}

    @app.post('/api/admin/upload')
    async def upload_card_art(request: Request, image: UploadFile = File(...)):
        only_admin(request)
        # Alguns navegadores classificam WEBP como application/octet-stream.
        # O conteúdo real é sempre verificado com Pillow antes do armazenamento.
        file_name = (image.filename or '').lower()
        if image.content_type not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif', 'application/octet-stream') and not file_name.endswith(('.png','.jpg','.jpeg','.webp','.gif')):
            raise HTTPException(422, detail='Use PNG, JPG, WEBP ou GIF')
        data = await image.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024:
            raise HTTPException(413, detail='Imagem acima de 4 MB')
        import io
        try:
            with Image.open(io.BytesIO(data)) as im:
                if im.width > 4000 or im.height > 4000:
                    raise ValueError('Grande demais')
                im.verify()
            with Image.open(io.BytesIO(data)) as im:
                fmt = im.format
        except (ValueError, OSError, Image.DecompressionBombError):
            raise HTTPException(422, detail='Arquivo de imagem inválido')
        if fmt not in ('PNG', 'JPEG', 'WEBP', 'GIF'):
            raise HTTPException(422, detail='Formato de imagem não permitido')
        ext = {'PNG': 'png', 'JPEG': 'jpg', 'WEBP': 'webp', 'GIF': 'gif'}[fmt]
        if os.getenv('APP_ENV', 'development').strip().lower() == 'production':
            # Upload assinado no servidor; o segredo Cloudinary NUNCA vai ao navegador.
            cloud = os.getenv('CLOUDINARY_CLOUD_NAME', '').strip()
            api_key = os.getenv('CLOUDINARY_API_KEY', '').strip()
            api_secret = os.getenv('CLOUDINARY_API_SECRET', '').strip()
            if not all((cloud, api_key, api_secret)):
                raise HTTPException(503, detail='Configure Cloudinary no Render para salvar imagens permanentemente (ou utilize URL HTTPS).')
            timestamp = str(int(time.time()))
            signed = f'folder=recanto&timestamp={timestamp}'
            signature = hashlib.sha1((signed + api_secret).encode('utf-8')).hexdigest()
            try:
                async with httpx.AsyncClient(timeout=35) as client:
                    response = await client.post(
                        f'https://api.cloudinary.com/v1_1/{cloud}/image/upload',
                        data={'api_key': api_key, 'timestamp': timestamp, 'folder':'recanto', 'signature':signature},
                        files={'file': (f'arte.{ext}', data, {'png':'image/png','jpg':'image/jpeg','webp':'image/webp','gif':'image/gif'}[ext])},
                    )
                    response.raise_for_status()
                    image_url = response.json().get('secure_url', '')
                    if not image_url.startswith('https://'):
                        raise ValueError('URL segura ausente na resposta')
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                raise HTTPException(502, detail='Falha ao enviar imagem ao armazenamento externo. Verifique as credenciais do Cloudinary.') from exc
            return {'ok': True, 'image_url': image_url}
        filename = secrets.token_hex(15) + '.' + ext
        folder = frontend / 'uploads'
        folder.mkdir(exist_ok=True)
        (folder / filename).write_bytes(data)
        return {'ok': True, 'image_url': '/uploads/' + filename}

    @app.post('/api/admin/upload-svg')
    async def upload_safe_svg(request: Request, image: UploadFile = File(...)):
        """SVG de ícones e favicon, validado antes de armazenar ou distribuir."""
        only_admin(request)
        if not image.filename or not image.filename.lower().endswith('.svg'):
            raise HTTPException(422, detail='Envie um arquivo SVG')
        data = await image.read(1024 * 1024 + 1)
        if not data or len(data) > 1024 * 1024:
            raise HTTPException(413, detail='SVG vazio ou acima de 1 MB')
        import xml.etree.ElementTree as ET
        import re as _re
        # SVG pode conter HTML/JS mesmo sem um <script> visível.
        # Declaracao XML padrao do Corel/Illustrator é permitida; outras instruções não.
        check_data = _re.sub(rb'^\s*<\?xml\s+[^>]*\?>', b'', data, flags=_re.I)
        if _re.search(rb'<!DOCTYPE|<!ENTITY|<\?|javascript\s*:|@import|expression\s*\(|-moz-binding', check_data, _re.I):
            raise HTTPException(422, detail='SVG contém conteúdo não permitido')
        try:
            root = ET.fromstring(data)
        except (ET.ParseError, ValueError):
            raise HTTPException(422, detail='XML SVG inválido')
        svg_ns = 'http://www.w3.org/2000/svg'
        if root.tag != '{%s}svg' % svg_ns:
            raise HTTPException(422, detail='Arquivo não é SVG')
        safe_tags = {'svg','g','defs','symbol','use','path','rect','circle','ellipse',
                     'line','polyline','polygon','linearGradient','radialGradient',
                     'stop','clipPath','mask','pattern','title','desc','style','text',
                     'tspan','filter','feGaussianBlur','feOffset','feBlend',
                     'feColorMatrix','feComposite','feMerge','feMergeNode',
                     'feFlood','feDropShadow'}
        for el in root.iter():
            if el.tag.rsplit('}',1)[-1] not in safe_tags:
                raise HTTPException(422, detail='SVG possui elemento não permitido')
            if el.tag.rsplit('}',1)[-1]=='style' and el.text and _re.search(r'url\s*\(\s*[^\s#\"\']|@|javascript|expression', el.text, _re.I):
                raise HTTPException(422, detail='Estilo SVG não permitido')
            for attr, val in el.attrib.items():
                key = attr.rsplit('}',1)[-1].lower()
                if key.startswith('on') or key in ('formaction','src','target'):
                    raise HTTPException(422, detail='Evento ou atributo SVG não permitido')
                if key=='href' and not val.strip().startswith('#'):
                    raise HTTPException(422, detail='SVG com referência externa não permitida')
                if _re.search(r'javascript\s*:|data\s*:|https?\s*:|@import|expression\s*\(|url\s*\(\s*(?![\"\']?#)', val, _re.I):
                    raise HTTPException(422, detail='SVG com recurso externo não permitido')
        if os.getenv('APP_ENV', 'development').strip().lower() == 'production':
            cloud = os.getenv('CLOUDINARY_CLOUD_NAME','').strip()
            api_key = os.getenv('CLOUDINARY_API_KEY','').strip()
            api_secret = os.getenv('CLOUDINARY_API_SECRET','').strip()
            if not all((cloud,api_key,api_secret)):
                raise HTTPException(503, detail='Configure Cloudinary para salvar SVG permanentemente')
            timestamp = str(int(time.time()))
            signed = f'folder=recanto&timestamp={timestamp}'
            signature = hashlib.sha1((signed + api_secret).encode('utf-8')).hexdigest()
            try:
                async with httpx.AsyncClient(timeout=35) as client:
                    response = await client.post(
                        f'https://api.cloudinary.com/v1_1/{cloud}/image/upload',
                        data={'api_key':api_key,'timestamp':timestamp,'folder':'recanto','signature':signature},
                        files={'file':('icone.svg',data,'image/svg+xml')},
                    )
                    response.raise_for_status()
                    url = response.json().get('secure_url','')
                    if not url.startswith('https://'):
                        raise ValueError('URL segura ausente')
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                raise HTTPException(502, detail='Falha no envio do SVG ao Cloudinary. Confira se a conta permite SVGs.') from exc
            return {'ok':True, 'image_url':url}
        filename = secrets.token_hex(15) + '.svg'
        folder = frontend / 'uploads'
        folder.mkdir(exist_ok=True)
        (folder / filename).write_bytes(data)
        return {'ok':True, 'image_url':'/uploads/'+filename}

    @app.get('/uploads/{filename}')
    def view_art(filename: str):
        if not filename or '/' in filename or '\\' in filename or len(filename) > 90:
            raise HTTPException(404, detail='Imagem não encontrada')
        path = frontend / 'uploads' / filename
        if not path.is_file():
            raise HTTPException(404, detail='Imagem não encontrada')
        extra={'Cache-Control': 'public, max-age=3600', 'X-Content-Type-Options':'nosniff'}
        if filename.lower().endswith('.svg'):
            extra['Content-Security-Policy']="default-src 'none'; style-src 'unsafe-inline'"
        return FileResponse(path, headers=extra)

    # 0.1.2: operações administrativas de manutenção, inclusive no PWA mobile.
    # Não expor simulações de desenvolvimento nem restauração de catálogos em produção.
    # O usuário é autenticado via sessão Discord e conferido na lista de administradores.
    # 0.1.12: ajuste manual de saldo para testes, restrito a administradores autenticados.
    @app.post('/api/admin/wallet/adjust')
    async def admin_adjust_wallet(request: Request):
        admin_id = only_admin(request)
        data = json_body(await request.json(), ('discord_id', 'amount', 'action'))
        target = str(data['discord_id']).strip()
        amount = integer(data['amount'])
        action = str(data['action'])
        if not target.isdecimal() or not 15 <= len(target) <= 22:
            raise HTTPException(422, detail='ID do usuário Discord inválido')
        if amount < 1 or amount > 100000:
            raise HTTPException(422, detail='Quantidade deve ser entre 1 e 100.000')
        if action not in ('add', 'remove'):
            raise HTTPException(422, detail='Operação inválida')
        with writing() as db:
            if db.get(User, target) is None:
                raise HTTPException(404, detail='O usuário ainda não entrou no Recanto')
            balance = wallet(db, target)
            if action == 'remove' and balance.coins < amount:
                raise HTTPException(409, detail='Saldo insuficiente para retirar esta quantia')
            balance.coins += amount if action == 'add' else -amount
            new_balance = balance.coins
        logger = logging.getLogger('recanto.admin')
        logger.info('Ajuste administrativo de moedas: admin=%s usuario=%s acao=%s quantidade=%s', admin_id, target, action, amount)
        return {'ok': True, 'balance': new_balance, 'discord_id': target}

    @app.post('/api/admin/reset-daily')
    def admin_reset_daily(request: Request):
        uid = only_admin(request)
        with writing() as db:
            for row in db.scalars(select(Claim).where(Claim.user_id == uid)).all():
                db.delete(row)
            cooldown = db.get(CardCooldown, uid)
            if cooldown: db.delete(cooldown)
            for progress in db.scalars(select(MissionProgress).where(
                    MissionProgress.user_id == uid,
                    MissionProgress.day == local_day())).all():
                db.delete(progress)
            db.execute(delete(MissionActionDaily).where(
                MissionActionDaily.user_id==uid,MissionActionDaily.day==local_day()))
            db.execute(delete(RecantoMissionExtraProgress).where(
                RecantoMissionExtraProgress.user_id==uid,
                RecantoMissionExtraProgress.period==local_day()))
        return {'ok': True, 'detail': 'Resgates diários do administrador reiniciados'}

    # A limpeza seletiva preserva contas, sessões, catálogos e configurações.
    # As dependências cruzadas (trocas, cópias, reservas, Feed) são removidas
    # antes de suas entidades principais para manter integridade referencial.
    RESET_GROUPS = {
        'economy': 'Moedas, petiscos e inventário de petiscos',
        'cards': 'Cards, pacotes e trocas',
        'pets': 'Pets, expedições e colecionáveis',
        'missions': 'Missões e resgates diários',
        'badges': 'Selos e progresso das conquistas',
        'favorites': 'Favoritos (Cards, campeões e jogos)',
        'feed': 'Feed, respostas e curtidas',
        'levels': 'EXP, níveis e histórico de EXP',
        'discord': 'Histórico de atividade Discord (inclui recibos de deduplicação)',
    }

    @app.get('/api/admin/reset-users')
    def admin_reset_users(request:Request):
        only_admin(request)
        with SessionLocal() as db:
            rows=db.scalars(select(User).order_by(User.username).limit(300)).all()
            return {'members':[{'id':u.id,'name':u.username} for u in rows],
                    'total':db.scalar(select(func.count(User.id))) or 0,
                    'categories':RESET_GROUPS}

    @app.post('/api/admin/reset-progress')
    async def admin_reset_progress(request: Request):
        admin_id=only_admin(request)
        payload=json_body(await request.json(),('confirmation',))
        categories=payload.get('categories')
        if not isinstance(categories,list) or not categories or len(categories)>len(RESET_GROUPS) or any(
            not isinstance(c,str) or c not in RESET_GROUPS for c in categories) or len(set(categories))!=len(categories):
            raise HTTPException(422,detail='Escolha uma ou mais categorias válidas')
        selected=set(categories)
        target=str(payload.get('user_id') or '').strip()
        if target and (not target.isascii() or not target.isdecimal() or not 15<=len(target)<=22):
            raise HTTPException(422,detail='ID Discord inválido')
        entire=set(RESET_GROUPS)==selected
        expected='LIMPAR TUDO' if entire and not target else 'LIMPAR SELECIONADOS'
        if payload['confirmation']!=expected:
            raise HTTPException(422,detail='Digite '+expected+' para confirmar')
        def purge(db,cls,predicate=None):
            statement=delete(cls)
            if predicate is not None:statement=statement.where(predicate)
            return db.execute(statement).rowcount or 0
        def uid_predicate(cls,attr='user_id'):
            return getattr(cls,attr)==target if target else None
        def extras(db,name):
            table=Base.metadata.tables.get(name)
            if table is None:return
            stmt=delete(table)
            if target:
                col=table.c.get('user_id')
                if col is None:col=table.c.get('discord_id')
                if col is None:return
                stmt=stmt.where(col==target)
            db.execute(stmt)
        with writing() as db:
            if target and db.get(User,target) is None:
                raise HTTPException(404,detail='Membro não encontrado no Recanto')
            if 'pets' in selected or 'economy' in selected:
                # Propostas de itens pendentes não podem sobreviver à limpeza de itens/saldo.
                # Reembolsar escrow quando só parte dos dados é removida.
                affected=db.scalars(select(CollectibleDeal).where(
                    ((CollectibleDeal.sender_id==target)|(CollectibleDeal.receiver_id==target))
                    if target else True)).all()
                for deal in affected:
                    if deal.status=='pendente' and deal.kind=='buy' and 'economy' not in selected:
                        wallet(db,deal.sender_id).coins+=deal.amount
                    db.delete(deal)
                db.flush()
            if 'cards' in selected:
                owned_ids=select(OwnedCard.id).where(OwnedCard.user_id==target) if target else None
                pack_ids=select(InventoryPack.id).where(InventoryPack.user_id==target) if target else None
                purge(db,Trade, ( (Trade.sender_id==target)|(Trade.receiver_id==target)|
                    Trade.offered_id.in_(owned_ids)|Trade.wanted_id.in_(owned_ids)) if target else None)
                purge(db,CoinOffer,((CoinOffer.buyer_id==target)|(CoinOffer.seller_id==target)|
                    CoinOffer.owned_id.in_(owned_ids)) if target else None)
                purge(db,FavoriteCard,((FavoriteCard.user_id==target)|FavoriteCard.owned_id.in_(owned_ids)) if target else None)
                purge(db,ReservedCard,ReservedCard.pack_id.in_(pack_ids) if target else None)
                for cls in (InventoryPack,TradeReward,OwnedCard,CardCooldown):
                    purge(db,cls,uid_predicate(cls))
            if 'economy' in selected:
                purge(db,InventoryTreat,uid_predicate(InventoryTreat))
                for w in db.scalars(select(Wallet).where(Wallet.user_id==target) if target else select(Wallet)).all():
                    w.coins=0;w.treats=0
            if 'pets' in selected:
                purge(db,VisitorCare,((VisitorCare.visitor_id==target)|(VisitorCare.owner_id==target)) if target else None)
                for cls in (PetExpedition,InventoryCollectible,UserPet):purge(db,cls,uid_predicate(cls))
            if 'missions' in selected:
                for cls in (Claim,MissionProgress):purge(db,cls,uid_predicate(cls))
                purge(db,RecantoMissionExtraProgress,uid_predicate(RecantoMissionExtraProgress))
                purge(db,MissionActionDaily,uid_predicate(MissionActionDaily))
                for table in ('recanto_mission_counters','recanto_mission_claims'):
                    extras(db,table)
            if 'badges' in selected:
                for cls in (UserAchievement,AchievementProgress):purge(db,cls,uid_predicate(cls))
            if 'favorites' in selected:
                for cls in (FavoriteCard,FavoriteChampion,FavoriteGame):purge(db,cls,uid_predicate(cls))
            if 'feed' in selected:
                if target:
                    post_ids=select(FeedEvent.id).where(FeedEvent.user_id==target)
                    purge(db,FeedReply,(FeedReply.user_id==target)|FeedReply.event_id.in_(post_ids))
                    purge(db,FeedLike,(FeedLike.user_id==target)|FeedLike.event_id.in_(post_ids))
                    purge(db,FeedEvent,FeedEvent.user_id==target)
                    purge(db,FeedDailyReward,FeedDailyReward.user_id==target)
                else:
                    for cls in (FeedReply,FeedLike,FeedEvent,FeedDailyReward):purge(db,cls)
            if 'levels' in selected:
                # IMPORTANTE: o reset total também precisa zerar EXP e nivel.
                for cls in (ExperienceOnce,ExperienceLog,UserExperience):purge(db,cls,uid_predicate(cls))
            if 'discord' in selected:
                for cls in (DiscordActivityEvent,DiscordMessageRate):purge(db,cls,uid_predicate(cls))
                extras(db,'recanto_discord_events')
            if entire:
                extras(db,'recanto_notification_sent')
        logging.getLogger('recanto.admin').warning(
            'Reset de progresso: admin=%s alvo=%s categorias=%s',admin_id,target or 'todos',','.join(sorted(selected)))
        return {'ok':True,'scope':'selected','user_id':target or None,
                'categories':sorted(selected),'levels_reset':'levels' in selected,
                'detail':'Categorias escolhidas reiniciadas; contas, catálogos e configurações mantidos'}

    @app.post('/api/dev/grant-coins')
    async def grant_test_coins(request: Request):
        uid=test_admin(request)
        data=json_body(await request.json(),('amount',))
        amount=integer(data['amount'])
        if amount<1 or amount>100000:
            raise HTTPException(422,detail='Valor de teste entre 1 e 100000')
        target=str(data.get('user_id') or uid)
        with writing() as db:
            if not db.get(User,target): raise HTTPException(404, detail='Membro não encontrado')
            wallet(db,target).coins+=amount
        return {'ok':True, 'amount':amount}

    @app.post('/api/dev/advance-pet')
    async def dev_advance_pet(request: Request):
        uid = test_admin(request)
        data = json_body(await request.json(), ('stage',))
        stage = str(data['stage'])
        if stage not in ('vet', 'death'):
            raise HTTPException(422, detail='Etapa inválida')
        with writing() as db:
            obj = db.get(UserPet, uid)
            if not obj:
                raise HTTPException(409, detail='Primeiro adote um Pet')
            if stage == 'vet':
                if obj.status != 'ativo':
                    raise HTTPException(409, detail='Pet não está ativo')
                obj.last_action_at = utcnow() - timedelta(hours=setting(db, 'neglect_hours') + 1)
                obj.last_tick_at = obj.last_action_at
            if stage == 'death':
                if obj.status != 'vet':
                    raise HTTPException(409, detail='Primeiro envie o Pet ao veterinário')
                obj.vet_since = utcnow() - timedelta(days=setting(db, 'vet_dead_days') + 1)
            pet_tick(db, obj)
            state = obj.status
        return {'ok': True, 'status': state}

    @app.post('/api/dev/reset-daily')
    def dev_reset_daily(request: Request):
        uid = test_admin(request)
        with writing() as db:
            for cl in db.scalars(select(Claim).where(Claim.user_id == uid)).all():
                db.delete(cl)
            cooldown=db.get(CardCooldown,uid)
            if cooldown:db.delete(cooldown)
            for m in db.scalars(select(MissionProgress).where(MissionProgress.user_id == uid, MissionProgress.day == local_day())).all():
                db.delete(m)
            db.execute(delete(MissionActionDaily).where(MissionActionDaily.user_id==uid,MissionActionDaily.day==local_day()))
            db.execute(delete(RecantoMissionExtraProgress).where(RecantoMissionExtraProgress.user_id==uid,
                RecantoMissionExtraProgress.period==local_day()))
        return {'ok': True}

    @app.post('/api/dev/reset-all')
    async def reset_all(request: Request):
        """Somente admin Discord no PC: apaga progresso ou restaura catálogos."""
        test_admin(request)
        payload = json_body(await request.json(), ('scope','confirmation'))
        scope = str(payload['scope'])
        if scope not in ('progress','factory') or payload['confirmation'] != 'LIMPAR TUDO':
            raise HTTPException(422, detail='Confirme digitando LIMPAR TUDO')
        with writing() as db:
            for table in (MissionActionDaily,RecantoMissionExtraProgress,VisitorCare, FavoriteCard, ReservedCard, InventoryPack, InventoryTreat, InventoryCollectible,
                          CollectibleDeal,CoinOffer, CardCooldown, PetExpedition, FavoriteGame, FavoriteChampion, TradeReward, Trade, MissionProgress, Claim, UserAchievement,
                          AchievementProgress, UserPet, OwnedCard):
                db.execute(delete(table))
            # 0.3.1: limpeza local completa também reinicia nível, EXP, Feed
            # e recibos do bot. Os rankings configurados permanecem.
            for cls in (FeedReply,FeedLike,FeedEvent,FeedDailyReward,
                        ExperienceOnce,ExperienceLog,UserExperience,
                        DiscordActivityEvent,DiscordMessageRate):
                db.execute(delete(cls))
            # Progresso e deduplicação da v1.2 também devem ser reiniciados
            # nas ferramentas EXCLUSIVAMENTE locais de teste.
            for name in ('recanto_mission_counters','recanto_mission_claims',
                         'recanto_discord_events','recanto_notification_sent'):
                extra=Base.metadata.tables.get(name)
                if extra is not None:db.execute(delete(extra))
            for w in db.scalars(select(Wallet)).all():
                w.coins = 0
                w.treats = 0
            if scope == 'factory':
                for table in (ProductCover, MissionCover, Achievement, PetSpecies, Card, GameSetting):
                    db.execute(delete(table))
                for key, value in DEFAULTS.items():
                    db.add(GameSetting(key=key, value=value))
                for tier, names in SEED_CARDS.items():
                    for name in names:
                        db.add(Card(name=name, rarity=tier, image_url=None))
                for name, emoji in SEED_PETS:
                    db.add(PetSpecies(name=name, emoji=emoji))
                for name, desc, icon, event, threshold in SEED_BADGES:
                    db.add(Achievement(title=name, description=desc, icon=icon,
                                       event=event, target=threshold))
        return {'ok': True, 'scope': scope, 'note': 'Contas Discord preservadas; todo progresso reiniciado'}
