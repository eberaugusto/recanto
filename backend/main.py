"""Recanto v0.8 — mobile PWA, login Discord OAuth2, perfis e coleção.

Python 3.12. Acesso Discord usa Authorization Code + PKCE e cookie de sessão
opaco; nunca entrega o Client Secret nem os tokens do Discord ao navegador.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT.parent / 'frontend'
load_dotenv(ROOT / '.env')
APP_ENV = os.getenv('APP_ENV', 'development').strip().lower()
CLIENT_ID = os.getenv('DISCORD_CLIENT_ID', '').strip()
CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET', '').strip()
REDIRECT_URI = os.getenv('DISCORD_REDIRECT_URI', 'http://localhost:5173/auth/discord/callback').strip()
REQUIRED_GUILD_ID = os.getenv('REQUIRED_DISCORD_GUILD_ID', '').strip()
DEMO_ENABLED = False  # v0.8: sem contas ficticias; acesso somente por OAuth2 Discord
COOKIE_SECURE = APP_ENV == 'production' or os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
SESSION_DAYS = 30
COOKIE_NAME = 'recanto_session'
API = 'https://discord.com/api/v10'

if APP_ENV not in {'development', 'production'}:
    raise RuntimeError('APP_ENV deve ser development ou production')
if APP_ENV == 'production':
    if not (CLIENT_ID and CLIENT_SECRET and REDIRECT_URI.startswith('https://')):
        raise RuntimeError('Producao exige Discord Client ID, Client Secret e Redirect URI HTTPS')
    if not os.getenv('DATABASE_URL', '').strip():
        raise RuntimeError('Producao exige DATABASE_URL (PostgreSQL persistente)')
# Render fornece HTTPS externamente, mas o proxy fala HTTP com uvicorn.
# PUBLIC_BASE_URL evita rejeitar requisições legitimas por diferenca http/https.
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', '').strip().rstrip('/')
if APP_ENV == 'production' and (not PUBLIC_BASE_URL.startswith('https://') or PUBLIC_BASE_URL.count('/') != 2):
    raise RuntimeError('Producao exige PUBLIC_BASE_URL como https://seuapp.onrender.com')

# Por padrao, o banco fica na pasta backend, independente de onde o BAT e aberto.
DATABASE_URL = os.getenv('DATABASE_URL', '').strip() or f'sqlite:///{(ROOT / "recanto.db").as_posix()}'
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = 'postgresql+psycopg://' + DATABASE_URL[len('postgres://'):]
elif DATABASE_URL.startswith('postgresql://'):
    DATABASE_URL = 'postgresql+psycopg://' + DATABASE_URL[len('postgresql://'):]
if APP_ENV == 'production' and not DATABASE_URL.startswith('postgresql+psycopg://'):
    raise RuntimeError('Em producao use um banco PostgreSQL (Neon); SQLite perderia dados no Render')
engine = create_engine(DATABASE_URL,
    connect_args={'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {},
    pool_pre_ping=True, pool_recycle=180)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    username: Mapped[str] = mapped_column(String(120), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    wallet: Mapped['Wallet'] = relationship(back_populates='user', uselist=False, cascade='all, delete-orphan')


class Wallet(Base):
    __tablename__ = 'wallets'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    coins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    treats: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    user: Mapped[User] = relationship(back_populates='wallet')


class Card(Base):
    __tablename__ = 'cards'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    rarity: Mapped[str] = mapped_column(String(40), default='comum', nullable=False)
    collection_name: Mapped[str] = mapped_column(String(100), default='Recanto Original', nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=True)


class OwnedCard(Base):
    __tablename__ = 'owned_cards'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False, index=True)
    card_id: Mapped[int] = mapped_column(ForeignKey('cards.id'), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class NotificationPreference(Base):
    __tablename__ = 'notification_preferences'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Session(Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OAuthAttempt(Base):
    __tablename__ = 'oauth_attempts'
    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Base.metadata.create_all(engine)
app = FastAPI(title='Recanto API', version='1.2.0', docs_url=None, redoc_url=None, openapi_url=None)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def naive_to_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def sha(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def cookie(response, name: str, value: str, lifetime: int) -> None:
    response.set_cookie(name, value, httponly=True, secure=COOKIE_SECURE,
                        samesite='lax', max_age=lifetime, path='/')


def clear_oauth_cookies(response) -> None:
    response.delete_cookie('recanto_oauth_state', path='/', secure=COOKIE_SECURE, samesite='lax')
    response.delete_cookie('recanto_oauth_verifier', path='/', secure=COOKIE_SECURE, samesite='lax')


def redirect_error(error: str) -> RedirectResponse:
    response = RedirectResponse('/?login_error=' + error, status_code=303)
    clear_oauth_cookies(response)
    return response


def auth_configured() -> bool:
    return bool(CLIENT_ID and CLIENT_SECRET)


def dev_request(request: Request) -> bool:
    # Verificacao pelo cliente visto pelo servidor; nao confiar em X-Forwarded-For.
    # Em produção a modalidade demo sempre está desativada.
    host = request.client.host if request.client else ''
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback
    except ValueError:
        return host == 'localhost'


def current_user_id(request: Request) -> str | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    with SessionLocal() as db:
        sess = db.get(Session, sha(token))
        if sess is None:
            return None
        if naive_to_utc(sess.expires_at) <= utcnow():
            db.delete(sess)
            db.commit()
            return None
        if sess.user_id.startswith('teste_') and not (DEMO_ENABLED and dev_request(request)):
            return None
        return sess.user_id


def issue_session(user_id: str):
    # Rotaciona o token apos login para evitar session fixation.
    token = secrets.token_urlsafe(32)
    with SessionLocal.begin() as db:
        db.add(Session(token_hash=sha(token), user_id=user_id,
                       expires_at=utcnow() + timedelta(days=SESSION_DAYS)))
    response = RedirectResponse('/', status_code=303)
    cookie(response, COOKIE_NAME, token, SESSION_DAYS * 86400)
    clear_oauth_cookies(response)
    return response


@app.middleware('http')
async def safety_headers(request: Request, call_next):
    # Bloqueia operações cross-site comuns, inclusive logout e login demo.
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        origin = request.headers.get('origin')
        if origin:
            from urllib.parse import urlsplit
            base = urlsplit(PUBLIC_BASE_URL or str(request.base_url))
            src = urlsplit(origin)
            if (src.scheme, src.netloc) != (base.scheme, base.netloc):
                return JSONResponse({'detail': 'Origem nao autorizada'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['X-Frame-Options'] = 'DENY'
    if request.url.path.startswith('/api/') or request.url.path.startswith('/auth/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/health')
def health():
    return {'status': 'ok', 'version': '1.2.0'}


@app.get('/api/config')
def public_config(request: Request):
    return {'demo_enabled': DEMO_ENABLED and dev_request(request),
            'discord_configured': auth_configured(),
            'login_required_guild': bool(REQUIRED_GUILD_ID),
            'version': '1.2.0'}


@app.get('/api/me')
def me(request: Request, response: Response):
    uid = current_user_id(request)
    if uid is None:
        return {'authenticated': False}
    # Renovação deslizante com validação no servidor. Mantém a conta logada
    # após reabrir o PWA, sem expor tokens ao JavaScript.
    token = request.cookies.get(COOKIE_NAME)
    if token:
        with SessionLocal.begin() as authdb:
            active = authdb.get(Session, sha(token))
            if active and naive_to_utc(active.expires_at) < utcnow() + timedelta(days=7):
                active.expires_at = utcnow() + timedelta(days=SESSION_DAYS)
                cookie(response, COOKIE_NAME, token, SESSION_DAYS * 86400)
    with SessionLocal() as db:
        user = db.get(User, uid)
        if user is None:
            return {'authenticated': False}
        count = db.scalar(select(func.count(OwnedCard.id)).where(OwnedCard.user_id == uid)) or 0
        recent = db.execute(
            select(Card.name, Card.image_url, Card.rarity, Card.id)
            .join(OwnedCard, OwnedCard.card_id == Card.id)
            .where(OwnedCard.user_id == uid)
            .order_by(OwnedCard.acquired_at.desc(), OwnedCard.id.desc()).limit(1)
        ).first()
        return {'authenticated': True, 'demo': False, 'name': user.username,
                'avatar_url': user.avatar_url,
                'coins': user.wallet.coins if user.wallet else 0,
                'cards': count, 'treats': user.wallet.treats if user.wallet else 0,
                'last_card': {'name': recent[0], 'image_url': recent[1], 'rarity': recent[2], 'card_id': recent[3]} if recent else None}


@app.get('/api/cards')
def cards(request: Request):
    """Coleção real somente do usuário conectado (duplicatas incluídas)."""
    uid = current_user_id(request)
    if uid is None:
        raise HTTPException(status_code=401, detail='Entre na sua conta primeiro')
    with SessionLocal() as db:
        owned = db.execute(
            select(OwnedCard.id, Card.id, Card.name, Card.rarity, Card.image_url, OwnedCard.acquired_at, Card.collection_name)
            .join(Card, OwnedCard.card_id == Card.id).where(OwnedCard.user_id == uid)
            .order_by(OwnedCard.acquired_at.desc(), OwnedCard.id.desc()).limit(200)
        ).all()
        total = db.scalar(select(func.count(OwnedCard.id)).where(OwnedCard.user_id == uid)) or 0
        return {'total': total, 'items': [
            {'owned_id': x[0], 'card_id': x[1], 'name': x[2], 'rarity': x[3],
             'image_url': x[4], 'acquired_at': x[5].isoformat() if x[5] else None,
             'collection': x[6] or 'Recanto Original'}
            for x in owned
        ]}




@app.get('/api/notifications/preferences')
def notification_preferences(request: Request):
    uid = current_user_id(request)
    if uid is None:
        raise HTTPException(status_code=401, detail='Entre na sua conta primeiro')
    with SessionLocal() as db:
        pref = db.get(NotificationPreference, uid)
        return {'enabled': bool(pref and pref.enabled), 'demo': uid.startswith('teste_')}


@app.post('/api/notifications/preferences')
async def set_notification_preferences(request: Request):
    uid = current_user_id(request)
    if uid is None:
        raise HTTPException(status_code=401, detail='Entre na sua conta primeiro')
    try:
        body = await request.json()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail='JSON invalido')
    if not isinstance(body, dict) or type(body.get('enabled')) is not bool:
        raise HTTPException(status_code=422, detail='enabled deve ser booleano')
    enabled = body['enabled']
    with SessionLocal.begin() as db:
        pref = db.get(NotificationPreference, uid)
        if pref is None:
            db.add(NotificationPreference(user_id=uid, enabled=enabled))
        else:
            pref.enabled = enabled
    return {'enabled': enabled, 'demo': uid.startswith('teste_')}


@app.get('/auth/discord/start')
def discord_start():
    if not auth_configured():
        return redirect_error('discord_not_configured')
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('utf-8')).digest()).decode('ascii').rstrip('=')
    with SessionLocal.begin() as db:
        db.add(OAuthAttempt(state_hash=sha(state), expires_at=utcnow() + timedelta(minutes=10)))
    params = {
        'response_type': 'code', 'client_id': CLIENT_ID,
        'scope': 'identify guilds' if REQUIRED_GUILD_ID else 'identify',
        'redirect_uri': REDIRECT_URI, 'state': state,
        'code_challenge': challenge, 'code_challenge_method': 'S256',
    }
    response = RedirectResponse('https://discord.com/oauth2/authorize?' + urlencode(params), status_code=302)
    cookie(response, 'recanto_oauth_state', state, 600)
    cookie(response, 'recanto_oauth_verifier', verifier, 600)
    return response


@app.get('/auth/discord/callback')
async def discord_callback(request: Request, code: str | None = None, state: str | None = None,
                           iss: str | None = None, error: str | None = None):
    if error is not None:
        return redirect_error('discord_denied')
    if iss is not None and iss != 'https://discord.com':
        return redirect_error('invalid_state')
    cookie_state = request.cookies.get('recanto_oauth_state')
    verifier = request.cookies.get('recanto_oauth_verifier')
    if not code or not state or not cookie_state or not verifier or not secrets.compare_digest(state, cookie_state):
        return redirect_error('invalid_state')
    # State de uso unico: consome ANTES da chamada externa ao Discord.
    with SessionLocal.begin() as db:
        attempt = db.get(OAuthAttempt, sha(state))
        if attempt is None or naive_to_utc(attempt.expires_at) < utcnow():
            return redirect_error('invalid_state')
        db.delete(attempt)
    if not auth_configured():
        return redirect_error('discord_not_configured')
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_reply = await client.post(API + '/oauth2/token', data={
                'grant_type': 'authorization_code', 'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET, 'code': code,
                'redirect_uri': REDIRECT_URI, 'code_verifier': verifier,
            }, headers={'Content-Type': 'application/x-www-form-urlencoded'})
            token_reply.raise_for_status()
            access_token = token_reply.json()['access_token']
            headers = {'Authorization': f'Bearer {access_token}'}
            profile_reply = await client.get(API + '/users/@me', headers=headers)
            profile_reply.raise_for_status()
            profile = profile_reply.json()
            uid = str(profile['id'])
            if not uid.isdecimal() or len(uid) > 32:
                raise ValueError('Discord ID inválido')
            if REQUIRED_GUILD_ID:
                guilds_reply = await client.get(API + '/users/@me/guilds', headers=headers)
                guilds_reply.raise_for_status()
                if REQUIRED_GUILD_ID not in {str(g['id']) for g in guilds_reply.json()}:
                    return redirect_error('not_a_member')
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return redirect_error('discord_unavailable')
    name = str(profile.get('global_name') or profile.get('username') or 'Membro')[:120]
    avatar_id = profile.get('avatar')
    avatar_url = f'https://cdn.discordapp.com/avatars/{uid}/{avatar_id}.png?size=256' if avatar_id else None
    with SessionLocal.begin() as db:
        user = db.get(User, uid)
        if user:
            user.username = name
            user.avatar_url = avatar_url
            if user.wallet is None:
                user.wallet = Wallet(coins=0, treats=0)
        else:
            db.add(User(id=uid, username=name, avatar_url=avatar_url, wallet=Wallet(coins=0, treats=0)))
    return issue_session(uid)


@app.post('/api/auth/logout')
def logout(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        with SessionLocal.begin() as db:
            sess = db.get(Session, sha(token))
            if sess is not None:
                db.delete(sess)
    response = JSONResponse({'ok': True})
    response.delete_cookie(COOKIE_NAME, path='/', secure=COOKIE_SECURE, samesite='lax')
    return response


app.mount('/icons', StaticFiles(directory=FRONTEND / 'icons'), name='icons')


@app.get('/', include_in_schema=False)
def home():
    return FileResponse(FRONTEND / 'index.html', headers={'Cache-Control': 'no-store'})


@app.get('/app.js', include_in_schema=False)
def javascript():
    return FileResponse(FRONTEND / 'app.js', media_type='application/javascript', headers={'Cache-Control': 'no-store'})


@app.get('/styles.css', include_in_schema=False)
def styles():
    return FileResponse(FRONTEND / 'styles.css', media_type='text/css', headers={'Cache-Control': 'no-store'})


@app.get('/recanto-logo.png', include_in_schema=False)
def logo():
    return FileResponse(FRONTEND / 'recanto-logo.png')


@app.get('/manifest.webmanifest', include_in_schema=False)
def manifest():
    return FileResponse(FRONTEND / 'manifest.webmanifest', media_type='application/manifest+json', headers={'Cache-Control': 'no-cache'})


@app.get('/api/version', include_in_schema=False)
def version():
    return JSONResponse({'version': '1.2.0'}, headers={'Cache-Control': 'no-store'})


@app.get('/favicon.ico', include_in_schema=False)
def favicon():
    return FileResponse(FRONTEND / 'icons' / 'icon-192.png', media_type='image/png')


@app.get('/sw.js', include_in_schema=False)
def worker():
    return FileResponse(FRONTEND / 'sw.js', media_type='application/javascript', headers={'Cache-Control': 'no-store'})


# Sistemas independentes: cards, loja, moedas, trocas, pets e missões.
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from engagement import register_engagement
track_event = register_engagement(app=app, Base=Base, engine=engine, SessionLocal=SessionLocal,
             User=User, Wallet=Wallet, current_user_id=current_user_id, utcnow=utcnow)
from game import register_game
register_game(app=app, Base=Base, engine=engine, SessionLocal=SessionLocal,
              User=User, Wallet=Wallet, Card=Card, OwnedCard=OwnedCard,
              current_user_id=current_user_id, utcnow=utcnow,
              naive_to_utc=naive_to_utc, dev_request=dev_request,
              demo_enabled=DEMO_ENABLED, root=ROOT, frontend=FRONTEND, mission_tracker=track_event)
