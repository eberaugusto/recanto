// PWA v0.8: rede em primeiro lugar para evitar interface desatualizada.
// A API e a autenticação nunca passam pelo cache.
const CACHE = 'recanto-ui-0.2.1';
const CORE = ['/', '/styles.css?v=0.2.1', '/app.js?v=0.2.1', '/recanto-logo.png', '/icons/icon-192.png'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(CORE)));
});
self.addEventListener('message', event => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
// 0.1.6: PWA instalado abre a interface do cache antes do servidor acordar.
// Nunca armazenar APIs, sessão, uploads nem páginas de autenticação.
self.addEventListener('fetch', event => {
  const req=event.request;
  const url=new URL(req.url);
  if(req.method!=='GET' || url.origin!==self.location.origin ||
     url.pathname.startsWith('/api/') || url.pathname.startsWith('/auth/') ||
     url.pathname.startsWith('/uploads/') || url.pathname.startsWith('/models/'))return;

  if(req.mode==='navigate' && url.pathname==='/'){
    event.respondWith(caches.match('/').then(cached=>cached || fetch(req)));
    return;
  }
  const versionedStatic = url.pathname==='/styles.css' || url.pathname==='/app.js';
  const stableStatic = url.pathname.startsWith('/icons/') || url.pathname==='/recanto-logo.png';
  if(versionedStatic || stableStatic){
    event.respondWith(caches.match(req).then(cached=>cached || fetch(req).then(response=>{
      if(response.ok){const copy=response.clone();event.waitUntil(caches.open(CACHE).then(cache=>cache.put(req,copy)));}
      return response;
    })));
    return;
  }
  event.respondWith(fetch(req).catch(()=>caches.match(req).then(cached=>cached||Response.error())));
});

// Estrutura de recebimento de push para a etapa futura. Nao envia alertas por si so.
self.addEventListener('push', event => {
  let data = {title: 'Recanto', body: 'Você tem uma novidade no Recanto!'};
  try { if (event.data) data = {...data, ...event.data.json()}; } catch (_) { /* payload opcional */ }
  const title = String(data.title || 'Recanto').slice(0, 90);
  const body = String(data.body || '').slice(0, 230);
  event.waitUntil(self.registration.showNotification(title, {
    body, icon: '/icons/icon-192.png', badge: '/icons/icon-192.png', tag: 'recanto-evento'
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(windows => {
    for (const win of windows) { if (win.url.startsWith(self.location.origin)) return win.focus(); }
    return self.clients.openWindow('/');
  }));
});
