"""Recanto v0.9.2 — assets dinamicos e seguranca de administracao."""
from pathlib import Path
import io
from PIL import Image
from fastapi.testclient import TestClient
from test_v07 import app_module, client_as

ADMIN = '249610270069096448'
VISITOR = '313131313131313131'


def test_assets_admin_game_icons_and_public_profile(app_module):
    with client_as(app_module, ADMIN) as admin, client_as(app_module, VISITOR) as member:
        original = member.get('/api/assets')
        assert original.status_code == 200
        assert member.post('/api/admin/assets', json={
            'key':'game:league','selector':'','mode':'icon','image_url':'https://example.org/league.png'}).status_code == 403
        added = admin.post('/api/admin/assets', json={
            'key':'game:league','selector':'','mode':'icon','image_url':'https://example.org/league.png'})
        assert added.status_code == 200, added.text
        assert any(a['key']=='game:league' for a in member.get('/api/assets').json()['items'])
        games = member.get('/api/games/preferences').json()['catalog']
        assert next(g for g in games if g['id']=='league')['image_url']=='https://example.org/league.png'
        saved = admin.post('/api/games/preferences', json={'games':['league']})
        assert saved.status_code == 200
        assert member.get('/api/community/profiles/'+ADMIN).json()['favorite_games'][0]['image_url']=='https://example.org/league.png'
        removed=admin.post('/api/admin/assets',json={
            'key':'game:league','selector':'','mode':'icon','image_url':''})
        assert removed.status_code==200
        assert next(g for g in member.get('/api/games/preferences').json()['catalog'] if g['id']=='league')['image_url'] is None


def test_asset_selectors_removal_and_prelogin(app_module):
    with client_as(app_module, ADMIN) as admin:
        for key,selector,mode in [
            ('nav-perfil','[data-tab="perfil"] .nav-circle','icon'),
            ('coins-asset','.stats-list .stat:nth-child(1) .stat-icon','icon'),
            ('login-bg','#loginScreen','background'),
        ]:
            resp=admin.post('/api/admin/assets', json={
                'key':key,'selector':selector,'mode':mode,'image_url':'https://example.org/asset.png'})
            assert resp.status_code==200,(key,resp.text)
        bad=admin.post('/api/admin/assets',json={
            'key':'injection','selector':'#loginScreen{color:red}','mode':'background',
            'image_url':'https://example.org/asset.png'})
        assert bad.status_code==422
        no_js=admin.post('/api/admin/assets',json={
            'key':'no-js','selector':'#loginScreen','mode':'background','image_url':'javascript:alert(1)'})
        assert no_js.status_code==422
        assert admin.post('/api/admin/assets',json={
            'key':'login-bg','selector':'#loginScreen','mode':'background','image_url':''}).status_code==200
    with TestClient(app_module.app) as unauthenticated:
        response=unauthenticated.get('/api/assets')
        assert response.status_code==200
        assert all(a['key']!='login-bg' for a in response.json()['items'])


def test_image_upload_for_assets(app_module):
    img=Image.new('RGBA',(16,16),(30,80,240,255))
    output=io.BytesIO();img.save(output,'PNG')
    image=output.getvalue()
    path=None
    try:
        with client_as(app_module, ADMIN) as admin, client_as(app_module, VISITOR) as user:
            assert user.post('/api/admin/upload',files={'image':('icon.png',image,'image/png')}).status_code==403
            created=admin.post('/api/admin/upload',files={'image':('icon.png',image,'image/png')})
            assert created.status_code==200,created.text
            url=created.json()['image_url']
            path=Path(__file__).resolve().parents[1]/'frontend'/url.lstrip('/')
            assert path.is_file()
            assert admin.post('/api/admin/assets',json={
                'key':'fundo-app','selector':'#homeScreen','mode':'background','image_url':url}).status_code==200
            assert user.get(url).status_code==200
    finally:
        if path and path.exists():path.unlink()
