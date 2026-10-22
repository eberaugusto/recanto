"""Recanto v0.9.1. Economia e jogo executados inteiramente no servidor.

Ações que alteram saldo/itens usam transações serializadas. O browser só pede
operações; nunca escolhe resultado de sorteio, saldo, recompensa ou tempo.
"""
from __future__ import annotations

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
import json
import re
import uuid

from fastapi import HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, and_, func, select, text, inspect, delete
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
    'vet_cost': 180, 'neglect_hours': 48,
    'vet_dead_days': 3,
}
MISSIONS = [
    ('daily_card', 'Resgate um card', 1, 12),
    ('daily_coins', 'Resgate suas moedas diárias', 1, 8),
    ('trade', 'Conclua uma troca', 1, 30),
    ('pet', 'Acaricie seu pet', 1, 8),
    ('feed', 'Alimente seu pet', 1, 12),
    ('adopt', 'Adote um pet', 1, 20),
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
    ('ffxiv','Final Fantasy XIV','🐉'),('honkai','Honkai: Star Rail','🚂'),
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
SEED_PETS = [('Pequena Lenda — exemplo 1', '🐾'), ('Pequena Lenda — exemplo 2', '✨')]
SHOP_EMOJI = {'pack3':'🃏','pack5':'🎴','treat3':'🍪','fruit':'🍓','feast':'🍖'}
TREAT_TYPES = {'biscoito':{'name':'Biscoito','food':15,'emoji':'🍪'},
               'fruta':{'name':'Frutinha','food':30,'emoji':'🍓'},
               'banquete':{'name':'Banquete','food':55,'emoji':'🍖'}}
MISSION_EMOJI = {'daily_card':'🃏','daily_coins':'🪙','trade':'🔄','pet':'💗','feed':'🍪','adopt':'🐾','pack':'🎁'}
# O evento voice_minutes não é emitido pelo PWA: precisa de integração Gateway autorizada.
SEED_BADGES = [
    ('Primeira Troca', 'Troque seu primeiro card com outro membro.', '🤝', 'trade', 1),
    ('Colecionador', 'Receba 10 cards em sua coleção.', '🃏', 'card', 10),
    ('Companheiro', 'Adote seu primeiro pet.', '🐾', 'adopt', 1),
    ('Carinho de Ouro', 'Acaricie seu pet 10 vezes.', '💞', 'pet', 10),
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
                  demo_enabled, root: Path, frontend: Path):
    class UIAsset(Base):
        """Imagens personalizadas por elemento/jogo, administradas no servidor."""
        __tablename__ = 'ui_assets'
        key: Mapped[str] = mapped_column(String(70), primary_key=True)
        selector: Mapped[str] = mapped_column(String(180), default='')
        mode: Mapped[str] = mapped_column(String(14), default='background')
        image_url: Mapped[str] = mapped_column(String(512), nullable=False)

    class GameSetting(Base):
        __tablename__ = 'game_settings'
        key: Mapped[str] = mapped_column(String(45), primary_key=True)
        value: Mapped[int] = mapped_column(Integer, nullable=False)

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

    class FeaturedCollection(Base):
        __tablename__ = 'featured_collections'
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        name: Mapped[str] = mapped_column(String(100), nullable=False)
        image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    class PetExpedition(Base):
        __tablename__ = 'pet_expeditions'
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        mission: Mapped[str] = mapped_column(String(30), nullable=False)
        started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
        ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
        coins: Mapped[int] = mapped_column(Integer, nullable=False)
        card_award: Mapped[bool] = mapped_column(Boolean, default=False)

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

    class AchievementProgress(Base):
        __tablename__ = 'achievement_progress'
        user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
        event: Mapped[str] = mapped_column(String(30), primary_key=True)
        counter: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

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
        status: Mapped[str] = mapped_column(String(15), default='ativo')
        food: Mapped[int] = mapped_column(Integer, default=85)
        happiness: Mapped[int] = mapped_column(Integer, default=85)
        adopted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
        last_action_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
        last_tick_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
        last_feed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
        last_pet_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
        vet_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    Base.metadata.create_all(engine)
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
        if not (db.scalar(select(func.count(Card.id))) or 0):
            for tier, names in SEED_CARDS.items():
                for name in names:
                    db.add(Card(name=name, rarity=tier, image_url=None))
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
                                 (TradeReward, 'user_id'), (MissionProgress, 'user_id'),
                                 (Claim, 'user_id'), (UserAchievement, 'user_id'),
                                 (AchievementProgress, 'user_id'), (UserPet, 'user_id'),
                                 (OwnedCard, 'user_id'), (CardCooldown, 'user_id'), (FavoriteGame,'user_id'),
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

    def card_bonus(db, rarity):
        if rarity not in TIERS:
            raise HTTPException(409, detail='Raridade invalida para recompensa')
        return setting(db, 'card_bonus_'+rarity)

    def next_card_available(db, uid):
        row=db.get(CardCooldown,uid)
        return naive_to_utc(row.last_claimed)+timedelta(hours=5) if row else None

    def game_entry(db, row):
        key,name,emoji=row
        image=db.get(UIAsset, 'game:'+key)
        return {'id':key, 'name':name, 'icon':emoji, 'image_url':image.image_url if image else None}

    def user_games(db, uid):
        entries=sorted(db.scalars(select(FavoriteGame).where(FavoriteGame.user_id==uid)).all(),key=lambda x:x.position)
        options={g[0]:g for g in GAMES}
        return [game_entry(db,options[g.game_id]) for g in entries if g.game_id in options]

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

    def progress(db, uid, mission, amount=1):
        day = local_day()
        obj = db.get(MissionProgress, (uid, day, mission))
        if obj is None:
            db.add(MissionProgress(user_id=uid, day=day, mission=mission, progress=amount, claimed=False))
        else:
            obj.progress = min(9999, obj.progress + amount)

    def achievement_event(db, uid, event, amount=1):
        # Nunca aceitar progresso arbitrário enviado pelo navegador.
        if event == 'voice_minutes':
            return
        obj = db.get(AchievementProgress, (uid, event))
        if obj is None:
            obj = AchievementProgress(user_id=uid, event=event, counter=0)
            db.add(obj)
        obj.counter += amount
        db.flush()
        for award in db.scalars(select(Achievement).where(Achievement.event == event,
                                                              Achievement.target <= obj.counter)).all():
            if not db.get(UserAchievement, (uid, award.id)):
                db.add(UserAchievement(user_id=uid, achievement_id=award.id, unlocked_at=utcnow()))

    @app.get('/api/achievements')
    def achievements(request: Request):
        uid = me(request)
        with SessionLocal() as db:
            goals = db.scalars(select(Achievement).order_by(Achievement.id)).all()
            progresses = {row.event: row.counter for row in db.scalars(
                select(AchievementProgress).where(AchievementProgress.user_id == uid)).all()}
            unlocks = {row.achievement_id: row.unlocked_at for row in db.scalars(
                select(UserAchievement).where(UserAchievement.user_id == uid)).all()}
            return {'unlocked': len(unlocks), 'total': len(goals), 'items': [
                {'id': g.id, 'title': g.title, 'description': g.description,
                 'icon': g.icon, 'image_url': g.image_url, 'event': g.event,
                 'target': g.target, 'progress': min(g.target, progresses.get(g.event, 0)),
                 'locked': g.id not in unlocks, 'available': g.event != 'voice_minutes',
                 'unlocked_at': unlocks[g.id].isoformat() if g.id in unlocks else None}
                for g in goals]}

    def stock(db):
        # Emissão global: 3 cópias por título Comum; 2 Raro; 1 Lendário/Prismático.
        rows = db.execute(select(Card.id, Card.name, Card.rarity, Card.image_url, Card.collection_name, Card.created_at)).all()
        counts = dict(db.execute(select(OwnedCard.card_id, func.count(OwnedCard.id)).group_by(OwnedCard.card_id)).all())
        reserved = dict(db.execute(select(ReservedCard.card_id, func.count(ReservedCard.id)).join(InventoryPack, InventoryPack.id == ReservedCard.pack_id).where(InventoryPack.opened_at.is_(None)).group_by(ReservedCard.card_id)).all())
        return [{'id': r[0], 'name': r[1], 'rarity': r[2], 'image_url': r[3],
                 'collection': r[4] or 'Recanto Original', 'created_at': naive_to_utc(r[5]).isoformat() if r[5] else None,
                 'max_copies': TIERS.get(r[2], 1), 'minted': counts.get(r[0], 0),
                 'reserved': reserved.get(r[0], 0),
                 'remaining': max(0, TIERS.get(r[2], 1) - counts.get(r[0], 0) - reserved.get(r[0], 0))} for r in rows]

    def random_card(pool, weight_key):
        eligible = [c for c in pool if c['remaining'] > 0]
        if not eligible:
            raise HTTPException(409, detail='Todos os cards se esgotaram; cadastre novos no painel de gestão.')
        tiers = sorted({x['rarity'] for x in eligible})
        weighted = [max(0, WEIGHTS[weight_key].get(t, 0)) for t in tiers]
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
                obj.last_tick_at = then + timedelta(hours=hours)
            threshold = timedelta(hours=setting(db, 'neglect_hours'))
            last = naive_to_utc(obj.last_action_at)
            if now - last >= threshold:
                obj.status = 'vet'
                obj.vet_since = last + threshold
        if obj.status == 'vet':
            deadline = naive_to_utc(obj.vet_since) + timedelta(days=setting(db, 'vet_dead_days'))
            if now >= deadline:
                obj.status = 'morto'

    def pet_dict(db, obj):
        if obj is None:
            return None
        sp = db.get(PetSpecies, obj.species_id)
        nextfeed = (naive_to_utc(obj.last_feed_at) + timedelta(minutes=15)).isoformat() if obj.last_feed_at else None
        nextpet = (naive_to_utc(obj.last_pet_at) + timedelta(minutes=5)).isoformat() if obj.last_pet_at else None
        deadline = (naive_to_utc(obj.vet_since) + timedelta(days=setting(db, 'vet_dead_days'))).isoformat() if obj.vet_since and obj.status == 'vet' else None
        return {'species_id': sp.id, 'name': sp.name, 'emoji': sp.emoji, 'image_url': sp.image_url, **model_fields(sp),
                'status': obj.status, 'food': obj.food, 'happiness': obj.happiness,
                'rescue_cost': setting(db, 'vet_cost'), 'vet_deadline': deadline,
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

    @app.get('/api/game/config')
    def game_config(request: Request):
        uid = me(request)
        with SessionLocal() as db:
            cfg = {x.key: x.value for x in db.scalars(select(GameSetting)).all()}
            return {'rules': cfg, 'chances': WEIGHTS, 'max_copies': TIERS,
                    'reset_timezone': TIMEZONE_NAME, 'admin': is_admin(uid, request),
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
                    'card_rewards': {tier:card_bonus(db,tier) for tier in TIERS}}

    @app.post('/api/daily/coins')
    def daily_coins(request: Request):
        uid = me(request)
        with writing() as db:
            record_claim(db, uid, 'coins')
            gain = setting(db, 'daily_coins')
            wallet(db, uid).coins += gain
            progress(db, uid, 'daily_coins')
        return {'ok': True, 'coins_gained': gain}

    @app.post('/api/daily/card')
    def daily_card(request: Request):
        uid = me(request)
        with writing() as db:
            at=next_card_available(db,uid)
            if at and at>utcnow():
                raise HTTPException(409, detail='Aguarde 5 horas entre resgates de cartas.')
            chosen = random_card(stock(db), 'diario')
            result = grant_card(db, uid, chosen)
            reward=card_bonus(db, result['rarity'])
            wallet(db, uid).coins += reward
            cooldown=db.get(CardCooldown,uid)
            if cooldown: cooldown.last_claimed=utcnow()
            else: db.add(CardCooldown(user_id=uid,last_claimed=utcnow()))
            progress(db, uid, 'daily_card')
            result['bonus_coins'] = reward
        return {'ok': True, 'card': result}

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
                    {'owned_id': x[0], 'name': x[1], 'rarity': x[2], 'image_url': x[3]} for x in holdings]})
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
                for who in (offer.buyer_id,offer.seller_id):progress(db,who,'trade');achievement_event(db,who,'trade')
            else:
                wallet(db,offer.buyer_id).coins+=offer.amount
                offer.status='cancelada' if action=='cancel' else ('recusada' if action=='reject' else 'expirada')
            return {'ok':True,'status':offer.status}

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

    @app.get('/api/assets')
    def ui_assets(request: Request):
        # Imagens publicas para permitir logo/fundo personalizados antes do login.
        # Apenas admin pode modificar os dados.
        with SessionLocal() as db:
            return {'items': [{'key':a.key, 'selector':a.selector,
                               'mode':a.mode, 'image_url':a.image_url}
                              for a in db.scalars(select(UIAsset)).all()]}

    @app.post('/api/admin/assets')
    async def update_ui_asset(request: Request):
        only_admin(request)
        data=json_body(await request.json(),('key','selector','mode','image_url'))
        key=str(data['key']).strip()
        selector=str(data['selector']).strip()
        mode=str(data['mode']).strip()
        if not re.fullmatch(r'(?:game:[a-z0-9_-]{1,40}|[a-z0-9][a-z0-9_-]{0,62})',key):
            raise HTTPException(422,detail='Chave do asset invalida')
        if key.startswith('game:') and key[5:] not in {g[0] for g in GAMES}:
            raise HTTPException(422,detail='Jogo nao encontrado')
        # Seletores sao apenas alvos visuais; rejeita caracteres CSS usados em
        # valores/scripts ou em combinacoes de pseudo-classes perigosas.
        if (len(selector)>180 or '\n' in selector or '\r' in selector or
            any(mark in selector for mark in ('{','}',';','\\','/*','*/'))):
            raise HTTPException(422,detail='Seletor CSS nao permitido')
        if mode not in ('image','icon','background'):
            raise HTTPException(422,detail='Modo desconhecido')
        if key.startswith('game:'):
            selector=''
            mode='icon'
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
        with SessionLocal() as db:return {'catalog':[game_entry(db,row) for row in GAMES], 'selected':user_games(db,uid),'max':5}

    @app.post('/api/games/preferences')
    async def save_game_preferences(request:Request):
        uid=me(request);data=json_body(await request.json(),('games',))
        chosen=data['games'];options={k for k,_,_ in GAMES}
        if not isinstance(chosen,list) or len(chosen)>5 or len(set(map(str,chosen)))!=len(chosen) or any(x not in options for x in chosen):
            raise HTTPException(422,detail='Selecione até 5 jogos diferentes da lista')
        with writing() as db:
            db.execute(delete(FavoriteGame).where(FavoriteGame.user_id==uid))
            for order,game in enumerate(chosen):db.add(FavoriteGame(user_id=uid,game_id=game,position=order))
        return {'ok':True}

    @app.get('/api/shop')
    def shop(request: Request):
        me(request)
        with SessionLocal() as db:
            products = [
                {'sku': 'pack3', 'name': 'Pacote com 3 cards', 'price': setting(db, 'pack3_cost'), 'amount': 3,
                 'rates': WEIGHTS['pack3'], 'kind': 'cards'},
                {'sku': 'pack5', 'name': 'Pacote com 5 cards', 'price': setting(db, 'pack5_cost'), 'amount': 5,
                 'rates': WEIGHTS['pack5'], 'kind': 'cards'},
                {'sku': 'treat3', 'name': '3 Biscoitos', 'price': setting(db, 'treat_bundle_cost'),
                 'amount': 3, 'kind': 'treats','food':15,'treat_sku':'biscoito'},
                {'sku': 'fruit', 'name': 'Frutinha', 'price':setting(db,'treat_fruit_cost'), 'amount':1,'kind':'treats','food':30,'treat_sku':'fruta'},
                {'sku': 'feast', 'name':'Banquete', 'price':setting(db,'treat_feast_cost'), 'amount':1,'kind':'treats','food':55,'treat_sku':'banquete'},
            ]
            covers = {c.sku:c.image_url for c in db.scalars(select(ProductCover)).all()}
            for item in products:
                item['image_url'] = covers.get(item['sku'])
                item['emoji'] = SHOP_EMOJI[item['sku']]
            return {'products': products}

    @app.post('/api/shop/purchase')
    async def purchase(request: Request):
        uid = me(request)
        data = json_body(await request.json(), ('sku',))
        sku = str(data['sku'])
        if sku not in ('pack3', 'pack5', 'treat3', 'fruit', 'feast'):
            raise HTTPException(422, detail='Produto desconhecido')
        with writing() as db:
            w = wallet(db, uid)
            if sku in ('treat3', 'fruit', 'feast'):
                foodsku,qty,key = {'treat3':('biscoito',3,'treat_bundle_cost'),
                                   'fruit':('fruta',1,'treat_fruit_cost'),
                                   'feast':('banquete',1,'treat_feast_cost')}[sku]
                cost = setting(db, key)
                require_coins(db, uid, cost)
                w.coins -= cost
                give_treat(db, uid, foodsku, qty)
                result = {'ok':True, 'treats_gained':qty, 'item':foodsku, 'spent':cost}
            else:
                qty = 3 if sku=='pack3' else 5
                cost = setting(db, sku+'_cost')
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
                    'treats':[{'sku':t.sku,'quantity':t.quantity,**TREAT_TYPES[t.sku]} for t in treats if t.sku in TREAT_TYPES]}

    @app.post('/api/inventory/packs/{pack_id}/open')
    def open_pack(pack_id: int, request: Request):
        uid=me(request)
        with writing() as db:
            pack=db.get(InventoryPack,pack_id)
            if not pack or pack.user_id!=uid: raise HTTPException(404, detail='Pacote não encontrado')
            if pack.opened_at is not None: raise HTTPException(409,detail='Pacote já aberto')
            reserved=db.scalars(select(ReservedCard).where(ReservedCard.pack_id==pack_id).order_by(ReservedCard.position)).all()
            if len(reserved)!=(3 if pack.sku=='pack3' else 5): raise HTTPException(409, detail='Pacote incompleto')
            result=[]
            for r in reserved:
                card=db.get(Card,r.card_id)
                if not card: raise HTTPException(409, detail='Card indisponível')
                result.append(grant_card(db,uid,{'id':card.id,'name':card.name,'rarity':card.rarity,'image_url':card.image_url,'collection':card.collection_name}))
            pack.opened_at=utcnow()
            bonus=sum(card_bonus(db,card['rarity']) for card in result)
            for card in result:
                card['bonus_coins']=card_bonus(db,card['rarity'])
            wallet(db,uid).coins+=bonus
            progress(db,uid,'pack')
        return {'ok':True,'cards':result,'bonus_coins':bonus}

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
            if owned_id is None:
                if fav: db.delete(fav)
            elif fav: fav.owned_id=owned_id
            else: db.add(FavoriteCard(user_id=uid,owned_id=owned_id))
        return {'ok':True,'owned_id':owned_id}

    @app.get('/api/community/profiles')
    def community_profiles(request: Request, q: str=''):
        uid=me(request)
        q=q.strip()[:80]
        with SessionLocal() as db:
            users=db.scalars(select(User).where(User.id != uid,User.username.ilike('%'+q.replace('%', r'\%').replace('_', r'\_')+'%')).order_by(User.username).limit(60)).all()
            return {'members':[{'key':u.id,'name':u.username,'avatar_url':u.avatar_url,
                                 'card_count':db.scalar(select(func.count(OwnedCard.id)).where(OwnedCard.user_id==u.id)) or 0} for u in users]}

    @app.get('/api/community/profiles/{member_id}')
    def public_profile(member_id: str, request: Request):
        me(request)
        with writing() as db:
            user=db.get(User,member_id)
            if not user or member_id.startswith('teste_'): raise HTTPException(404,detail='Membro não encontrado')
            obj=db.get(UserPet,member_id)
            pet_tick(db,obj)
            badges=db.execute(select(Achievement.title,Achievement.icon,Achievement.image_url).join(UserAchievement,UserAchievement.achievement_id==Achievement.id).where(UserAchievement.user_id==member_id)).all()
            count=db.scalar(select(func.count(OwnedCard.id)).where(OwnedCard.user_id==member_id)) or 0
            return {'key':user.id,'name':user.username,'avatar_url':user.avatar_url,'cards':count,
                    'badges':[{'title':x[0],'icon':x[1],'image_url':x[2]} for x in badges],
                    'favorite':favorite_info(db,member_id),
                    'pet':pet_dict(db,obj), 'favorite_games':user_games(db,member_id)}

    @app.post('/api/pets/visit/{owner_id}')
    async def visit_pet(owner_id: str,request: Request):
        visitor=me(request)
        payload=json_body(await request.json(),('action',))
        action=str(payload['action'])
        sku=str(payload.get('treat_sku','biscoito'))
        if action not in ('pet','feed'): raise HTTPException(422,detail='Interação inválida')
        if owner_id==visitor: raise HTTPException(422,detail='Use sua própria aba Pet')
        with writing() as db:
            if not db.get(User,owner_id): raise HTTPException(404,detail='Membro não encontrado')
            obj=db.get(UserPet,owner_id)
            pet_tick(db,obj)
            if obj is None or obj.status!='ativo': raise HTTPException(409,detail='Este pet não está disponível')
            key=(visitor,owner_id,local_day(),action)
            if db.get(VisitorCare,key): raise HTTPException(409,detail='Você já realizou essa interação hoje com este pet')
            if action=='feed':
                consume_treat(db,visitor,sku)
                obj.food=min(100,obj.food+TREAT_TYPES[sku]['food'])
            else:
                obj.happiness=min(100,obj.happiness+15)
            obj.last_action_at=utcnow()
            db.add(VisitorCare(visitor_id=visitor,owner_id=owner_id,day=local_day(),action=action))
            gain=setting(db,'visit_pet_reward' if action=='pet' else 'visit_feed_reward')
            owner_gain=setting(db,'visit_owner_reward')
            wallet(db,visitor).coins+=gain
            wallet(db,owner_id).coins+=owner_gain
            progress(db,visitor,'pet' if action=='pet' else 'feed')
            achievement_event(db,visitor,'pet' if action=='pet' else 'feed')
            result=pet_dict(db,obj)
        return {'ok':True,'visitor_coins':gain,'owner_coins':owner_gain,'pet':result}

    @app.post('/api/inventory/gift')
    async def gift_treat(request: Request):
        uid=me(request)
        data=json_body(await request.json(),('to_user','sku','quantity'))
        to_user=str(data['to_user']);sku=str(data['sku']);qty=integer(data['quantity'])
        if sku not in TREAT_TYPES or qty<1 or qty>100: raise HTTPException(422,detail='Petisco ou quantidade inválida')
        if to_user==uid: raise HTTPException(422,detail='Você não pode presentear a si mesmo')
        with writing() as db:
            if not db.get(User,to_user): raise HTTPException(404,detail='Destinatário não encontrado')
            give_treat(db,uid,sku,-qty)
            give_treat(db,to_user,sku,qty)
        return {'ok':True,'quantity':qty,'sku':sku}

    @app.get('/api/pets')
    def pets(request: Request):
        uid = me(request)
        with writing() as db:
            obj = db.get(UserPet, uid)
            pet_tick(db, obj)
            types = db.scalars(select(PetSpecies).order_by(PetSpecies.id)).all()
            return {'pet': pet_dict(db, obj), 'species': [
                {'id': s.id, 'name': s.name, 'emoji': s.emoji, 'image_url': s.image_url, **model_fields(s)} for s in types],
                    'treats': wallet(db, uid).treats,
                    'expedition':({'mission':mission.mission,'name':EXPEDITIONS[mission.mission]['name'],
                       'ends_at':naive_to_utc(mission.ends_at).isoformat(),'ready':utcnow()>=naive_to_utc(mission.ends_at)}
                       if (mission:=db.get(PetExpedition,uid)) else None),
                    'expedition_options':[{'id':k,**v} for k,v in EXPEDITIONS.items()]}

    @app.post('/api/pets/expedition/start')
    async def start_expedition(request:Request):
        uid=me(request);data=json_body(await request.json(),('mission',));key=str(data['mission'])
        if key not in EXPEDITIONS:raise HTTPException(422,detail='Missão desconhecida')
        info=EXPEDITIONS[key]
        with writing() as db:
            obj=db.get(UserPet,uid)
            if not obj:raise HTTPException(409,detail='Adote uma Pequena Lenda antes')
            pet_tick(db,obj)
            if obj.status!='ativo':raise HTTPException(409,detail='Seu pet está indisponível')
            if obj.food<info['food']+15:raise HTTPException(409,detail='Alimente o pet antes de enviá-lo à missão')
            if db.get(PetExpedition,uid):raise HTTPException(409,detail='Já existe uma expedição pendente')
            now=utcnow();obj.status='missao';obj.last_tick_at=now;obj.last_action_at=now
            coins=RANDOM.randint(*info['coins'])
            card_award=RANDOM.randrange(100)<info['card_chance']
            db.add(PetExpedition(user_id=uid,mission=key,started_at=now,
                       ends_at=now+timedelta(minutes=info['minutes']),coins=coins,card_award=card_award))
        return {'ok':True,'ends_at':(now+timedelta(minutes=info['minutes'])).isoformat()}

    @app.post('/api/pets/expedition/collect')
    def collect_expedition(request:Request):
        uid=me(request)
        with writing() as db:
            row=db.get(PetExpedition,uid);obj=db.get(UserPet,uid)
            if not row or not obj or obj.status!='missao':raise HTTPException(409,detail='Nenhuma expedição em andamento')
            if utcnow()<naive_to_utc(row.ends_at):raise HTTPException(409,detail='Seu pet ainda está em missão')
            info=EXPEDITIONS[row.mission]
            obj.food=max(0,obj.food-info['food']);obj.happiness=max(0,obj.happiness-6)
            obj.status='ativo';obj.last_tick_at=utcnow();obj.last_action_at=utcnow()
            earned=row.coins;wallet(db,uid).coins+=earned
            granted=None
            if row.card_award:
                pool=stock(db)
                if any(c['remaining']>0 for c in pool):
                    chosen=random_card(pool,'expedition');granted=grant_card(db,uid,chosen)
                    wallet(db,uid).coins+=card_bonus(db,granted['rarity'])
            db.delete(row)
        return {'ok':True,'coins_gained':earned,'card':granted}

    @app.post('/api/pets/adopt')
    async def adopt(request: Request):
        uid = me(request)
        data = json_body(await request.json(), ('species_id',))
        sid = integer(data['species_id'])
        with writing() as db:
            specie = db.get(PetSpecies, sid)
            if not specie:
                raise HTTPException(404, detail='Pet indisponível para adoção')
            pet = db.get(UserPet, uid)
            if pet:
                pet_tick(db, pet)
                if pet.status != 'morto':
                    raise HTTPException(409, detail='Cada jogador pode ter apenas um pet')
                db.delete(pet)
                db.flush()
            db.add(UserPet(user_id=uid, species_id=sid, status='ativo',
                           food=85, happiness=85, adopted_at=utcnow(),
                           last_action_at=utcnow(), last_tick_at=utcnow()))
            progress(db, uid, 'adopt')
            achievement_event(db, uid, 'adopt')
        return {'ok': True, 'message': f'{specie.name} foi adotado!'}

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
                raise HTTPException(409, detail='Adote um pet primeiro')
            pet_tick(db, obj)
            if obj.status != 'ativo':
                raise HTTPException(409, detail='Seu pet não está disponível para cuidados')
            now = utcnow()
            if action == 'feed':
                if obj.last_feed_at and now < naive_to_utc(obj.last_feed_at) + timedelta(minutes=15):
                    raise HTTPException(409, detail='Aguarde 15 minutos antes de alimentar novamente')
                sku = str(data.get('treat_sku', 'biscoito'))
                consume_treat(db, uid, sku)
                obj.food = min(100, obj.food + TREAT_TYPES[sku]['food'])
                obj.last_feed_at = now
            else:
                if obj.last_pet_at and now < naive_to_utc(obj.last_pet_at) + timedelta(minutes=5):
                    raise HTTPException(409, detail='Aguarde 5 minutos antes de acariciar novamente')
                obj.happiness = min(100, obj.happiness + 25)
                obj.last_pet_at = now
            obj.last_action_at = now
            progress(db, uid, action)
            achievement_event(db, uid, action)
            result = pet_dict(db, obj)
        return {'ok': True, 'pet': result}

    @app.post('/api/pets/rescue')
    def rescue(request: Request):
        uid = me(request)
        with writing() as db:
            obj = db.get(UserPet, uid)
            if not obj:
                raise HTTPException(409, detail='Nenhum pet encontrado')
            pet_tick(db, obj)
            if obj.status != 'vet':
                raise HTTPException(409, detail='Este pet não está aguardando resgate no veterinário')
            price = setting(db, 'vet_cost')
            require_coins(db, uid, price).coins -= price
            obj.status = 'ativo'
            obj.vet_since = None
            obj.food = 70
            obj.happiness = 65
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
            wallet(db, uid).coins += definitions[code][3]
            achievement_event(db, uid, 'mission')
        return {'ok': True, 'coins_gained': definitions[code][3]}

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
        if key not in DEFAULTS or not 0 <= value <= 100000:
            raise HTTPException(422, detail='Configuração inválida')
        if key.startswith('card_bonus_') and not 1 <= value <= 5:
            raise HTTPException(422, detail='Recompensas por raridade devem ficar entre 1 e 5 moedas')
        if key in ('neglect_hours', 'vet_dead_days') and value < 1:
            raise HTTPException(422, detail='O prazo deve ser no mínimo 1')
        with writing() as db:
            db.get(GameSetting, key).value = value
        return {'ok': True, 'key': key, 'value': value}

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
            card = Card(name=name, rarity=rarity, image_url=picture, collection_name=collection)
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
                raise HTTPException(409, detail='Este pet já existe')
            obj = PetSpecies(name=name, emoji=emo or '🐾', image_url=picture,
                             model_url=model, **animations)
            db.add(obj)
            db.flush()
            sid = obj.id
        return {'ok': True, 'id': sid}

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
        valid_shop = {'pack3', 'pack5', 'treat3', 'fruit', 'feast'}
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
        if os.getenv('APP_ENV','development').strip().lower() != 'development':
            raise HTTPException(403, detail='Upload de modelos apenas para testes locais')
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
        folder = frontend / 'models' / uuid.uuid4().hex
        folder.mkdir(parents=True, exist_ok=False)
        for name, contents in gathered.items():
            (folder / name).write_bytes(contents)
        return {'ok':True, 'model_url':f'/models/{folder.name}/{primary}', 'files':len(gathered)}

    @app.get('/models/{folder}/{filename}')
    def view_model(folder: str, filename: str):
        if not re.fullmatch(r'[0-9a-f]{32}', folder) or not re.fullmatch(r'[A-Za-z0-9_+(). -]{1,100}',filename) or '..' in filename:
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
        if event not in {'trade', 'card', 'adopt', 'pet', 'feed', 'mission', 'voice_minutes'}:
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
            if event != 'voice_minutes':
                for row in db.scalars(select(AchievementProgress).where(
                    AchievementProgress.event == event, AchievementProgress.counter >= target)).all():
                    db.add(UserAchievement(user_id=row.user_id, achievement_id=new_id, unlocked_at=utcnow()))
        return {'ok': True, 'id': new_id, 'available': event != 'voice_minutes'}

    @app.post('/api/admin/upload')
    async def upload_card_art(request: Request, image: UploadFile = File(...)):
        only_admin(request)
        if image.content_type not in ('image/png', 'image/jpeg', 'image/webp'):
            raise HTTPException(422, detail='Use PNG, JPG ou WEBP')
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
        if fmt not in ('PNG', 'JPEG', 'WEBP'):
            raise HTTPException(422, detail='Formato de imagem não permitido')
        ext = {'PNG': 'png', 'JPEG': 'jpg', 'WEBP': 'webp'}[fmt]
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
                        files={'file': (f'arte.{ext}', data, image.content_type)},
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

    @app.get('/uploads/{filename}')
    def view_art(filename: str):
        if not filename or '/' in filename or '\\' in filename or len(filename) > 90:
            raise HTTPException(404, detail='Imagem não encontrada')
        path = frontend / 'uploads' / filename
        if not path.is_file():
            raise HTTPException(404, detail='Imagem não encontrada')
        return FileResponse(path, headers={'Cache-Control': 'public, max-age=3600'})

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
                raise HTTPException(409, detail='Primeiro adote um pet')
            if stage == 'vet':
                if obj.status != 'ativo':
                    raise HTTPException(409, detail='Pet não está ativo')
                obj.last_action_at = utcnow() - timedelta(hours=setting(db, 'neglect_hours') + 1)
                obj.last_tick_at = obj.last_action_at
            if stage == 'death':
                if obj.status != 'vet':
                    raise HTTPException(409, detail='Primeiro envie o pet ao veterinário')
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
            for table in (VisitorCare, FavoriteCard, ReservedCard, InventoryPack, InventoryTreat,
                          CoinOffer, CardCooldown, PetExpedition, FavoriteGame, TradeReward, Trade, MissionProgress, Claim, UserAchievement,
                          AchievementProgress, UserPet, OwnedCard):
                db.execute(delete(table))
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
