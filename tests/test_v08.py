"""Regressoes de colecoes e UI v0.8, usando banco temporario e sessoes isoladas."""
from datetime import datetime, timezone
from pathlib import Path
from test_v07 import app_module, client_as  # fixtures v0.7


def test_catalog_has_collections_and_filter_fields(app_module):
    with client_as(app_module, '249610270069096448') as client:
        catalog=client.get('/api/catalog')
        assert catalog.status_code == 200
        assert all(x['collection'] == 'Recanto Original' for x in catalog.json()['items'])
        assert all(x['created_at'] for x in catalog.json()['items'])
        response=client.post('/api/admin/cards',json={
            'name':'Grande Aurora','rarity':'raro','collection':'Bosque Encantado'})
        assert response.status_code==200,response.text
        cid=response.json()['id']
        created=next(c for c in client.get('/api/catalog').json()['items'] if c['id']==cid)
        assert created['collection']=='Bosque Encantado'
        assert created['created_at']
        response=client.post('/api/admin/cards/collection',json={'card_id':cid,'collection':'Noites de Inverno'})
        assert response.status_code==200,response.text
        updated=next(c for c in client.get('/api/catalog').json()['items'] if c['id']==cid)
        assert updated['collection']=='Noites de Inverno'


def test_admin_collection_validation_and_member_access(app_module):
    with client_as(app_module, '249610270069096448') as admin, client_as(app_module,'313131313131313131') as member:
        assert admin.post('/api/admin/cards',json={'name':'Teste','rarity':'comum','collection':'x'}).status_code==422
        assert member.post('/api/admin/cards/collection',json={'card_id':1,'collection':'Aventuras'}).status_code==403
        card=admin.post('/api/daily/card',json={})
        assert card.status_code==200, card.text
        owned=admin.get('/api/cards').json()['items']
        assert owned and owned[0]['collection']=='Recanto Original'


def test_frontend_markup_and_cache_version(app_module):
    root=Path(__file__).resolve().parents[1]
    index=(root/'frontend/index.html').read_text()
    js=(root/'frontend/app.js').read_text()
    css=(root/'frontend/styles.css').read_text()
    assert index.count('id="searchUsers"')==1
    assert index.count('id="dailyCoins"')==1
    assert index.index('id="dailyCoins"')>index.index('id="shopScreen"')
    assert 'id="cardFilters"' in index and 'id="dailyCardIcon"' in index
    assert 'card-icon-available' in js
    assert 'shareCardArtwork' not in js
    assert 'logo-breathe-v08' in css
    assert 'recanto-ui-1.0.0' in (root/'frontend/sw.js').read_text()


def test_upgrade_old_cards_table_without_losing_rows(tmp_path, monkeypatch):
    import sqlite3
    from sqlalchemy import inspect, select
    path=tmp_path/'legacy.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE cards (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL, image_url VARCHAR(512), rarity VARCHAR(40) NOT NULL)')
        db.execute("INSERT INTO cards (id,name,rarity) VALUES (900, 'Arte preservada', 'raro')")
    monkeypatch.setenv('DATABASE_URL',f'sqlite:///{path.as_posix()}')
    import importlib, sys
    root=Path(__file__).resolve().parents[1]/'backend'
    sys.path.insert(0,str(root))
    for mod in ('main','game'):
        sys.modules.pop(mod,None)
    try:
        m=importlib.import_module('main')
        names={x['name'] for x in inspect(m.engine).get_columns('cards')}
        assert {'collection_name','created_at'}<=names
        with m.SessionLocal() as db:
            c=db.get(m.Card,900)
            assert c.name=='Arte preservada'
            assert c.rarity=='raro'
            assert c.collection_name=='Recanto Original'
            assert c.created_at is None
    finally:
        for mod in ('main','game'):
            sys.modules.pop(mod,None)
        sys.path.remove(str(root))
