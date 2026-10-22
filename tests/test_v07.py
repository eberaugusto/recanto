"""Testes v0.7 isolados por processo: não usam credenciais Discord nem modificam contas reais."""
import importlib
import secrets
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1] / 'backend'

@pytest.fixture
def app_module(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{(tmp_path / "test.db").as_posix()}')
    monkeypatch.setenv('APP_ENV', 'development')
    monkeypatch.setenv('RECANTO_ADMIN_DISCORD_IDS', '249610270069096448')
    monkeypatch.delenv('DISCORD_CLIENT_ID', raising=False)
    monkeypatch.delenv('DISCORD_CLIENT_SECRET', raising=False)
    sys.path.insert(0, str(BACKEND))
    for module in ('main', 'game'):
        sys.modules.pop(module, None)
    main = importlib.import_module('main')
    with main.SessionLocal.begin() as db:
        for uid, name in [('249610270069096448','Conta admin'),('313131313131313131','Amigo')]:
            db.add(main.User(id=uid, username=name, wallet=main.Wallet(coins=5000, treats=0)))
    yield main
    for module in ('main', 'game'):
        sys.modules.pop(module, None)
    sys.path.remove(str(BACKEND))


def client_as(app, uid):
    c = TestClient(app.app, client=('127.0.0.1', 5050))
    token = secrets.token_urlsafe(28)
    with app.SessionLocal.begin() as db:
        db.add(app.Session(token_hash=app.sha(token),user_id=uid,
                           expires_at=app.utcnow()+timedelta(days=1)))
    c.cookies.set(app.COOKIE_NAME,token)
    return c


def test_login_only_discord_and_admin_permissions(app_module):
    app=app_module
    with client_as(app,'249610270069096448') as admin, client_as(app,'313131313131313131') as user:
        assert admin.post('/api/auth/demo',json={'account':'lia'}).status_code==404
        assert admin.get('/api/game/config').json()['admin'] is True
        assert user.get('/api/game/config').json()['admin'] is False
        assert user.post('/api/admin/settings',json={'key':'pack3_cost','value':20}).status_code==403
        assert admin.post('/api/admin/authorized-ids',json={'discord_id':'423456789012345678','action':'add'}).status_code==200
        assert '423456789012345678' in admin.get('/api/admin/authorized-ids').json()['additional']
        assert user.post('/api/admin/authorized-ids',json={'discord_id':'999999999999999999','action':'add'}).status_code==403
        assert admin.post('/api/admin/authorized-ids',json={'discord_id':'249610270069096448','action':'remove'}).status_code==409
        assert admin.post('/api/admin/authorized-ids',json={'discord_id':'423456789012345678','action':'remove'}).status_code==200


def test_buy_pack_inventory_reveal_and_favorite(app_module):
    app=app_module
    with client_as(app,'249610270069096448') as admin:
        a=admin.post('/api/shop/purchase',json={'sku':'pack5'})
        assert a.status_code==200,a.text
        pack_id=a.json()['pack_id']
        assert admin.get('/api/me').json()['cards']==0
        assert admin.get('/api/inventory').json()['packs'][0]['amount']==5
        reserved=admin.get('/api/catalog').json()['items']
        assert sum(x['reserved'] for x in reserved)==5
        cards=admin.post(f'/api/inventory/packs/{pack_id}/open',json={})
        assert cards.status_code==200,cards.text
        assert len(cards.json()['cards'])==5
        assert admin.get('/api/me').json()['cards']==5
        assert admin.post(f'/api/inventory/packs/{pack_id}/open',json={}).status_code==409
        assert admin.get('/api/inventory').json()['packs']==[]
        owned=admin.get('/api/cards').json()['items'][0]['owned_id']
        assert admin.post('/api/cards/favorite',json={'owned_id':owned}).status_code==200
        assert admin.get('/api/cards/favorite').json()['card']['owned_id']==owned
        assert admin.post('/api/cards/favorite',json={'owned_id':999999999}).status_code==403


def test_gifts_visits_cooldowns_and_private_profile(app_module):
    app=app_module
    with client_as(app,'249610270069096448') as admin, client_as(app,'313131313131313131') as friend:
        sp=admin.get('/api/pets').json()['species'][0]['id']
        assert admin.post('/api/pets/adopt',json={'species_id':sp}).status_code==200
        assert friend.post('/api/shop/purchase',json={'sku':'treat3'}).status_code==200
        assert friend.post('/api/shop/purchase',json={'sku':'fruit'}).status_code==200
        public=friend.get('/api/community/profiles/249610270069096448').json()
        assert 'coins' not in public and 'treats' not in public
        assert 'badges' in public and 'pet' in public
        assert friend.post('/api/pets/visit/249610270069096448',json={'action':'pet'}).status_code==200
        assert friend.post('/api/pets/visit/249610270069096448',json={'action':'pet'}).status_code==409
        fed=friend.post('/api/pets/visit/249610270069096448',json={'action':'feed','treat_sku':'fruta'})
        assert fed.status_code==200,fed.text
        assert fed.json()['visitor_coins'] > fed.json()['owner_coins']
        assert friend.post('/api/inventory/gift',json={'to_user':'249610270069096448','sku':'biscoito','quantity':2}).status_code==200
        assert admin.get('/api/inventory').json()['treats'][0]['quantity']==2
        assert friend.post('/api/inventory/gift',json={'to_user':'313131313131313131','sku':'biscoito','quantity':1}).status_code==422


def test_admin_local_reset_removes_progress_and_closed_packs(app_module):
    app=app_module
    with client_as(app,'249610270069096448') as admin, client_as(app,'313131313131313131') as friend:
        assert friend.post('/api/dev/grant-coins',json={'amount':5000}).status_code==403
        assert admin.post('/api/dev/grant-coins',json={'amount':5000}).status_code==200
        assert admin.post('/api/shop/purchase',json={'sku':'pack3'}).status_code==200
        assert admin.post('/api/dev/reset-all',json={'scope':'progress','confirmation':'errado'}).status_code==422
        assert admin.post('/api/dev/reset-all',json={'scope':'progress','confirmation':'LIMPAR TUDO'}).status_code==200
        assert admin.get('/api/inventory').json()['packs']==[]
        assert admin.get('/api/me').json()['coins']==0
        assert admin.get('/api/game/config').json()['admin'] is True
