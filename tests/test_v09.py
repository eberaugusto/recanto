"""Novas regras Recanto v0.9; todos os testes usam um banco temporário isolado."""
from datetime import timedelta
from sqlalchemy import text
from test_v07 import app_module, client_as

A='249610270069096448'
B='313131313131313131'

def make_copy(app, uid, card_id=1):
    with app.SessionLocal.begin() as db:
        db.add(app.OwnedCard(user_id=uid, card_id=card_id, acquired_at=app.utcnow()))

def test_new_economy_and_five_hour_claim(app_module):
    app=app_module
    with client_as(app,A) as c:
        config=c.get('/api/game/config').json()
        assert config['chances']['pack3']['prismático']>config['chances']['pack5']['prismático']
        assert config['rules']['daily_coins']==35
        assert config['rules']['pack3_cost']>config['rules']['pack5_cost']
        first=c.post('/api/daily/card',json={})
        assert first.status_code==200,first.text
        assert c.post('/api/daily/card',json={}).status_code==409
        status=c.get('/api/daily/status').json()
        assert status['card_claimed'] and status['card_next_at']
        with app.engine.begin() as db:
            db.execute(text("UPDATE card_cooldowns SET last_claimed=:last WHERE user_id=:uid"),
                       {'last':(app.utcnow()-timedelta(hours=6)).replace(tzinfo=None),'uid':A})
        assert c.get('/api/daily/status').json()['card_claimed'] is False
        assert c.post('/api/daily/card',json={}).status_code==200


def test_coin_offer_escrow_refund_and_accept(app_module):
    app=app_module
    make_copy(app,B)
    with client_as(app,A) as buyer, client_as(app,B) as seller:
        mine=seller.get('/api/cards').json()['items'][0]
        min_offer=buyer.get('/api/card-economy').json()['minimum_offers'][mine['rarity']]
        balance=buyer.get('/api/me').json()['coins']
        low=buyer.post('/api/coin-offers',json={'to_user':B,'wanted_owned_id':mine['owned_id'],'amount':min_offer-1})
        assert low.status_code==422
        offered=buyer.post('/api/coin-offers',json={'to_user':B,'wanted_owned_id':mine['owned_id'],'amount':min_offer})
        assert offered.status_code==200,offered.text
        assert buyer.get('/api/me').json()['coins']==balance-min_offer
        offer_id=offered.json()['id']
        denied=seller.post(f'/api/coin-offers/{offer_id}/decide',json={'action':'reject'})
        assert denied.status_code==200
        assert buyer.get('/api/me').json()['coins']==balance
        offered=buyer.post('/api/coin-offers',json={'to_user':B,'wanted_owned_id':mine['owned_id'],'amount':min_offer})
        oid=offered.json()['id']
        assert seller.post(f'/api/coin-offers/{oid}/decide',json={'action':'accept'}).status_code==200
        assert buyer.get('/api/me').json()['coins']==balance-min_offer
        assert buyer.get('/api/cards').json()['total']==1
        assert seller.get('/api/cards').json()['total']==0
        assert seller.post(f'/api/coin-offers/{oid}/decide',json={'action':'accept'}).status_code==409


def test_duplicate_sale_and_game_profiles(app_module):
    app=app_module
    make_copy(app,A)
    make_copy(app,A)
    with client_as(app,A) as c,client_as(app,B) as visitor:
        cards=c.get('/api/cards').json()['items']
        own=cards[0]['owned_id']
        assert c.get('/api/card-economy').json()['duplicate_sale']['comum']==10
        result=c.post('/api/cards/sell-duplicate',json={'owned_id':own})
        assert result.status_code==200,result.text
        assert c.get('/api/cards').json()['total']==1
        assert c.post('/api/cards/sell-duplicate',json={'owned_id':cards[1]['owned_id']}).status_code==409
        catalog=c.get('/api/games/preferences').json()['catalog']
        assert len(catalog)>=20
        ids=[x['id'] for x in catalog[:5]]
        assert c.post('/api/games/preferences',json={'games':ids}).status_code==200
        assert c.post('/api/games/preferences',json={'games':ids+['random']}).status_code==422
        profile=visitor.get('/api/community/profiles/'+A).json()
        assert 'coins' not in profile
        assert len(profile['favorite_games'])==5
        featured=c.get('/api/collections/featured').json()
        assert featured['name']=='Celebridades'
        assert 'Memes' in featured['collections']
        assert c.post('/api/admin/collections/featured',json={'name':'Memes'}).status_code==200
        assert visitor.get('/api/collections/featured').json()['name']=='Memes'


def test_pet_expedition_care_lock_and_return(app_module):
    app=app_module
    with client_as(app,A) as owner,client_as(app,B) as friend:
        species=owner.get('/api/pets').json()['species'][0]['id']
        assert owner.post('/api/pets/adopt',json={'species_id':species}).status_code==200
        task=owner.post('/api/pets/expedition/start',json={'mission':'passeio'})
        assert task.status_code==200,task.text
        assert owner.get('/api/pets').json()['pet']['status']=='missao'
        assert owner.post('/api/pets/care',json={'action':'pet'}).status_code==409
        assert friend.post(f'/api/pets/visit/{A}',json={'action':'pet'}).status_code==409
        assert owner.post('/api/pets/expedition/collect',json={}).status_code==409
        with app.engine.begin() as db:
            db.execute(text('UPDATE pet_expeditions SET ends_at=:end WHERE user_id=:uid'),
                       {'end':(app.utcnow()-timedelta(minutes=1)).replace(tzinfo=None),'uid':A})
        finished=owner.post('/api/pets/expedition/collect',json={})
        assert finished.status_code==200,finished.text
        assert finished.json()['coins_gained']>=12
        assert owner.get('/api/pets').json()['pet']['status']=='ativo'
        assert owner.post('/api/pets/expedition/collect',json={}).status_code==409
