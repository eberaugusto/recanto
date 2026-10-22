"""Smoke tests da hospedagem, arquivos do PWA e upload externo de imagens."""
import hashlib
import io
from pathlib import Path
from PIL import Image
from fastapi.testclient import TestClient
from test_v07 import app_module, client_as

ADMIN='249610270069096448'
VISITOR='313131313131313131'


def test_version_health_and_pwa_update_markup(app_module):
    root=Path(__file__).resolve().parents[1]
    with TestClient(app_module.app) as browser:
        assert browser.get('/api/version').json()['version']=='1.0.0'
        assert browser.get('/api/health').status_code==200
        html=browser.get('/').text
        assert 'id="updateBanner"' in html
        assert 'id="updateNow"' in html
        assert 'id="checkUpdates"' in html
    sw=(root/'frontend/sw.js').read_text()
    js=(root/'frontend/app.js').read_text()
    assert "recanto-ui-1.0.0" in sw
    assert "SKIP_WAITING" in sw and "SKIP_WAITING" in js
    assert "url.pathname.startsWith('/api/')" in sw


def test_cloudinary_signed_image_upload_and_admin_guard(app_module, monkeypatch):
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.setenv('CLOUDINARY_CLOUD_NAME','cloud-recanto')
    monkeypatch.setenv('CLOUDINARY_API_KEY','public-key')
    monkeypatch.setenv('CLOUDINARY_API_SECRET','private-secret')
    import httpx
    received=[]
    class DummyResponse:
        def raise_for_status(self):return None
        def json(self):return {'secure_url':'https://res.cloudinary.com/cloud-recanto/image/upload/recanto/test.png'}
    class DummyClient:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,data=None,files=None):
            received.append((url,data,files))
            return DummyResponse()
    monkeypatch.setattr(httpx,'AsyncClient',DummyClient)
    img=Image.new('RGB',(14,14),(10,40,90));bio=io.BytesIO();img.save(bio,format='PNG')
    files={'image':('test.png',bio.getvalue(),'image/png')}
    with client_as(app_module,VISITOR) as visitor:
        assert visitor.post('/api/admin/upload',files=files).status_code==403
    with client_as(app_module,ADMIN) as admin:
        response=admin.post('/api/admin/upload',files=files)
        assert response.status_code==200,response.text
        assert response.json()['image_url'].startswith('https://res.cloudinary.com/')
    assert len(received)==1
    url,data,_=received[0]
    assert url=='https://api.cloudinary.com/v1_1/cloud-recanto/image/upload'
    signed='folder=recanto&timestamp='+data['timestamp']
    assert data['signature']==hashlib.sha1((signed+'private-secret').encode()).hexdigest()


def test_public_frontend_has_no_secrets(app_module):
    with TestClient(app_module.app) as browser:
        for url in ('/app.js','/styles.css','/sw.js'):
            r=browser.get(url)
            assert r.status_code==200
            assert 'CLOUDINARY_API_SECRET' not in r.text
