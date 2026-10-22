"""Recanto v0.9.1: chance, preco, bonus por tier e persistencia."""
import importlib
import sys

from sqlalchemy import text
from test_v07 import app_module, client_as

ADMIN='249610270069096448'
REWARDS={'comum':1,'raro':2,'lendário':4,'prismático':5}
PACK3={'comum':65,'raro':20,'lendário':12,'prismático':3}
PACK5={'comum':65,'raro':25,'lendário':9,'prismático':1}


def test_prices_chances_rewards_and_credit_once(app_module):
    with client_as(app_module, ADMIN) as client:
        cfg=client.get('/api/game/config').json()
        assert cfg['chances']['pack3']==PACK3
        assert cfg['chances']['pack5']==PACK5
        for tier,val in REWARDS.items():
            assert cfg['rules']['card_bonus_'+tier]==val
        shop={p['sku']:p for p in client.get('/api/shop').json()['products']}
        assert shop['pack3']['price']==700
        assert shop['pack5']['price']==550
        assert shop['pack3']['rates']==PACK3
        assert shop['pack5']['rates']==PACK5
        balance=client.get('/api/me').json()['coins']
        for sku,cost in [('pack3',700),('pack5',550)]:
            bought=client.post('/api/shop/purchase',json={'sku':sku})
            assert bought.status_code==200,bought.text
            pack_id=bought.json()['pack_id']
            balance-=cost
            assert client.get('/api/me').json()['coins']==balance, 'Nao paga bonus na compra do pack'
            opened=client.post(f'/api/inventory/packs/{pack_id}/open',json={})
            assert opened.status_code==200,opened.text
            data=opened.json()
            total=sum(REWARDS[c['rarity']] for c in data['cards'])
            assert data['bonus_coins']==total
            assert all(c['bonus_coins']==REWARDS[c['rarity']] for c in data['cards'])
            balance+=total
            assert client.get('/api/me').json()['coins']==balance
            assert client.post(f'/api/inventory/packs/{pack_id}/open',json={}).status_code==409
            assert client.get('/api/me').json()['coins']==balance

        claim=client.post('/api/daily/card',json={})
        assert claim.status_code==200, claim.text
        card=claim.json()['card']
        assert card['bonus_coins']==REWARDS[card['rarity']]
        assert client.get('/api/me').json()['coins']==balance+card['bonus_coins']
        assert client.post('/api/daily/card',json={}).status_code==409


def test_admin_bonus_is_per_tier_and_legacy_bonus_removed(app_module):
    with client_as(app_module, ADMIN) as client:
        settings=client.get('/api/admin/settings').json()['settings']
        assert 'card_bonus' not in settings
        assert {k:settings['card_bonus_'+k] for k in REWARDS}==REWARDS
        assert client.post('/api/admin/settings',json={'key':'card_bonus','value':5}).status_code==422
        assert client.post('/api/admin/settings',json={'key':'card_bonus_raro','value':6}).status_code==422
        assert client.post('/api/admin/settings',json={'key':'card_bonus_raro','value':3}).status_code==200
        assert client.get('/api/admin/settings').json()['settings']['card_bonus_raro']==3


def test_existing_v09_defaults_migrate_without_touching_custom_price(tmp_path,monkeypatch):
    from pathlib import Path
    path=tmp_path/'old_version.db'
    backend=Path(__file__).resolve().parents[1]/'backend'
    monkeypatch.setenv('DATABASE_URL',f'sqlite:///{path}')
    monkeypatch.setenv('APP_ENV','development')
    sys.path.insert(0,str(backend))
    def load():
        for mod in ('main','game'):
            sys.modules.pop(mod,None)
        return importlib.import_module('main')
    try:
        old=load()
        with old.engine.begin() as conn:
            conn.execute(text("UPDATE game_settings SET value=850 WHERE key='pack3_cost'"))
            conn.execute(text("UPDATE game_settings SET value=600 WHERE key='pack5_cost'"))
            conn.execute(text("INSERT INTO game_settings(key,value) VALUES ('card_bonus',5)"))
        new=load()
        with new.SessionLocal() as db:
            values={k:v for k,v in db.execute(text('SELECT key,value FROM game_settings')).all()}
            assert values['pack3_cost']==700
            assert values['pack5_cost']==550
            assert 'card_bonus' not in values
            assert values['card_bonus_prismático']==5
        with new.engine.begin() as conn:
            conn.execute(text("UPDATE game_settings SET value=625 WHERE key='pack3_cost'"))
        customized=load()
        with customized.SessionLocal() as db:
            values={k:v for k,v in db.execute(text('SELECT key,value FROM game_settings')).all()}
            assert values['pack3_cost']==625
            assert values['pack5_cost']==550
    finally:
        for mod in ('main','game'):
            sys.modules.pop(mod,None)
        sys.path.remove(str(backend))
