"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const PREFETCH_TTL=60000;
  const tabLoadedAt={};
  const TAB_SOFT_TTL=20000;
  const getCache=new Map();
  const cacheable=url=>/^(\/api\/(game\/config|achievements|games\/preferences|shop|daily\/status|catalog|cards|inventory|pets|missions|collections\/featured|assets|community\/profiles))(\?|$|\/)/.test(url);
  function resetCachedData(){getCache.clear();for(const k of Object.keys(tabLoadedAt))delete tabLoadedAt[k];if(typeof state!=='undefined')state.petPreviewLoaded=false;}
  const API = async (url, data) => {
    if(data===undefined && cacheable(url)){
      const prev=getCache.get(url);
      if(prev && prev.until>Date.now())return prev.promise;
      const task=fetchJson(url,data);
      getCache.set(url,{until:Date.now()+PREFETCH_TTL,promise:task});
      task.catch(()=>{if(getCache.get(url)?.promise===task)getCache.delete(url);});
      return task;
    }
    return fetchJson(url,data);
  };
  const fetchJson=async (url, data) => {
    const options = { credentials: 'same-origin', cache:'no-store', headers: {Accept:'application/json'} };
    if (data !== undefined) {options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(data);}
    const controller=new AbortController();
    const timeout=setTimeout(()=>controller.abort(),18000);
    let response;
    try{response=await fetch(url,{...options,signal:controller.signal});}finally{clearTimeout(timeout);}
    let result;try{result=await response.json();}catch(_){result={detail:'O servidor não respondeu corretamente.'};}
    if(!response.ok)throw Error(result.detail||`Erro HTTP ${response.status}`);
    return result;
  };
  let prefetchPromise=null;
  function prefetchTabs(){
    if(prefetchPromise)return prefetchPromise;
    const urls=['/api/daily/status','/api/shop','/api/inventory','/api/missions','/api/pets'];
    prefetchPromise=Promise.allSettled(urls.map(url=>API(url)));
    prefetchPromise.finally(()=>{prefetchPromise=null;});
    return prefetchPromise;
  }
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  async function retryBootstrap(url){
    let last;
    for(let attempt=0;attempt<3;attempt++){
      try{return await API(url);}catch(err){last=err;if(attempt<2)await sleep(350*(attempt+1));}
    }
    throw last;
  }

  const h = (tag, className='', content='') => {const el=document.createElement(tag);if(className)el.className=className;if(content!==undefined&&content!==null)el.textContent=String(content);return el;};
  const money = n=>Number(n||0).toLocaleString('pt-BR');
  const poroLegacyText = value => String(value ?? '').replace(/Pequenas Lendas/gi,'Poros').replace(/Pequena Lenda/gi,'Poro').replace(/\bpets\b/gi,'Poros').replace(/\bpet\b/gi,'Poro');
  const poroSpeciesName = value => /^Pequena Lenda — exemplo (\d+)$/i.test(String(value || '')) ? String(value).replace(/Pequena Lenda/i,'Poro') : value;
  const labels={feed:'Feed',perfil:'Perfil',cards:'Cards',inventario:'Inventário',pet:'Poros',loja:'Loja',missoes:'Missões'};
  const tierLabels={comum:'Comum',raro:'Raro',lendário:'Lendário',prismático:'Prismático'};
  const state={dailyReward:0,dailyClaimInFlight:false,assets:[],account:null,config:{},game:null,tab:'perfil',cardTab:'colecao',reset:null,cardReset:null,missionReset:null,installEvent:null,notification:false,notificationBusy:false,tabTransition:0,focusShop:null,petAction:null,inventoryTab:'packs',reveal:null,revealIndex:0,revealFace:false,badgesVisible:8,cardPage:1,cardPageSize:12,darkMode:false,cardFilters:{rarity:'todos',collection:'todas',alphabetical:matchMedia('(min-width:768px)').matches?'raridade':'padrao',missing:false,newOnly:false},detailClosing:false};
  const toast=(message)=>{const el=$('toast');el.textContent=message;el.hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>{el.hidden=true;},4000);};
  $('toast').addEventListener('click',()=>{$('toast').hidden=true;clearTimeout(toast.timer);});
  $('toast').title='Clique para dispensar';
  const report=msg=>{$('message').textContent=msg||'';};
  // O botão responde ao clique no mesmo frame; uma requisição demorada nunca aceita clique duplo.
  const button=(text,handler,style='main-action')=>{
    const b=h('button',style,text);b.type='button';
    b.addEventListener('click',event=>{
      if(b.dataset.pending==='1')return;
      let promise;
      try{promise=handler(event);}catch(err){toast('⚠ '+(err?.message||'Falha na operação.'));return;}
      if(promise && typeof promise.then==='function'){
        b.dataset.pending='1';b.classList.add('action-pending');b.setAttribute('aria-busy','true');
        Promise.resolve(promise).catch(err=>toast('⚠ '+(err?.message||'Falha na operação.'))).finally(()=>{
          delete b.dataset.pending;b.classList.remove('action-pending');b.removeAttribute('aria-busy');
          // Não sobrescrever disabled definido pela lógica da ação (ex.: missão já resgatada).
        });
      }
    });return b;
  };
  const block=(title,body)=>{const div=h('div','game-box');if(title)div.append(h('h3','',title));if(body)div.append(h('p','',body));return div;};
  // A resposta do POST encerra a espera. GETs de reconciliação não bloqueiam a interface.
  let reconcileTimer=null;
  let profileRefreshGeneration=0;
  const pendingFeedLikes=new Set();
  let pendingCoinsPreview=0;
  function paintCoins(){
    if(!state.account)return;
    const total=Number(state.account.coins||0)+pendingCoinsPreview;
    for(const id of ['valMoedas','desktopWallet']){const el=$(id);if(el){el.textContent=money(total);el.classList.toggle('coins-awaiting-confirmation',pendingCoinsPreview>0);}}
    const shop=$('shopWallet');if(shop)shop.textContent='🪙 '+money(total);
  }
  function applyConfirmedCoins(response, fallback=0){
    if(!state.account)return;
    // Uma resposta com saldo final é autoritativa; os clientes antigos ainda aceitam deltas.
    const value=Number(response?.coins_balance);
    if(response?.coins_balance!==undefined && Number.isFinite(value))state.account.coins=value;
    else state.account.coins=Math.max(0,Number(state.account.coins||0)+Number(response?.coins_gained??fallback));
    profileRefreshGeneration++; // Desconsiderar GET de /me iniciado antes da confirmação.
    paintCoins();
  }
  function reconcileAfterAction(){
    if(reconcileTimer)clearTimeout(reconcileTimer);
    reconcileTimer=setTimeout(()=>{
      reconcileTimer=null;
      // Atualização na retaguarda: não fazer o usuário esperar /me e outra aba.
      refreshProfile().catch(()=>{});
      if($('adminModal').hidden && !pendingFeedLikes.size)refreshActive(true).catch(()=>{});
    },180);
  }
  const safeRun=async(action,success,onConfirmed=null)=>{
    try{
      const result=await action();resetCachedData();
      if(onConfirmed)onConfirmed(result);
      if(success)toast(typeof success==='function'?success(result):success);
      reconcileAfterAction();return result;
    }catch(err){toast('⚠ '+(err?.message||'Não foi possível concluir.'));return null;}
  };
  function countdown(iso){if(!iso)return '—';const delta=new Date(iso).getTime()-Date.now();if(delta<=0)return 'Disponível agora';let s=Math.ceil(delta/1000);const d=Math.floor(s/86400);s%=86400;const hour=Math.floor(s/3600);s%=3600;const minute=Math.floor(s/60);const sec=s%60;return (d?`${d}d `:'')+`${String(hour).padStart(2,'0')}:${String(minute).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;}
  function updateCountdowns(){if(state.reset){const t=countdown(state.reset);$('cardCountdown').textContent=$('dailyCard').disabled?'Novo card em '+countdown(state.cardReset):'Disponível agora (a cada 5h)!';$('coinCountdown').textContent=$('dailyCoins').disabled?'Próximo resgate: '+t:'Resgate disponível!';}if(state.missionReset)$('missionTimer').textContent='Resetam em: '+countdown(state.missionReset);}
  function avatar(el,name,url){el.replaceChildren();if(url){const img=h('img');img.src=url;img.alt='Foto de '+name;img.onerror=()=>{img.remove();el.textContent='◉';};el.append(img);}else el.textContent='◉';}

  function applyTheme(mode){
    state.darkMode=mode==='dark';
    document.body.classList.toggle('dark-mode',state.darkMode);
    const toggle=$('darkModeToggle');
    if(toggle){toggle.classList.toggle('on',state.darkMode);toggle.setAttribute('aria-checked',String(state.darkMode));}
  }
  function loadTheme(){
    const stored=localStorage.getItem('recanto-theme');
    applyTheme(stored==='dark'?'dark':'light');
  }
  function toggleDarkMode(){
    const next=state.darkMode?'light':'dark';
    localStorage.setItem('recanto-theme',next);
    applyTheme(next);
    toast(state.darkMode?'Modo escuro ativado.':'Modo claro ativado.');
  }
  function updateInstallButton(){
    const btn=$('installApp');
    if(!btn)return;
    const installed=matchMedia('(display-mode: standalone)').matches || navigator.standalone===true;
    btn.hidden=installed;
    btn.disabled=installed;
    btn.querySelector('span').textContent='Instalar';
  }
  function renderProfile(me){state.account=me;$('loginScreen').hidden=true;$('homeScreen').hidden=false;$('modal').hidden=true;$('userName').textContent='Olá, '+me.name;$('valMoedas').textContent=money(me.coins);$('valCards').textContent=money(me.cards);$('valPetiscos').textContent=money(me.treats);$('desktopWallet').textContent=money(me.coins);$('desktopCards').textContent=money(me.cards);$('desktopTreats').textContent=money(me.treats);$('desktopUserName').textContent=me.name;$('desktopProfileName').textContent=me.name;avatar($('userAvatar'),me.name,me.avatar_url);avatar($('desktopAvatar'),me.name,me.avatar_url);const recent=$('latestCard');recent.replaceChildren();recent.classList.toggle('has-card',false);recent.setAttribute('aria-label','Nenhum card favorito selecionado');recent.onclick=()=>toast('Escolha um card da sua coleção e toque em Favoritar card.');recent.onkeydown=(e)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();recent.click();}};recent.textContent='?';paintCoins();const profileId=me.name;API('/api/cards/favorite').then(({card})=>{if(state.account?.name!==profileId)return;recent.replaceChildren();recent.classList.toggle('has-card',!!card);recent.setAttribute('aria-label',card?'Ampliar card favorito: '+card.name:'Nenhum card favorito selecionado');recent.onclick=card?()=>showCard(card,'Card favorito',true):()=>toast('Escolha um card da sua coleção e toque em Favoritar card.');recent.onkeydown=(e)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();recent.click();}};if(card?.image_url){const img=h('img');img.src=card.image_url;img.alt=card.name;recent.append(img);}else recent.textContent=card?.name||'?';}).catch(()=>{});}

  async function refreshProfile(){
    if(!state.account)return;
    const generation=++profileRefreshGeneration;
    const me=await API('/api/me');
    if(generation!==profileRefreshGeneration)return;
    if(me.authenticated){
      const previous=state.account;
      if(!previous||previous.name!==me.name||previous.avatar_url!==me.avatar_url){renderProfile(me);}
      else{
        // Atualização de contadores sem reconstruir avatar, favorito e toda a página.
        state.account=me;
        $('valCards').textContent=money(me.cards);$('valPetiscos').textContent=money(me.treats);
        $('desktopCards').textContent=money(me.cards);$('desktopTreats').textContent=money(me.treats);
      }
      paintCoins();
    }else showLogin();
  }
  function showLogin(){resetCachedData();state.adminReady=false;state.petPreviewLoaded=false;$('adminModal').hidden=true;document.body.classList.remove('page-open');$('settingsAdmin').hidden=true;state.account=null;$('loginScreen').hidden=false;$('splashScreen').hidden=true;$('homeScreen').hidden=true;$('modal').hidden=true;}
  async function refreshActive(force=false){if(!state.account)return;
    if(!force && tabLoadedAt[state.tab] && Date.now()-tabLoadedAt[state.tab]<TAB_SOFT_TTL)return;
    if(state.tab==='feed')await loadFeed();
    if(state.tab==='perfil')await loadProfileExtras();
    if(state.tab==='cards')await loadCards();
    if(state.tab==='inventario')await loadInventory();
    if(state.tab==='pet')await loadPet();
    if(state.tab==='loja')await loadShop();
    if(state.tab==='missoes')await loadMissions();
    tabLoadedAt[state.tab]=Date.now();
  }
  // 0.1.21: animação entre telas ao deslizar no celular.
  const MOBILE_TAB_ORDER=['feed','perfil','missoes','inventario','cards','pet','loja'];
  let swipeCleanup=null;
  let swipeGuideDismissed=false;
  let swipeGuideTimer=null;
  function hideSwipeGuide(){
    swipeGuideDismissed=true;
    clearTimeout(swipeGuideTimer);swipeGuideTimer=null;
    const guide=$('recantoSwipeGuide');if(!guide)return;
    guide.classList.add('recanto-guide-fadeout');
    setTimeout(()=>{guide.hidden=true;guide.classList.remove('recanto-guide-fadeout');},420);
  }
  function showSwipeGuide(){
    const guide=$('recantoSwipeGuide');if(!guide)return;
    const mobile=matchMedia('(max-width:767px)').matches;
    if(!mobile||!state.account||swipeGuideDismissed){guide.hidden=true;return;}
    const idx=MOBILE_TAB_ORDER.indexOf(state.tab);
    const left=$('recantoSwipeLeft'),right=$('recantoSwipeRight');
    left.hidden=idx<=0;right.hidden=idx>=MOBILE_TAB_ORDER.length-1;
    guide.hidden=false;
    if(!swipeGuideTimer)swipeGuideTimer=setTimeout(hideSwipeGuide,5000);
  }
  function registerSwipeDiscovery(){hideSwipeGuide();}
  async function chooseTab(tab,focusSku=null,transitionDirection=0){
    if(!labels[tab]||!state.account)return;
    const pages={feed:$('feedScreen'),perfil:$('profileContent'),cards:$('cardsScreen'),inventario:$('inventoryScreen'),pet:$('petScreen'),loja:$('shopScreen'),missoes:$('missionsScreen')};
    const oldTab=state.tab,oldPage=pages[oldTab];const nextPage=pages[tab];const changed=oldTab!==tab;
    const seq=++state.tabTransition;
    const slide=changed&&transitionDirection!==0&&matchMedia('(max-width:767px)').matches&&
      !matchMedia('(prefers-reduced-motion: reduce)').matches;
    if(swipeCleanup){swipeCleanup();swipeCleanup=null;}
    state.tab=tab;if(tab==='loja'&&focusSku)state.focusShop=focusSku;
    document.querySelectorAll('[data-tab]').forEach(b=>{b.classList.toggle('nav-active',b.dataset.tab===tab);b.setAttribute('aria-current',b.dataset.tab===tab?'page':'false');});
    // Duas telas temporariamente visíveis criam a sensação de acompanhar a navegação.
    // A animação não altera a posição persistente nem a rolagem de nenhuma aba.
    Object.entries(pages).forEach(([key,node])=>{node.hidden=slide?key!==tab&&key!==oldTab:key!==tab;node.classList.remove('page-enter','recanto-slide-enter','recanto-slide-exit','slide-next','slide-prev');});
    if(slide&&oldPage&&nextPage){
      const klass=transitionDirection>0?'slide-next':'slide-prev';
      oldPage.classList.add('recanto-slide-exit',klass);
      nextPage.classList.add('recanto-slide-enter',klass);
      let timeout=setTimeout(()=>finish(),270);
      function finish(){clearTimeout(timeout);oldPage.hidden=true;oldPage.classList.remove('recanto-slide-exit',klass);nextPage.classList.remove('recanto-slide-enter',klass);if(swipeCleanup===finish)swipeCleanup=null;}
      swipeCleanup=finish;
    }
    document.querySelectorAll('.desktop-side-link[data-tab]').forEach(btn=>btn.classList.toggle('selected',btn.dataset.tab===tab));
    showSwipeGuide();
    // Preservar a rolagem interna de cada aba sem transformar o contêiner da tela.
    if(changed && nextPage && nextPage.dataset.firstVisit!=='yes'){nextPage.dataset.firstVisit='yes';nextPage.scrollTop=0;}
    try{await refreshActive();if(seq===state.tabTransition)applyUiAssets();}catch(err){if(seq===state.tabTransition)toast('⚠ Não foi possível carregar esta aba. Tente novamente.');}
  }
  // Detalhes de Selos e Jogos usam o mesmo overlay de tela inteira dos Cards.
  function showProfileItemDetail(item,kind){
    const modal=$('cardModal'),pane=$('cardDetail');
    state.detailClosing=false;modal.classList.remove('detail-closing');
    modal.classList.add('favorite-fullscreen','profile-info-fullscreen');
    const isBadge=kind==='badge',isCollectible=kind==='collectible';
    modal.classList.toggle('collectible-fullscreen',isCollectible);
    const name=poroLegacyText(isBadge?item.title:item.name)||'Sem título';
    modal.querySelector('.card-detail-dialog').setAttribute('aria-label',`Detalhes de ${name}`);
    pane.replaceChildren();
    const art=h('div','profile-info-art');art.append(iconArtwork(item.image_url,item.icon||item.emoji||(isBadge?'🏅':isCollectible?'🏆':'🎮')));
    pane.append(art,h('h2','profile-info-name',name));
    if(isBadge){
      if(item.description)pane.append(h('p','profile-info-description',poroLegacyText(item.description)));
      const locked=Boolean(item.locked);
      pane.append(h('p','profile-info-status',locked?'🔒 Selo bloqueado':'✓ Selo desbloqueado'));
      if(Number.isFinite(Number(item.target)) && Number(item.target)>0){
        pane.append(h('p','profile-info-progress',`Progresso: ${Math.min(Number(item.target),Number(item.progress)||0)} / ${item.target}`));
      }
      if(item.available===false)pane.append(h('p','profile-info-note','Disponível em uma integração futura com o Discord.'));
    }else if(isCollectible){
      pane.append(h('p','profile-info-status','Colecionável do Poro'));
      if(item.description)pane.append(h('p','profile-info-description',poroLegacyText(item.description)));
      if(item.acquired_at){const d=new Date(item.acquired_at);if(!Number.isNaN(d.getTime()))pane.append(h('p','profile-info-note','Adquirido em: '+d.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric'})));}
      if(item.quantity!=null)pane.append(h('p','profile-info-note',`Quantidade na coleção: ${item.quantity}`));
    }else{
      pane.append(h('p','profile-info-status','Jogo favorito'));
      if(item.description)pane.append(h('p','profile-info-description',poroLegacyText(item.description)));
    }
    modal.hidden=false;
  }
  function makeProfileItemInteractive(chip,item,kind){
    chip.type='button';chip.title=poroLegacyText(kind==='badge'?item.title:item.name)||'Ver detalhes';
    chip.setAttribute('aria-label','Ver detalhes: '+chip.title);
    chip.addEventListener('click',()=>showProfileItemDetail(item,kind));
    if(chip.tagName!=='BUTTON'){
      chip.setAttribute('role','button');chip.tabIndex=0;
      chip.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();chip.click();}});
    }
    return chip;
  }

  async function loadProfileExtras(){
    const [ach,game,prefs]=await Promise.all([API('/api/achievements'),API('/api/game/config'),API('/api/games/preferences')]);state.game=game;
    if(!$('badgesSection')){const b=h('section','profile-badges');b.id='badgesSection';$('desktopLeftColumn').append(b);}
    const b=$('badgesSection');b.replaceChildren();
    const heading=h('div','badge-title');heading.append(h('strong','','🏅 Selos'),h('small','',`${ach.unlocked}/${ach.total} desbloqueados`));b.append(heading);
    const line=h('div','badge-strip');
    const visible=Math.max(8,state.badgesVisible||8);
    const shown=ach.items.slice(0,visible);
    for(const a of shown){const chip=h('button','badge-chip'+(a.locked?' locked':''));chip.append(iconArtwork(a.image_url,a.icon||'🏅'));makeProfileItemInteractive(chip,a,'badge');line.append(chip);}
    b.append(line);
    if(ach.items.length>8){
      const remaining=Math.max(0,ach.items.length-shown.length);
      const expanded=shown.length>=ach.items.length;
      const toggle=button(expanded?'Mostrar menos ↑':`Mais (${remaining}) ↓`,()=>{state.badgesVisible=expanded?8:Math.min(ach.items.length,shown.length+8);loadProfileExtras().catch(e=>toast(e.message));},'badge-more');
      toggle.setAttribute('aria-expanded',String(expanded));
      b.append(toggle);
    }
    // Gestão fica exclusivamente em Configurações; o servidor valida o acesso.
    $('settingsAdmin').hidden=!game.admin;
    let gamesSection=$('gamesSection');if(!gamesSection){gamesSection=h('section','profile-games');gamesSection.id='gamesSection';b.after(gamesSection);}
    gamesSection.replaceChildren();
    const head=h('div','badge-title');head.append(h('strong','','🎮 Jogos favoritos'),button('Editar',()=>editFavoriteGames(prefs),'game-edit'));gamesSection.append(head);
    const lineGames=h('div','game-icons');
    if(!prefs.selected.length)lineGames.append(h('p','', 'Escolha até cinco jogos para exibir no seu perfil.'));
    for(const g of prefs.selected){const chip=h('button','game-icon');chip.append(gameIcon(g));makeProfileItemInteractive(chip,g,'game');lineGames.append(chip);}
    gamesSection.append(lineGames);applyUiAssets();
    if(!state.discordWidgetStarted)startDiscordWidget();
    if(!state.petPreviewLoaded)loadPetPreview().catch(()=>{});
  }

  // Feed compartilhado: apenas eventos confirmados pela API. Nunca inserir HTML de usuários.
  let feedRefreshTimer=null;
  let feedLoading=false;
  function feedImageText(parent, item, kind){
    if(!item)return;
    const token=h('span','feed-entity '+(kind==='card'?'feed-rarity-'+String(item.rarity||'comum').normalize('NFD').replace(/[\u0300-\u036f]/g,''):'feed-pet-name'),(kind==='pet'?poroSpeciesName(item.name):item.name)||'Item');
    token.tabIndex=0;
    if(item.image_url){
      const preview=h('span','feed-preview');const img=h('img');img.src=item.image_url;img.loading='lazy';img.alt=item.name||'Prévia';preview.append(img);token.append(preview);
    }else if(item.emoji){const preview=h('span','feed-preview feed-emoji',item.emoji);token.append(preview);}
    parent.append(token);
  }
  function feedMessage(row,item){
    const d=item.data||{};const add=text=>row.append(document.createTextNode(text));
    const card=c=>feedImageText(row,c,'card');const pet=p=>feedImageText(row,p,'pet');
    if(item.kind==='expedition_start'){add(' enviou ');pet(d.pet);add(' para uma Expedição.');}
    else if(item.kind==='daily_card'){add(' conseguiu ');card(d.card);add(' no Resgate Diário.');}
    else if(item.kind==='pack_card'){add(' conseguiu ');card(d.card);add(' no Pack de '+(Number(d.pack_size)||'?')+' Cards.');}
    else if(item.kind==='expedition_card'){add(' teve seu Poro ');pet(d.pet);add(' retornando da Expedição com ');card(d.card);add('.');}
    else if(item.kind==='trade_cards'){add(' trocou ');card(d.card_a);add(' por ');card(d.card_b);add(' com '+(d.other||'outro membro')+'.');}
    else if(item.kind==='trade_coins'){add(' trocou ');card(d.card);add(' por '+(Number(d.coins)||0)+' moedas com '+(d.other||'outro membro')+'.');}
    else if(item.kind==='badge'){add(' conquistou o selo ');if(d.badge?.icon)add(d.badge.icon+' ');feedImageText(row,{name:d.badge?.name,image_url:d.badge?.image_url},'pet');add('!');}
  }
  async function loadFeed(){
    if(feedLoading||pendingFeedLikes.size)return;feedLoading=true;
    try{
      const data=await API('/api/feed');const list=$('feedList');if(!list)return;
      list.replaceChildren();$('feedCount').textContent=`${data.items.length} publicações recentes`;
      $('feedReward').textContent=`Moedas com likes hoje: ${data.reward_today}/20`;
      if(!data.items.length)list.append(h('div','feed-empty','Nenhuma novidade por enquanto.'));
      for(const item of data.items){
        const article=h('article','feed-entry');
        const pic=h('div','feed-avatar');avatar(pic,item.user.name,item.user.avatar_url);
        const box=h('div','feed-entry-body');const header=h('div','feed-head');
        header.append(h('strong','',item.user.name));
        const feedTimestamp=new Date(item.created_at);
        const feedClock=Number.isNaN(feedTimestamp.getTime())?'—':new Intl.DateTimeFormat('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(feedTimestamp);
        const time=h('time','feed-time',feedClock);time.dateTime=item.created_at;time.title='Horário de Brasília';header.append(time);
        const msg=h('p','feed-description');feedMessage(msg,item);
        const actions=h('div','feed-actions');const like=button(`${item.liked?'♥':'♡'} ${item.likes}`,async()=>{
          if(pendingFeedLikes.has(item.id)||item.liked)return;
          pendingFeedLikes.add(item.id);
          // Curtida visual otimista, revertida se o servidor recusar a operação.
          const before=like.textContent;
          like.textContent=`♥ ${Number(item.likes||0)+1}`;
          like.classList.add('is-liked','like-awaiting-confirmation');
          try{
            const ans=await API(`/api/feed/${item.id}/like`,{});
            item.liked=!!ans.liked;item.likes=Number(item.likes||0)+(ans.liked?1:0);
            like.textContent=`${item.liked?'♥':'♡'} ${item.likes}`;
            like.classList.toggle('is-liked',item.liked);
            if(Number.isFinite(Number(ans.reward_today))){
              $('feedReward').textContent=`Moedas com likes hoje: ${ans.reward_today}/20`;
            }
            if(ans.coins_gained){applyConfirmedCoins(ans);toast('+1 moeda por curtir!');}
            resetCachedData();
          }catch(err){
            like.textContent=before;like.classList.remove('is-liked');
            toast('⚠ '+(err?.message||'Não foi possível curtir.'));
            resetCachedData();reconcileAfterAction();
          }finally{
            pendingFeedLikes.delete(item.id);
            like.classList.remove('like-awaiting-confirmation');
            like.dataset.keepDisabled=item.liked?'1':'';
            if(item.liked){like.disabled=true;like.title='Você já curtiu esta publicação';}
          }
        },'feed-like'+(item.liked?' is-liked':''));
        like.setAttribute('aria-label',item.mine?'Não é possível curtir publicação própria':'Curtir publicação; '+item.likes+' curtidas');
        if(item.mine||item.liked){like.disabled=true;like.dataset.keepDisabled='1';like.title=item.mine?'Você não pode curtir sua própria publicação':'Você já curtiu esta publicação';if(item.mine)like.classList.add('feed-like-own');}
        actions.append(like);
        box.append(header,msg,actions);article.append(pic,box);list.append(article);
      }
    }finally{feedLoading=false;}
  }
  async function loadFeedRefresh(){feedLoading=false;await loadFeed();}
  function startFeedPolling(){if(feedRefreshTimer)return;feedRefreshTimer=setInterval(()=>{if(state.tab==='feed'&&!document.hidden&&state.account)loadFeed().catch(()=>{});},12000);}
  // Recanto 0.1.18: gesto pull-to-refresh com deslocamento visual e indicador.
  // Só intercepta arrasto vertical para baixo iniciado no topo; o swipe entre abas permanece.
  function startMobileGestures(){
    const home=$('homeScreen');
    const indicator=$('pullRefreshIndicator');
    let start=null;
    let refreshing=false;
    let activeTarget=null;
    const isMobile=()=>matchMedia('(max-width:767px)').matches;
    const currentPage=()=>state.tab==='perfil' ? $('profileContent') : ({
      feed:$('feedScreen'),missoes:$('missionsScreen'),inventario:$('inventoryScreen'),
      cards:$('cardsScreen'),pet:$('petScreen'),loja:$('shopScreen')
    })[state.tab];
    const paintPull=(distance,status='pulling')=>{
      if(!activeTarget)return;
      activeTarget.classList.add('recanto-pull-target');
      activeTarget.style.transform=`translate3d(0,${Math.round(distance)}px,0)`;
      indicator.classList.add('pull-visible');
      indicator.classList.toggle('pull-refreshing',status==='refreshing');
      indicator.classList.toggle('pull-ready',status==='ready');
      indicator.style.setProperty('--pull-motion',`${Math.round(Math.min(distance*.6,48))}px`);
      indicator.setAttribute('aria-label',status==='refreshing'?'Atualizando':'Puxe para atualizar');
    };
    const resetPull=()=>{
      if(activeTarget){
        const target=activeTarget;
        target.classList.add('recanto-pull-return');
        target.style.transform='translate3d(0,0,0)';
        setTimeout(()=>{target.classList.remove('recanto-pull-return','recanto-pull-target');target.style.transform='';},280);
      }
      indicator.classList.remove('pull-visible','pull-ready','pull-refreshing');
      indicator.style.removeProperty('--pull-motion');
      activeTarget=null;
    };
    home.addEventListener('touchstart',e=>{
      if(refreshing||e.touches.length!==1||!state.account||!isMobile()||
         !$('modal').hidden||!$('adminModal').hidden||!$('publicProfilePage').hidden||!$('profilesModal').hidden||
         e.target.closest('input,textarea,select,button,a,[role="dialog"],.card-grid,.mini-tabs,.badge-strip')){
        start=null;return;
      }
      const t=e.touches[0];
      const scroll=e.target.closest('.scroll-content,#profileContent,.content-page');
      start={x:t.clientX,y:t.clientY,atTop:(!scroll||scroll.scrollTop<=2),scroll,pulling:false,distance:0};
    },{passive:true});
    home.addEventListener('touchmove',e=>{
      if(!start||e.touches.length!==1||!isMobile())return;
      const t=e.touches[0];
      const dx=t.clientX-start.x,dy=t.clientY-start.y;
      if(!start.pulling){
        if(!start.atTop||dy<8||Math.abs(dy)<Math.abs(dx)*1.2)return;
        if(start.scroll&&start.scroll.scrollTop>2)return;
        activeTarget=currentPage();
        if(!activeTarget)return;
        activeTarget.classList.remove('recanto-pull-return');
        start.pulling=true;
      }
      if(e.cancelable)e.preventDefault();
      // Atrito progressivo, distancia maxima de 100px para nao encobrir outros controles.
      start.distance=Math.min(100,Math.max(0,dy)*.54);
      paintPull(start.distance,start.distance>=65?'ready':'pulling');
    },{passive:false});
    home.addEventListener('touchend',e=>{
      if(!start||!e.changedTouches.length)return;
      const touch=e.changedTouches[0];
      const dx=touch.clientX-start.x,dy=touch.clientY-start.y;
      const pulled=start.pulling,amount=start.distance,atTop=start.atTop;
      start=null;
      if(pulled){
        if(amount<65){resetPull();return;}
        refreshing=true;
        paintPull(56,'refreshing');
        const startedTab=state.tab;
        (async()=>{
          try{
            resetCachedData();
            await refreshProfile();
            if(state.account&&state.tab===startedTab)await refreshActive(true);
            toast('Atualizado!');
          }catch(_){toast('Não foi possível atualizar agora.');}
          finally{refreshing=false;resetPull();}
        })();
        return;
      }
      if(Math.abs(dx)>85&&Math.abs(dx)>Math.abs(dy)*1.55){
        const index=MOBILE_TAB_ORDER.indexOf(state.tab);
        const next=MOBILE_TAB_ORDER[index+(dx>0?-1:1)];
        if(next){registerSwipeDiscovery();chooseTab(next,null,dx<0?1:-1);}
      }else if(dy>110&&Math.abs(dy)>Math.abs(dx)*1.5&&atTop){
        // Fallback se touchmove nao foi entregue pelo navegador.
        resetCachedData();
        refreshProfile().then(()=>refreshActive(true)).catch(()=>toast('Não foi possível atualizar agora.'));
      }
    },{passive:true});
    home.addEventListener('touchcancel',()=>{start=null;if(!refreshing)resetPull();},{passive:true});
  }
  function startDiscordWidget(){
    const iframe=$('discordServerFrame');
    if(!iframe || state.discordWidgetStarted)return;
    state.discordWidgetStarted=true;
    const begin=()=>{if(iframe.src==='about:blank')iframe.src='https://discord.com/widget?id=958567158479208458&theme=dark';};
    if('IntersectionObserver' in window){
      const watcher=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){watcher.disconnect();begin();}},{rootMargin:'220px'});
      watcher.observe($('discordWidgetSection'));
    }else begin();
  }
  // O colecionável acompanha o retrato, não o avatar do usuário. É visível para visitantes.
  function petPortrait(species,large=false,thumbnail=false){
    const view=petVisual(species,large,thumbnail);
    const equipped=species?.equipped_collectible;
    if(equipped){
      const chip=h('button','poro-equipped-chip');chip.type='button';
      chip.title='Ver item equipado: '+equipped.name;
      chip.setAttribute('aria-label','Ver item equipado no Poro: '+equipped.name);
      chip.append(iconArtwork(equipped.image_url,equipped.emoji||'🏆'));
      chip.addEventListener('click',event=>{event.stopPropagation();showProfileItemDetail(equipped,'collectible');});
      view.append(chip);
    }
    return view;
  }
  async function loadPetPreview(){
    // Opcional e paralelo: a página inicial não fica bloqueada aguardando o pet.
    if(state.petPreviewLoading)return;
    state.petPreviewLoading=true;
    const content=$('desktopPetPreview');
    try{
      const data=await API('/api/pets');
      const pet=data.pet;content.replaceChildren();
      const mobile=$('mobilePetPreview');if(mobile)mobile.replaceChildren();
      if(!pet){content.append(h('p','', 'Você ainda não adotou um Poro.'));if(mobile)mobile.closest('.mobile-pet-widget').hidden=true;state.petPreviewLoaded=true;return;}
      content.append(petPortrait(pet,false));
      content.append(h('p','desktop-pet-name',pet.nickname||poroSpeciesName(pet.name)));
      if(mobile){mobile.closest('.mobile-pet-widget').hidden=false;mobile.append(petPortrait(pet,false,true),h('strong','',pet.nickname||poroSpeciesName(pet.name)),h('span','',pet.status==='missao'?'Em expedição':pet.status==='ativo'?'Em casa':pet.status==='vet'?'No veterinário':'Falecido'));}
      content.append(h('p','',pet.status==='ativo'?'Em casa':pet.status==='vet'?'No veterinário':pet.status==='missao'?'Em missão':'Falecido'));
      for(const [label,val] of [['Bem-estar',pet.happiness],['Fome',pet.food]]){
        if(val==null)continue;
        const row=h('div','desktop-pet-metric');row.append(h('span','',label),h('span','',`${val}/100`));
        const meter=h('div','desktop-pet-meter');const fill=h('span');fill.style.width=`${Math.max(0,Math.min(100,Number(val)||0))}%`;meter.append(fill);
        content.append(row,meter);
      }
      state.petPreviewLoaded=true;
    }catch(_){content.replaceChildren(h('p','', 'Poro temporariamente indisponível. Abra a aba Poros para tentar novamente.'));}
    finally{state.petPreviewLoading=false;}
  }

  async function editFavoriteGames(prefs){
    const pane=$('profilesPane');$('profilesModal').hidden=false;pane.replaceChildren(h('h3','','Meus jogos favoritos'),h('p','','Selecione até 5 jogos.'));
    const selected=new Set(prefs.selected.map(g=>g.id));const grid=h('div','game-choices');
    for(const game of prefs.catalog){const btn=button('',()=>{if(selected.has(game.id))selected.delete(game.id);else if(selected.size<5)selected.add(game.id);else{toast('Escolha no máximo 5 jogos.');return;}btn.classList.toggle('selected',selected.has(game.id));},'game-choice'+(selected.has(game.id)?' selected':''));
      const icon=h('span','game-choice-icon');icon.append(gameIcon(game));btn.append(icon,h('span','',game.name));grid.append(btn);}
    const actions=h('div','game-choice-actions');
    actions.append(button('Salvar jogos',async()=>{const result=await safeRun(()=>API('/api/games/preferences',{games:[...selected]}),'Jogos favoritos atualizados!');if(result){$('profilesModal').hidden=true;await loadProfileExtras();}}),button('Voltar',()=>{$('profilesModal').hidden=true;},'soft-action'));
    pane.append(grid,actions);
  }
    function cardTile(item,onClick){
    const tile=h('div','card-tile tier-'+item.rarity);tile.setAttribute('role','button');tile.tabIndex=0;
    const art=h('div','card-art');if(item.image_url){const im=h('img');im.src=item.image_url;im.alt=item.name;im.loading='lazy';art.append(im);}else art.textContent='✦';
    tile.append(art,h('strong','',item.name),h('small','',tierLabels[item.rarity]||item.rarity));
    if(item.is_favorite)tile.append(h('span','fav-mark','★ Favorito'));
    tile.addEventListener('click',()=>{if(onClick)onClick(item);});
    tile.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();if(onClick)onClick(item);}});
    return tile;
  }
  function showCard(item,extra='',favoriteFullscreen=false){
    const p=$('cardDetail');p.replaceChildren();const modal=$('cardModal');modal.classList.remove('detail-closing','profile-info-fullscreen','collectible-fullscreen');modal.querySelector('.card-detail-dialog').setAttribute('aria-label','Detalhes do card');modal.classList.toggle('favorite-fullscreen',favoriteFullscreen);state.detailClosing=false;
    const art=h('div','detail-art tier-'+item.rarity);if(item.image_url){const img=h('img');img.src=item.image_url;img.alt=item.name;art.append(img);}else art.textContent='✦';
    p.append(art,h('h2','',item.name),h('p','',tierLabels[item.rarity]||item.rarity));
    if(item.collection)p.append(h('p','detail-meta',`Coleção: ${item.collection}`));
    if(extra)p.append(h('p','detail-meta',extra));
    const actions=h('div','detail-actions');
    if(item.owned_id)actions.append(button(item.is_favorite?'★ Remover favorito':'☆ Favoritar card',async()=>{const result=await safeRun(()=>API('/api/cards/favorite',{owned_id:item.is_favorite?null:item.owned_id}),'Favorito atualizado!');if(result){closeCardDetail();renderProfile(state.account);}}));
    if(item.owned_id && (item.duplicate_count||0)>1){
      actions.append(button('Vender cópia extra',async()=>{
        const economy=await API('/api/card-economy');const price=economy.duplicate_sale[item.rarity];
        if(!confirm(`Vender uma cópia de ${item.name} por ${price} moedas?`))return;
        const result=await safeRun(()=>API('/api/cards/sell-duplicate',{owned_id:item.owned_id}),`+${price} moedas recebidas!`);
        if(result)closeCardDetail();
      },'soft-action'));
    }
    p.append(actions);modal.hidden=false;
  }
  async function closeCardDetail(){
    const modal=$('cardModal');if(modal.hidden||state.detailClosing)return;
    state.detailClosing=true;
    if(!matchMedia('(prefers-reduced-motion: reduce)').matches&&typeof modal.animate==='function'){
      const panel=modal.querySelector('.card-detail-dialog');
      await Promise.all([
        panel.animate([{opacity:1,transform:'scale(1)'},{opacity:0,transform:'scale(.91)'}],{duration:230,easing:'cubic-bezier(.4,0,1,1)'}).finished.catch(()=>{}),
        modal.animate([{opacity:1},{opacity:0}],{duration:230,easing:'ease-in'}).finished.catch(()=>{})]);
    }
    modal.hidden=true;state.detailClosing=false;
  }
    async function loadCards(){const [daily,game]=await Promise.all([API('/api/daily/status'),API('/api/game/config')]);state.game=game;state.reset=daily.next_reset;state.cardReset=daily.card_next_at;$('dailyCard').disabled=daily.card_claimed;$('dailyCard').textContent=daily.card_claimed?'⏳ Aguardar 5h':'Resgatar card';$('dailyCardIcon').classList.toggle('card-icon-available',!daily.card_claimed);updateCountdowns();await cardPane(state.cardTab);}
  function renderCardFilters(items,ownedIds,tab,container){
    const host=$('cardFilters');host.replaceChildren();host.hidden=false;
    const filters=state.cardFilters;
    const line=h('div','filters-top');
    const chooser=(name,value,options,callback)=>{const wrapper=h('label','filter-label');wrapper.append(h('span','',name));const select=h('select','select-input');for(const [v,txt] of options){const opt=h('option','',txt);opt.value=v;select.append(opt);}select.value=value;select.addEventListener('change',()=>callback(select.value));wrapper.append(select);return wrapper;};
    const rerender=()=>{state.cardPage=1;paintCardGrid(items,ownedIds,tab,container);};
    line.append(chooser('Raridade',filters.rarity,[['todos','Todas'],...Object.entries(tierLabels)],v=>{filters.rarity=v;rerender();}));
    const collections=[...new Set([...items.map(c=>c.collection||'Recanto Original'),'Celebridades','Personagens','Memes',filters.collection].filter(c=>c!=='todas'))].sort((a,b)=>a.localeCompare(b,'pt-BR'));
    if(filters.collection!=='todas'&&!collections.includes(filters.collection))filters.collection='todas';
    line.append(chooser('Coleção',filters.collection,[['todas','Todas as coleções'],...collections.map(v=>[v,v])],v=>{filters.collection=v;rerender();}));
    line.append(chooser('Ordem',filters.alphabetical,[['raridade','Mais raros primeiro'],['padrao','Recentes / Catálogo'],['az','Alfabético A–Z'],['za','Alfabético Z–A']],v=>{filters.alphabetical=v;rerender();}));
    host.append(line);
    const checks=h('div','filters-checks');
    const toggle=(name,key,enabled=true)=>{const label=h('label','filter-check');const cb=h('input');cb.type='checkbox';cb.checked=!!filters[key];cb.disabled=!enabled;cb.addEventListener('change',()=>{filters[key]=cb.checked;rerender();});label.append(cb,h('span','',name));return label;};
    checks.append(toggle('Não obtidos','missing',tab==='catalogo'),toggle('Novos (7 dias)','newOnly'));
    host.append(checks);rerender();
  }
  function paintCardGrid(items,ownedIds,tab,container){
    container.replaceChildren();const f=state.cardFilters;const week=Date.now()-7*24*60*60*1000;
    let list=items.filter(c=>(f.rarity==='todos'||c.rarity===f.rarity)&&(f.collection==='todas'||(c.collection||'Recanto Original')===f.collection));
    if(f.missing&&tab==='catalogo')list=list.filter(c=>!ownedIds.has(c.id));
    if(f.newOnly)list=list.filter(c=>{const date=c.acquired_at||c.created_at;return date&&new Date(date).getTime()>=week;});
    if(f.alphabetical==='az'||f.alphabetical==='za')list=list.slice().sort((a,b)=>a.name.localeCompare(b.name,'pt-BR')*(f.alphabetical==='za'?-1:1));
    if(f.alphabetical==='raridade'){
      const ranks={'prismático':4,'prismatico':4,'lendário':3,'lendario':3,'raro':2,'comum':1};
      list=list.slice().sort((a,b)=>(ranks[b.rarity]||0)-(ranks[a.rarity]||0)||a.name.localeCompare(b.name,'pt-BR'));
    }
    if(!list.length)container.append(block('Nenhum card encontrado','Altere os filtros para encontrar outros cards.'));
    // Uma mesma paginacao leve no PC e no celular: nao montar todo o catalogo de uma vez.
    const pageSize=state.cardPageSize;
    const pages=Math.max(1,Math.ceil(list.length/pageSize));
    state.cardPage=Math.min(Math.max(1,state.cardPage),pages);
    const start=(state.cardPage-1)*pageSize;
    const grid=h('div','card-grid');
    for(const item of list.slice(start,start+pageSize)){grid.append(cardTile(item,c=>{
      if(tab==='catalogo'){const owners=c.owners.map(o=>`${o.name}: ${o.count}`).join(' · ');showCard(c,`${c.minted}/${c.max_copies} cópias distribuídas. Donos: ${owners||'nenhum'}`);}
      else showCard(c,`Exemplar #${c.owned_id}`);
    }));}
    container.append(grid);
    if(list.length>pageSize){
      const nav=h('nav','card-pagination');nav.setAttribute('aria-label','Páginas de cards');
      const changePage=(nextPage)=>{
        state.cardPage=nextPage;
        paintCardGrid(items,ownedIds,tab,container);
        // Avanca para os cards da pagina nova, preservando os filtros acima.
        const scrollArea=container.closest('.scroll-content');
        if(scrollArea){
          const top=scrollArea.scrollTop+container.getBoundingClientRect().top-scrollArea.getBoundingClientRect().top-10;
          scrollArea.scrollTo({top:Math.max(0,top),behavior:'auto'});
        }
      };
      const previous=button('← Anterior',()=>changePage(state.cardPage-1),'soft-action');previous.disabled=state.cardPage===1;
      const caption=h('span','card-pagination-label',`Página ${state.cardPage} de ${pages} · ${list.length} cards`);
      const next=button('Próxima →',()=>changePage(state.cardPage+1),'soft-action');next.disabled=state.cardPage===pages;
      nav.append(previous,caption,next);container.append(nav);
    }
  }
  let currentCardPaneRequest=0;
  async function cardPane(tab){
    const requestId=++currentCardPaneRequest;
    if(state.cardTab!==tab)state.cardPage=1;
    state.cardTab=tab;document.querySelectorAll('[data-card-tab]').forEach(el=>el.classList.toggle('mini-active',el.dataset.cardTab===tab));
    const p=$('cardsPane');p.replaceChildren();p.dataset.mode=tab;$('cardFilters').hidden=tab==='trocas';
    if(tab==='colecao'){
      const [data,fav]=await Promise.all([API('/api/cards'),API('/api/cards/favorite')]);
      const counts={};for(const c of data.items)counts[c.card_id]=(counts[c.card_id]||0)+1;
      for(const c of data.items){c.is_favorite=c.owned_id===fav.card?.owned_id;c.duplicate_count=counts[c.card_id];}
      $('cardsCount').textContent=`${data.total} card(s)`;
      if(!data.items.length)p.append(block('Sua coleção está vazia','Resgate seu card diário ou compre pacotes na Loja.'));
      const results=h('div','filtered-cards');p.append(results);renderCardFilters(data.items,new Set(data.items.map(c=>c.card_id)),'colecao',results);
      p.append(button('Ir para Loja →',()=>chooseTab('loja','pack3'),'soft-action'));
    }
    if(tab==='catalogo'){
      const [data,mine]=await Promise.all([API('/api/catalog'),API('/api/cards')]);
      $('cardsCount').textContent=`${data.items.length} cards no catálogo`;
      const catalogIntro=h('div','catalog-highlights');
      const catalogSummary=block('Todos os cards','Limites globais: Comum 3 • Raro 2 • Lendário 1 • Prismático 1.');
      catalogSummary.classList.add('catalog-summary');catalogIntro.append(catalogSummary);
      const featured=await API('/api/collections/featured');
      const banner=h('button','featured-collection-banner');banner.type='button';
      if(featured.image_url){banner.style.backgroundImage=`linear-gradient(90deg,rgba(19,24,88,.78),rgba(19,24,88,.12)),url("${featured.image_url.replaceAll('"','%22')}")`;}
      banner.append(h('small','','✦ COLEÇÃO EM DESTAQUE'),h('strong','',featured.name),h('span','','Ver os cards desta coleção →'));
      banner.onclick=()=>{state.cardFilters.collection=featured.name;state.cardPage=1;cardPane('catalogo').catch(e=>toast(e.message));};
      catalogIntro.append(banner);p.append(catalogIntro);
      const results=h('div','filtered-cards');p.append(results);renderCardFilters(data.items,new Set(mine.items.map(c=>c.card_id)),'catalogo',results);
    }
    if(tab==='trocas'){
      const [community,trades,mine]=await Promise.all([API('/api/community'),API('/api/trades'),API('/api/cards')]);if(requestId!==currentCardPaneRequest||state.cardTab!==tab)return;$('cardsCount').textContent='Negociações';
      const form=block('Propor uma troca','Escolha um membro e indique a carta sua e a carta dele. A troca só acontece quando a outra pessoa aceitar.');
      const members=community.members.filter(m=>m.cards.length);const mineCards=mine.items;
      if(members.length&&mineCards.length){
        const memberSelect=h('select','select-input');members.forEach(m=>{const o=h('option','',m.name);o.value=m.key;memberSelect.append(o);});
        const mySelect=h('select','select-input');mineCards.forEach(c=>{const o=h('option','',c.name+' — '+c.rarity+' #'+c.owned_id);o.value=c.owned_id;mySelect.append(o);});
        const theirs=h('select','select-input');const update=()=>{theirs.replaceChildren();const mem=members.find(m=>m.key===memberSelect.value);(mem?.cards||[]).forEach(c=>{const o=h('option','',c.name+' — '+c.rarity+' #'+c.owned_id);o.value=c.owned_id;theirs.append(o);});};memberSelect.addEventListener('change',update);update();
        form.append(h('label','','Membro'),memberSelect,h('label','','Sua carta'),mySelect,h('label','','Carta desejada'),theirs,button('Enviar proposta',()=>safeRun(()=>API('/api/trades',{to_user:memberSelect.value,offered_owned_id:Number(mySelect.value),wanted_owned_id:Number(theirs.value)}),'Proposta enviada!')));
      }else form.append(h('p','',mineCards.length?'Ainda não há outros jogadores com cartas cadastradas.':'Primeiro obtenha um card para oferecer.'));
      const tradeColumns=h('div','trade-columns');const tradeProposals=h('section','trade-section');const tradeOffers=h('section','trade-section');
      tradeProposals.append(form);
      const proposalHistory=h('div','trade-history-group');proposalHistory.append(h('h3','section-heading','Minhas propostas'));
      if(!trades.items.length)proposalHistory.append(block('Sem propostas','As negociações aparecerão aqui.'));
      for(const t of trades.items){const row=block(`${t.from_name} ↔ ${t.to_name}`,`${t.offered?.name||'Card'} ↔ ${t.wanted?.name||'Card'} · ${t.status}`);row.classList.add('trade-row');if(t.can_accept){row.append(button('Aceitar',()=>actTrade(t.id,'accept')));row.append(button('Recusar',()=>actTrade(t.id,'reject'),'soft-action'));}if(t.can_cancel)row.append(button('Cancelar proposta',()=>actTrade(t.id,'cancel'),'soft-action'));proposalHistory.append(row);}
      const [offers,eco]=await Promise.all([API('/api/coin-offers'),API('/api/card-economy')]);if(requestId!==currentCardPaneRequest||state.cardTab!==tab)return;
      const prices=Object.entries(eco.minimum_offers).map(([tier,v])=>`${tierLabels[tier]}: ${v}`).join(' • ');
      const bid=block('Oferecer moedas por card',`Valores mínimos: ${prices}. A oferta reserva suas moedas até a decisão do dono.`);
      const candidates=community.members.filter(m=>m.cards.length);
      if(candidates.length){
        const selectMember=h('select','select-input');for(const m of candidates){const op=h('option','',m.name);op.value=m.key;selectMember.append(op);}
        const selectCard=h('select','select-input'),value=h('input','text-input');value.type='number';value.step='1';value.min='1';
        const update=()=>{selectCard.replaceChildren();const other=candidates.find(m=>m.key===selectMember.value);for(const c of other?.cards||[]){const op=h('option','',`${c.name} (${tierLabels[c.rarity]})`);op.value=String(c.owned_id);op.dataset.tier=c.rarity;selectCard.append(op);}calc();};
        const calc=()=>{const tier=selectCard.selectedOptions[0]?.dataset.tier||'comum';value.min=String(eco.minimum_offers[tier]);value.value=String(eco.minimum_offers[tier]);};
        selectMember.onchange=update;selectCard.onchange=calc;update();
        bid.append(h('label','','Quem receberá a oferta'),selectMember,h('label','','Card desejado'),selectCard,h('label','','Moedas ofertadas'),value,
          button('Enviar oferta em moedas',()=>safeRun(()=>API('/api/coin-offers',{to_user:selectMember.value,wanted_owned_id:Number(selectCard.value),amount:Number(value.value)}),'Oferta enviada e moedas reservadas!')));
      }else bid.append(h('p','','Ainda não há cartas disponíveis de outros membros.'));
      tradeOffers.append(bid);const offerHistory=h('div','trade-history-group');offerHistory.append(h('h3','section-heading','Ofertas de moedas'));
      if(!offers.items.length)offerHistory.append(block('Nenhuma oferta','As propostas em moedas aparecerão aqui.'));
      for(const offer of offers.items){const row=block(`${offer.buyer_name} → ${offer.seller_name}`,`${offer.card_name} • ${money(offer.amount)} moedas • ${offer.status}`);
        if(offer.can_accept){row.append(button('Aceitar oferta',()=>decideCoinOffer(offer.id,'accept')));row.append(button('Recusar',()=>decideCoinOffer(offer.id,'reject'),'soft-action'));}
        if(offer.can_cancel)row.append(button('Cancelar e receber reembolso',()=>decideCoinOffer(offer.id,'cancel'),'soft-action'));
        offerHistory.append(row);
      }
      const pending=h('section','trade-section trade-pending');
      pending.append(proposalHistory,offerHistory);
      tradeColumns.append(tradeProposals,tradeOffers,pending);p.replaceChildren(tradeColumns);
    }
  }
    async function decideCoinOffer(id,action){await safeRun(()=>API(`/api/coin-offers/${id}/decide`,{action}),'Oferta atualizada!');}
    async function actTrade(id,action){await safeRun(()=>API(`/api/trades/${id}/decide`,{action}),action==='accept'?'Troca concluída!':'Proposta atualizada.');}
  async function loadInventory(){
    const data=await API('/api/inventory');$('inventorySummary').textContent=`${data.packs.length} pacote(s) · ${(data.collectibles||[]).length} colecionável(is)`;
    await inventoryPane(state.inventoryTab,data);
  }
  async function inventoryPane(tab,data=null){
    state.inventoryTab=tab;document.querySelectorAll('[data-inventory-tab]').forEach(b=>b.classList.toggle('mini-active',b.dataset.inventoryTab===tab));
    const d=data||await API('/api/inventory');const pane=$('inventoryPane');pane.replaceChildren();
    if(tab==='packs'){
      if(!d.packs?.length)pane.append(block('Nenhum pacote fechado','Pacotes comprados ficam aqui até serem abertos.'));
      for(const pack of d.packs||[]){const row=h('div','inventory-row');row.append(mediaCover(pack.image_url,pack.amount===5?'🎴':'🃏','Pacote '+pack.amount,'item-cover'));
        const info=h('div','inventory-meta');info.append(h('strong','',`Pacote de ${pack.amount} cards`),h('p','','Revelação em tela cheia'));
        row.append(info,button('Abrir',()=>openPack(pack.id)));pane.append(row);}
      pane.append(button('Ver pacotes na Loja →',()=>chooseTab('loja','pack3'),'soft-action'));
    }else if(tab==='petiscos'){
      if(!d.treats?.length)pane.append(block('Sem itens para Poros','Compre alimentos e vacinas na Loja.'));
      for(const t of d.treats||[]){const row=h('div','inventory-row');row.append(mediaCover(t.image_url,t.emoji,t.name,'item-cover'));
        const info=h('div','inventory-meta');info.append(h('strong','',t.name),h('p','',`${t.quantity} disponível(is)${t.food?' • +'+t.food+' fome':''}`));row.append(info);
        if(t.sku==='vacina')row.append(button('Usar vacina',()=>safeRun(()=>API('/api/pets/vaccinate',{}),'Poro recuperado no veterinário!'),'soft-action'));
        else row.append(button('Presentear',()=>giftDialog(t),'soft-action'));
        pane.append(row);}
      pane.append(button('Ver itens na Loja →',()=>chooseTab('loja','treat3'),'soft-action'));
    }else if(tab==='colecionaveis'){
      if(!d.collectibles?.length)pane.append(block('Nenhum colecionável','Itens especiais encontrados nas expedições aparecerão aqui.'));
      const grid=h('div','collectible-grid');
      for(const item of d.collectibles||[]){const tile=h('article','collectible-item');tile.append(mediaCover(item.image_url,item.emoji,item.name,'collectible-art'),h('strong','',item.name),h('small','',`Quantidade: ${item.quantity}`));
        if(item.description)tile.append(h('p','',item.description));
        const controls=h('div','collectible-actions');
        controls.append(button('Ver detalhes',()=>showProfileItemDetail(item,'collectible'),'soft-action'));
        controls.append(button('Equipar no Poro',()=>safeRun(()=>API('/api/pets/equip-collectible',{collectible_id:item.id}),'Item equipado no seu Poro!')));
        tile.append(controls);grid.append(tile);}
      pane.append(grid);
    }
  }
  async function giftDialog(item){
    try{const data=await API('/api/community/profiles');const choices=data.members;
      if(!choices.length){toast('Não há outros membros cadastrados para presentear.');return;}
      const wrap=$('profilesPane');$('profilesModal').hidden=false;wrap.replaceChildren(h('h3','','Presentear '+item.name));
      const select=h('select','select-input');choices.forEach(x=>{const opt=h('option','',x.name);opt.value=x.key;select.append(opt);});
      const num=h('input','text-input');num.type='number';num.min='1';num.max=String(item.quantity);num.value='1';
      wrap.append(h('p','','Escolha quem receberá os petiscos no inventário.'),select,h('p','','Quantidade'),num,
        button('Enviar presente',async()=>{const result=await safeRun(()=>API('/api/inventory/gift',{to_user:select.value,sku:item.sku,quantity:Number(num.value)}),'Presente enviado!');if(result){$('profilesModal').hidden=true;await loadInventory();}}),
        button('Voltar ao inventário',()=>{$('profilesModal').hidden=true;},'soft-action'));
    }catch(err){toast(err.message);}
  }
  async function openPack(id){
    const result=await safeRun(()=>API('/api/inventory/packs/'+id+'/open',{}));
    if(!result)return;
    state.reveal=result.cards;state.revealBonus=result.bonus_coins;state.revealIndex=0;state.revealFace=false;
    $('packReveal').hidden=false;showRevealStep();
  }
  function showRevealStep(){
    const cards=state.reveal||[];const index=state.revealIndex;
    const modal=$('packReveal');const flip=$('flipCard');const front=$('flipFront');
    flip.classList.remove('is-revealed');modal.className='pack-reveal';state.revealFace=false;
    $('revealExit').hidden=true;
    if(index>=cards.length){$('flipStage').hidden=true;$('revealHint').textContent='Pacote completo!';
      $('revealCounter').textContent=`🪙 +${state.revealBonus||0} moedas · `+cards.map(c=>c.name).join(' · ');
      $('revealNext').hidden=true;$('revealExit').hidden=false;return;}
    $('flipStage').hidden=false;$('revealNext').hidden=false;
    front.replaceChildren();const c=cards[index];
    if(c.image_url){const img=h('img');img.src=c.image_url;img.alt=c.name;front.append(img);}else front.append(h('div','', '✦'));
    front.append(h('span','reveal-caption',c.name+' · '+(tierLabels[c.rarity]||c.rarity)));
    $('revealHint').textContent='Card '+(index+1)+' de '+cards.length;
    $('revealCounter').textContent='Toque para revelar';$('revealNext').textContent='Revelar card';
    requestAnimationFrame(()=>{flip.classList.remove('is-revealed');});
  }
  function revealNext(){const cards=state.reveal;if(!cards||!cards.length)return;
    const card=cards[state.revealIndex];if(!card)return;
    if(!state.revealFace){state.revealFace=true;$('packReveal').className='pack-reveal tier-'+card.rarity;
      $('flipCard').classList.add('is-revealed');$('revealCounter').textContent=(tierLabels[card.rarity]||card.rarity)+` · 🪙 +${card.bonus_coins||0} moeda(s)`;
      $('revealNext').textContent=state.revealIndex===cards.length-1?'Ver resumo':'Próximo card';
    }else{state.revealIndex++;showRevealStep();}
  }
  async function searchProfiles(){
    $('profilesModal').hidden=false;const pane=$('profilesPane');pane.replaceChildren();
    const input=h('input','profiles-search');input.placeholder='Buscar por nome...';input.setAttribute('aria-label','Buscar usuários');pane.append(input);
    const results=h('div');pane.append(results);
    async function search(){try{const d=await API('/api/community/profiles?q='+encodeURIComponent(input.value));results.replaceChildren();
      if(!d.members.length)results.append(h('p','','Nenhum perfil encontrado.'));
      d.members.forEach(m=>{const row=h('button','profile-result');if(m.avatar_url){const img=h('img');img.src=m.avatar_url;img.alt=m.name;row.append(img);}else row.append(h('span','profile-thumb','◉'));
        const info=h('div');info.append(h('strong','',m.name),h('small','',m.card_count+' cards'));row.append(info);
        row.addEventListener('click',()=>openPublicProfile(m.key));results.append(row);});
    }catch(err){toast(err.message);}}
    let seq=0;input.addEventListener('input',()=>{const n=++seq;setTimeout(()=>{if(n===seq)search();},250);});await search();
  }
  // Todos os exemplares do perfil visitado ficam abaixo do Poro.
  // Reutilizamos a visualização dos Cards, sem qualquer ação sobre itens alheios.
  function publicMemberCardsSection(profile){
    const cards=Array.isArray(profile.collection_cards)?profile.collection_cards:[];
    const section=block('🃏 Cards de '+profile.name);
    section.classList.add('public-section','public-member-cards');
    section.append(h('p','public-member-cards-count',cards.length+' card(s) na coleção'));
    if(!cards.length){
      section.append(h('p','public-member-cards-empty','Este membro ainda não possui Cards.'));
      return section;
    }
    const grid=h('div','public-member-cards-grid');
    for(const owned of cards){
      // Não receber/exibir o ID da posse evita botões como favoritar e vender.
      const card={card_id:owned.card_id,name:owned.name,rarity:owned.rarity,
                  image_url:owned.image_url,collection:owned.collection};
      const tile=cardTile(card,()=>showCard(card,'Card de '+profile.name,true));
      tile.setAttribute('aria-label','Ver '+card.name+' em tela cheia');
      grid.append(tile);
    }
    section.append(grid);
    return section;
  }
  async function openPublicProfile(uid){
    try{
      const [d,items]=await Promise.all([API('/api/community/profiles/'+encodeURIComponent(uid)),API('/api/inventory')]);
      $('profilesModal').hidden=true;$('publicProfilePage').hidden=false;
      const pane=$('publicProfileContent');pane.replaceChildren();
      // No celular, preservar a composição 0.1.4 já aprovada; o dashboard vale apenas para PC.
      if(!matchMedia('(min-width:768px)').matches){
        pane.append(button('← Voltar à busca',()=>{$('publicProfilePage').hidden=true;searchProfiles();},'soft-action'));
        const title=h('div','public-identity');
        if(d.avatar_url){const img=h('img');img.src=d.avatar_url;img.alt=d.name;title.append(img);}else title.append(h('div','profile-thumb','◉'));
        const meta=h('div');meta.append(h('h3','',d.name),h('p','',d.cards+' cards na coleção'));title.append(meta);pane.append(title);
        if(d.favorite){const fav=block('★ Card favorito',d.favorite.name);fav.classList.add('public-section','public-favorite');
          const art=mediaCover(d.favorite.image_url,'★',d.favorite.name,'item-cover');art.setAttribute('role','button');art.tabIndex=0;art.addEventListener('click',()=>showCard(d.favorite,'Card favorito',true));art.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();showCard(d.favorite,'Card favorito',true);}});fav.prepend(art);pane.append(fav);}
        const badges=block('🏅 Selos desbloqueados');badges.classList.add('public-section');const line=h('div','public-badges');
        (d.badges||[]).forEach(b=>{const badge=h('span','badge-chip');badge.append(iconArtwork(b.image_url,b.icon||'🏅'));makeProfileItemInteractive(badge,b,'badge');line.append(badge);});
        if(!d.badges?.length)line.append(h('p','','Nenhum selo por enquanto.'));badges.append(line);pane.append(badges);
        const favorites=block('🎮 Jogos favoritos');favorites.classList.add('public-section');
        const gameIcons=h('div','game-icons');if(!d.favorite_games?.length)gameIcons.append(h('p','','Nenhum jogo selecionado.'));
        for(const game of d.favorite_games||[]){const chip=h('span','game-icon');chip.append(gameIcon(game));makeProfileItemInteractive(chip,game,'game');gameIcons.append(chip);}
        favorites.append(gameIcons);pane.append(favorites);
        if(d.collectibles?.length){const found=block('🏆 Colecionáveis');found.classList.add('public-section','public-collectibles');const grid=h('div','collectible-grid');
          for(const item of d.collectibles){const tile=h('article','collectible-item');tile.append(mediaCover(item.image_url,item.emoji,item.name,'collectible-art'));tile.append(h('strong','',item.name),h('small','',`×${item.quantity}`));if(item.description)tile.title=item.description;grid.append(tile);}found.append(grid);pane.append(found);}
        pane.append(publicPoroCard(d,items));
        pane.append(publicMemberCardsSection(d));
        return;
      }
      const back=button('← Voltar à busca',()=>{$('publicProfilePage').hidden=true;searchProfiles();},'soft-action public-back-search');
      pane.append(back);
      const layout=h('div','public-profile-layout');const main=h('div','public-profile-main');const aside=h('div','public-profile-aside');
      const hero=h('section','public-profile-hero');
      const title=h('div','public-identity');
      if(d.avatar_url){const img=h('img');img.src=d.avatar_url;img.alt=d.name;title.append(img);}else title.append(h('div','profile-thumb','◉'));
      const meta=h('div','public-identity-info');meta.append(h('h3','',d.name),h('span','public-online','● Perfil da comunidade'),h('p','public-card-count',`${d.cards} card(s) na coleção`));title.append(meta);hero.append(title);
      if(d.favorite){const recent=h('div','public-hero-favorite');const cover=mediaCover(d.favorite.image_url,'★',d.favorite.name,'item-cover');cover.tabIndex=0;cover.setAttribute('role','button');cover.setAttribute('aria-label','Ampliar card favorito de '+d.name);cover.addEventListener('click',()=>showCard(d.favorite,'Card favorito de '+d.name,true));cover.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();showCard(d.favorite,'Card favorito de '+d.name,true);}});recent.append(cover,h('strong','','Card favorito: '+d.favorite.name));hero.prepend(recent);}
      main.append(hero);
      const badges=block('🏅 Selos desbloqueados');badges.classList.add('public-section','public-badges');const line=h('div','public-badges-row');
      (d.badges||[]).forEach(b=>{const badge=h('span','badge-chip');badge.append(iconArtwork(b.image_url,b.icon||'🏅'));makeProfileItemInteractive(badge,b,'badge');line.append(badge);});
      if(!d.badges?.length)line.append(h('p','','Nenhum selo por enquanto.'));badges.append(line);main.append(badges);
      const favorites=block('🎮 Jogos favoritos');favorites.classList.add('public-section','public-games');
      const gameIcons=h('div','game-icons');if(!d.favorite_games?.length)gameIcons.append(h('p','','Nenhum jogo selecionado.'));
      for(const game of d.favorite_games||[]){const chip=h('span','game-icon');chip.append(gameIcon(game));makeProfileItemInteractive(chip,game,'game');gameIcons.append(chip);}
      favorites.append(gameIcons);main.append(favorites);
      if(d.collectibles?.length){const found=block('🏆 Colecionáveis');found.classList.add('public-section','public-collectibles');const grid=h('div','collectible-grid');
        for(const item of d.collectibles){const tile=h('article','collectible-item');tile.append(mediaCover(item.image_url,item.emoji,item.name,'collectible-art'));tile.append(h('strong','',item.name),h('small','',`×${item.quantity}`));if(item.description)tile.title=item.description;grid.append(tile);}found.append(grid);main.append(found);}
      aside.append(publicPoroCard(d,items));
      aside.append(publicMemberCardsSection(d));
      layout.append(main,aside);pane.append(layout);
    }catch(err){toast(err.message);}
  }
  function publicPoroCard(profile,inventory){
    if(!profile.pet){const empty=block('Sem Poro','Este membro ainda não adotou um Poro.');empty.classList.add('public-section','public-pet');return empty;}
    const pet=profile.pet;
    const label=pet.nickname||poroSpeciesName(pet.name);
    const status={ativo:'Em casa',missao:'Em expedição',vet:'No veterinário',morto:'Falecido'}[pet.status]||'Indisponível';
    const panel=block('🐾 Poro: '+label,`Fome ${pet.food}/100 · Felicidade ${pet.happiness}/100 · ${status}`);
    panel.classList.add('public-section','public-pet');panel.dataset.ownerId=profile.key;
    panel.prepend(petPortrait(pet));
    if(pet.status==='ativo'){
      const actions=h('div','social-actions public-pet-actions');
      const caress=button('💗 Acariciar',()=>visitPet(profile.key,'pet',null,panel),'main-action public-pet-pat');
      actions.append(caress);
      const available=(inventory.treats||[]).filter(t=>t.sku!=='vacina' && Number(t.quantity||0)>0);
      const select=h('select','select-input');select.setAttribute('aria-label','Petisco para alimentar este Poro');
      for(const item of available){const option=h('option','',`${item.name} (×${item.quantity})`);option.value=item.sku;select.append(option);}
      if(available.length)actions.append(select);
      const feed=button('🍪 Alimentar',()=>visitPet(profile.key,'feed',select.value,panel),'soft-action public-pet-feed');
      if(!available.length){feed.disabled=true;feed.title='Você precisa de um petisco no Inventário';}
      actions.append(feed);
      if(!available.length)actions.append(button('Comprar petiscos →',()=>{$('publicProfilePage').hidden=true;chooseTab('loja','treat3');},'soft-action public-pet-buy'));
      panel.append(actions);
    }else{
      panel.append(h('p','public-pet-closed','Os cuidados de visitantes ficam indisponíveis enquanto este Poro estiver no veterinário, em expedição ou ausente.'));
    }
    return panel;
  }
  async function visitPet(owner,action,sku,card){
    if(!card || card.dataset.carePending==='1' || card.dataset.ownerId!==owner)return;
    card.dataset.carePending='1';
    const controls=card.querySelectorAll('.public-pet-actions button');
    controls.forEach(b=>b.disabled=true);
    // Reação local instantânea; o perfil público e o GLB permanecem montados.
    const visual=card.querySelector('.pet-visual');
    if(visual){
      const effect=h('span','pet-spark',action==='feed'?'🍪':'💖');visual.append(effect);
      setTimeout(()=>effect.remove(),850);
      visual.playCareAnimation?.(action);
    }
    try{
      const response=await API('/api/pets/visit/'+encodeURIComponent(owner),{action,treat_sku:sku||'biscoito'});
      resetCachedData();
      if(response.pet){
        const status=card.querySelector(':scope > p');
        if(status)status.textContent=`Fome ${response.pet.food}/100 · Felicidade ${response.pet.happiness}/100 · Em casa`;
      }
      applyConfirmedCoins({coins_balance:response.visitor_balance,coins_gained:response.visitor_coins});
      if(action==='feed' && response.visitor_treats!==undefined){
        if(state.account)state.account.treats=response.visitor_treats;
        for(const id of ['valPetiscos','desktopTreats']){const el=$(id);if(el)el.textContent=money(response.visitor_treats);}
        const selected=card.querySelector('.public-pet-actions .select-input');
        if(selected){const option=Array.from(selected.options).find(o=>o.value===sku);
          if(option){const remaining=Number(response.treat_quantity);
            if(Number.isFinite(remaining)&&remaining<=0)option.remove();
            else if(Number.isFinite(remaining))option.textContent=option.textContent.replace(/×\d+/,`×${remaining}`);
          }
        }
      }
      const used=card.querySelector(action==='pet'?'.public-pet-pat':'.public-pet-feed');
      if(used){used.textContent=action==='pet'?'✓ Acariciado hoje':'✓ Alimentado hoje';used.dataset.completed='1';}
      toast(`+${money(response.visitor_coins||0)} moedas para você e +${money(response.owner_coins||0)} para o dono!`);
      // Reconciliar apenas contadores, sem chamar openPublicProfile e recarregar seu modelo.
      refreshProfile().catch(()=>{});
      return response;
    }catch(err){toast('⚠ '+(err?.message||'Não foi possível cuidar deste Poro.'));return null;}
    finally{
      delete card.dataset.carePending;
      controls.forEach(b=>{if(!b.dataset.completed && !b.classList.contains('public-pet-buy'))b.disabled=b.classList.contains('public-pet-feed') && !card.querySelector('.public-pet-actions .select-input')?.options.length;});
    }
  }
  // GLB: animações nomeadas (Idle, carinho e alimentação) são selecionadas
  // sem recriar a cena. Embeds Khada não expõem API para trocar os clipes.
  const KHADA_EMBED_ORIGIN='https://modelviewer.lol';
  function khadaTftUrl(id){
    const value=String(id||'').trim();
    if(!/^\d{2,12}$/.test(value))throw Error('Informe um ID numérico válido do Khada (TFT).');
    return `${KHADA_EMBED_ORIGIN}/embed?id=${value}&group=tft`;
  }
  function khadaEmbedUrl(value){
    try{
      const u=new URL(String(value||''),location.href);
      if(u.origin!==KHADA_EMBED_ORIGIN || u.pathname!=='/embed' || !/^\d{2,12}$/.test(u.searchParams.get('id')||''))return null;
      const group=u.searchParams.get('group')||'tft';
      if(!['tft','lol','extras'].includes(group))return null;
      // Permitimos somente parametros documentados; emotes/animacoes Pro nao sao usados.
      const safe=new URL('/embed',KHADA_EMBED_ORIGIN);
      safe.searchParams.set('id',u.searchParams.get('id'));
      safe.searchParams.set('group',group);
      safe.searchParams.set('shadow','false');
      return safe.href;
    }catch(_){return null;}
  }
  function khadaIdFromUrl(value){
    const url=khadaEmbedUrl(value);
    return url ? new URL(url).searchParams.get('id') : '';
  }
  let modelViewerLoad=null;
  function load3DViewer(){
    if(window.customElements?.get('model-viewer'))return Promise.resolve(true);
    if(!modelViewerLoad){
      modelViewerLoad=import('https://cdn.jsdelivr.net/npm/@google/model-viewer@4.1.0/dist/model-viewer.min.js')
        .catch(()=>import('https://unpkg.com/@google/model-viewer@4.1.0/dist/model-viewer.min.js'))
        .then(()=>window.customElements.whenDefined('model-viewer').then(()=>true))
        .catch(()=>{modelViewerLoad=null;return false;});
    }
    return modelViewerLoad;
  }
  function bestIdleClip(clips,requested){
    const names=Array.isArray(clips)?clips:[];
    const explicit=String(requested||'').trim();
    // Respeitar o nome exato configurado no gerenciador, sem exigir a palavra Idle.
    if(explicit){const found=names.find(name=>name===explicit)||names.find(name=>name.toLowerCase()===explicit.toLowerCase());if(found)return found;}
    const isIdle=name=>/idle|stand|breath|parad/i.test(name);
    return names.find(isIdle)||(names.length===1?names[0]:null);
  }
  function careClipName(clips,requested,action){
    const names=Array.isArray(clips)?clips:[];
    const explicit=String(requested||'').trim();
    if(explicit){
      // Se uma animação foi configurada, nunca escolher outra aleatoriamente.
      return names.find(name=>name===explicit)||names.find(name=>name.toLowerCase()===explicit.toLowerCase())||null;
    }
    const rx=action==='feed'?/(?:feed|eat|eating|snack|treat|aliment|comer|munch|bite)/i:/(?:petting|pet_|_pet|pat|happy|affection|caress|carinho|purr)/i;
    return names.find(name=>rx.test(name) && !/idle|stand/i.test(name))||null;
  }
  function petVisual(species,large=false,thumbnail=false){
    const wrap=h('div','pet-visual'+(large?' pet-visual-large':''));
    const fallback=mediaCover(species.image_url,species.emoji||'🐾',poroSpeciesName(species.name),'pet-fallback');
    wrap.append(fallback);
    const model=String(species.model_url||'').trim();
    const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
    // Muitos modelos simultaneos na lista de adocao esgotam WebGL em celulares.
    if(!model || thumbnail){
      if(!model && !reduced)wrap.classList.add('pet-preview-moving');
      if(!model && !thumbnail){
        const note=h('span','pet-model-hint','Modelo 3D não configurado');
        note.title='Abra Gestão do Recanto → Poros e associe um ID Khada TFT real ou uma URL pública de arquivo .glb.';
        wrap.append(note);
      }
      return wrap;
    }
    const khada=khadaEmbedUrl(model);
    if(!khada && !/^(https:\/\/|\/models\/)/i.test(model)){
      wrap.dataset.modelError='invalid-url';
      wrap.append(h('span','pet-model-hint pet-model-hint-error','URL 3D inválida: use ID do Khada ou arquivo .glb por HTTPS.'));
      return wrap;
    }
    if(!khada && !/\.glb(?:[?#]|$)/i.test(model)){
      wrap.dataset.modelError='not-glb';
      wrap.append(h('span','pet-model-hint pet-model-hint-error','O endereço salvo não é um arquivo .glb direto.'));
      return wrap;
    }
    let visible=false,started=false,loaded=false;
    let view=null,carePlaying=false,careFallbackTimer=null;
    function returnToIdle(){
      clearTimeout(careFallbackTimer);careFallbackTimer=null;
      carePlaying=false;
      if(!view)return;
      view.dataset.carePlaying='';
      const idle=view.dataset.idleAnimation;
      if(idle){view.animationName=idle;if(visible && !reduced)try{view.play();}catch(_){/* A cena pode estar oculta. */}}
      else view.pause?.();
    }
    // O botão não recria o elemento 3D. Ele troca apenas o clipe no viewer existente.
    wrap.playCareAnimation=(action)=>{
      if(!view || !loaded || khada || reduced || carePlaying)return false;
      const requested=action==='feed'?species.feed_animation:species.pet_animation;
      const clip=careClipName(view.availableAnimations,requested,action);
      if(!clip)return false;
      carePlaying=true;view.dataset.carePlaying='1';
      try{
        view.animationName=clip;
        view.currentTime=0;
        view.play({repetitions:1});
        // Backup para clips cujos modelos não emitem finished por limitação do export.
        const seconds=Number(view.duration);
        careFallbackTimer=setTimeout(returnToIdle,Number.isFinite(seconds)&&seconds>0?Math.min(15000,Math.max(1600,seconds*1000+950)):8000);
        return true;
      }catch(_){returnToIdle();return false;}
    };
    const syncVisibility=(show)=>{
      visible=show && document.visibilityState!=='hidden';
      if(visible && !started){started=true;startViewer();}
      if(!view || khada || !loaded)return;
      if(!visible){view.pause?.();return;}
      if(carePlaying)return; // A entrada/saída do viewport não reinicia a cena durante o carinho.
      if(!reduced && view.dataset.idleAnimation){
        try{view.play();}catch(_){/* O componente ainda pode estar inicializando. */}
      }
    };
    function startViewer(){
      if(khada){
        const iframe=h('iframe','pet-khada-embed');
        iframe.title='Poro animado em repouso: '+poroSpeciesName(species.name);
        iframe.loading='lazy';iframe.referrerPolicy='strict-origin-when-cross-origin';
        iframe.setAttribute('allow','autoplay; fullscreen');
        iframe.src=khada;
        // O embed gratuito inclui rodape e marca do Khada; nunca os ocultamos.
        iframe.addEventListener('load',()=>{
          fallback.classList.add('fallback-hidden');
          wrap.classList.add('khada-frame-loaded');
          // O evento load não confirma que o ID exista dentro do iframe externo.
        },{once:true});
        iframe.addEventListener('error',()=>{
          fallback.classList.remove('fallback-hidden');
          wrap.dataset.modelError='khada-iframe';
        });
        wrap.append(iframe);
        const link=h('a','pet-model-check','Testar modelo no Khada ↗');
        link.href=khada;link.target='_blank';link.rel='noopener noreferrer';
        link.title='Se a cena ficar vazia, confirme o ID no catálogo Khada TFT (se o modelo for compatível).';
        wrap.after(link);
        return;
      }
      view=h('model-viewer','pet-model');
      view.setAttribute('alt','Modelo 3D de '+poroSpeciesName(species.name));
      view.setAttribute('camera-controls','');
      view.setAttribute('shadow-intensity','0.65');
      view.setAttribute('exposure','1.1');view.setAttribute('environment-image','neutral');
      view.setAttribute('interaction-prompt','none');
      view.setAttribute('loading','eager');view.setAttribute('reveal','auto');
      if(large){
        // Aproxima o Poro dentro do seu painel sem alterar escala do card.
        view.setAttribute('camera-orbit','0deg 75deg 82%');
        view.setAttribute('min-camera-orbit','auto auto 65%');
      }
      view.setAttribute('animation-crossfade-duration','300');
      // Nao ativar autoplay antes de descobrir a animacao correta: isso disparava Walk/Dance.
      view.addEventListener('load',()=>{
        loaded=true;
        view.classList.add('model-loaded');fallback.classList.add('fallback-hidden');
        wrap.classList.remove('pet-preview-moving');
        const idle=bestIdleClip(view.availableAnimations,species.idle_animation);
        if(idle){
          view.dataset.idleAnimation=idle;
          view.animationName=idle;
          // model-viewer reproduz em loop por padrao; ao pausar fora da tela economizamos GPU.
          if(visible && !reduced)view.play();
        }else{
          view.dataset.idleAnimation='';
          // Modelo sem Idle: posicao estatica; nao executar outra acao involuntariamente.
          view.pause?.();
          wrap.title='Este GLB não contém uma animação Idle identificável.';
        }
      });
      view.addEventListener('error',()=>{
        loaded=false;view.classList.remove('model-loaded');fallback.classList.remove('fallback-hidden');
        if(!reduced)wrap.classList.add('pet-preview-moving');
        if(!wrap.querySelector('.model-error'))wrap.append(h('small','model-error','Falha no GLB: confirme URL pública, extensão .glb e permissão CORS.'));
      });
      view.addEventListener('finished',()=>{
        if(carePlaying)returnToIdle();
        else if(visible && !reduced && view.dataset.idleAnimation){view.animationName=view.dataset.idleAnimation;view.play();}
      });
      wrap.append(view);
      load3DViewer().then(ready=>{
        if(ready)view.src=model;
        else view.dispatchEvent(new Event('error'));
      });
    }
    if('IntersectionObserver' in window){
      const observer=new IntersectionObserver(entries=>{
        if(!wrap.isConnected){observer.disconnect();return;}
        syncVisibility(entries.some(e=>e.isIntersecting));
      },{threshold:0.01,rootMargin:'100px 0px'});
      observer.observe(wrap);
    }else syncVisibility(true);
    return wrap;
  }
  // Economiza GPU ao minimizar/alternar para outro aplicativo.
  document.addEventListener('visibilitychange',()=>{
    for(const view of document.querySelectorAll('model-viewer.pet-model')){
      if(document.hidden){view.pause?.();continue;}
      const rect=view.getBoundingClientRect();
      if(!view.dataset.carePlaying && view.dataset.idleAnimation && rect.width && rect.height && rect.bottom>0 && rect.top<innerHeight){
        try{view.play();}catch(_){/* Modelo ainda inicializando. */}
      }
    }
  });
  function petReaction(action){
    // Feedback no instante do clique: nenhuma navegação ou remontagem do GLB.
    const visual=$('petPane').querySelector('.poro-main-card .pet-visual-large');if(!visual)return;
    const symbol=h('span','pet-spark',action==='feed'?'🍪':'💖');visual.append(symbol);
    setTimeout(()=>symbol.remove(),850);
    visual.playCareAnimation?.(action);
  }
  async function petCare(action,sku='biscoito'){
    if(state.petCareBusy)return;
    state.petCareBusy=true;
    petReaction(action);
    try{
      const result=await API('/api/pets/care',{action,treat_sku:sku});
      resetCachedData();
      // Atualização pontual: preserva o <model-viewer>, o vídeo Idle e a rolagem.
      if(result?.pet){
        state.activePet=result.pet;
        if(Number.isFinite(Number(result.treats)))state.activePetTreats=Number(result.treats);
        const p=$('petPane').querySelector('.poro-status-card p');
        if(p)p.textContent=`🍎 Fome: ${result.pet.food}/100 • 💕 Felicidade: ${result.pet.happiness}/100 • 🍪 Petiscos: ${state.activePetTreats??0}`;
      }
      if(action==='feed'){
        const remaining=Number(result?.treats);
        if(Number.isFinite(remaining)){
          if(state.account){state.account.treats=remaining;}
          for(const id of ['valPetiscos','desktopTreats']){const el=$(id);if(el)el.textContent=money(remaining);}
        }
        const choose=$('petPane').querySelector('.poro-care-actions-card .select-input');
        if(choose){
          const option=Array.from(choose.options).find(opt=>opt.value===sku);
          if(option){
            const qty=Number(result?.treat_quantity);
            if(Number.isFinite(qty) && qty<=0)option.remove();
            else if(Number.isFinite(qty))option.textContent=option.textContent.replace(/·\s*\d+\s*$/,`· ${qty}`);
          }
          if(!choose.options.length){choose.disabled=true;const btn=$('petPane').querySelector('.poro-care-actions-card .pet-actions button');if(btn){btn.disabled=true;btn.textContent='Sem petiscos';}}
        }
      }
      toast(action==='feed'?'Poro alimentado!':'Seu Poro recebeu carinho!');
      // Não chamar refreshActive nem refreshProfile aqui: ambos poderiam recriar o Poro.
      return result;
    }catch(err){
      toast('⚠ '+(err?.message||'Não foi possível cuidar do Poro.'));
      // Uma interação recusada não aumenta fome/felicidade nem desconta petiscos.
      return null;
    }finally{state.petCareBusy=false;}
  }
  async function loadPet(){
    const data=await API('/api/pets');const pane=$('petPane');pane.replaceChildren();const pet=data.pet;
    state.activePet=pet;state.activePetTreats=Number(data.treats||0);
    if(state.account && data.coins_balance!==undefined && Number.isFinite(Number(data.coins_balance))
       && Number(data.coins_balance)!==Number(state.account.coins)){
      applyConfirmedCoins({coins_balance:data.coins_balance});
    }
    $('petStatus').textContent=pet?({ativo:'Em casa','vet':'No veterinário','morto':'Falecido','missao':'Em missão'}[pet.status]):'Sem Poro';
    if(!pet||pet.status==='morto'){
      const deceased=pet?.status==='morto';
      const waiting=deceased && pet.adoption_available_at && new Date(pet.adoption_available_at).getTime()>Date.now();
      const message=deceased
        ?`Seu Poro faleceu. Penalidade aplicada: ${pet.death_penalty||150} moedas. ${waiting?'Você poderá adotar outro em '+countdown(pet.adoption_available_at)+'.':'Já pode adotar um novo Poro.'}`
        :'Você pode adotar apenas um Poro por vez. Cuide dele diariamente.';
      const notice=block(deceased?'Seu Poro faleceu':'Escolha seu Poro',message);
      if(waiting){
        const until=h('p','poro-death-countdown');until.dataset.readyAt=pet.adoption_available_at;
        const update=()=>{if(until.isConnected){until.textContent='Próxima adoção em: '+countdown(pet.adoption_available_at);}};
        update();
        const ticker=setInterval(()=>{if(!until.isConnected){clearInterval(ticker);return;}update();if(Date.now()>=new Date(pet.adoption_available_at).getTime()){clearInterval(ticker);loadPet().catch(()=>{});}},1000);
        notice.append(until);
      }
      pane.append(notice);
      const grid=h('div','pet-grid');data.species.forEach(s=>{
        const row=block(poroSpeciesName(s.name),'Poro disponível para adoção');row.prepend(petVisual(s,false,true));
        const nameRow=h('label','poro-nickname-label','Nome do seu Poro');
        const nickname=h('input','text-input poro-nickname');nickname.type='text';nickname.maxLength=40;
        nickname.placeholder='Como seu Poro vai se chamar?';nickname.autocomplete='off';
        nameRow.append(nickname);
        const adoptButton=button('Adotar',async()=>{
          const name=nickname.value.trim();
          if(name.length<2||name.length>40){toast('Escolha um nome de 2 a 40 caracteres para seu Poro.');nickname.focus();return;}
          const created=await safeRun(()=>API('/api/pets/adopt',{species_id:s.id,nickname:name}),name+' foi adotado!');
          if(created){resetCachedData();await loadPet();}
        });
        if(waiting){adoptButton.disabled=true;adoptButton.title='Aguarde 24 horas após o falecimento do Poro';}
        row.append(nameRow,adoptButton);grid.append(row);
      });pane.append(grid);return;
    }
    const layout=h('div','poro-layout');const care=h('section','poro-care-column');const adventures=h('section','poro-expeditions-column');
    layout.append(care,adventures);pane.append(layout);
    const petName=pet.nickname||poroSpeciesName(pet.name);
    const show=h('section','game-box poro-main-card');
    const nameBar=h('div','poro-name-banner');
    nameBar.append(h('strong','poro-name-text',petName),h('span','poro-home-badge',
      ({ativo:'Em casa',missao:'Em expedição',vet:'No veterinário',morto:'Falecido'})[pet.status]||'Status indisponível'));
    show.append(nameBar,petPortrait(pet,true));
    care.append(show);

    const statusCard=block('Status do Poro',pet.status==='missao'
      ?`🍎 Fome: ${pet.food}/100 • 💕 Felicidade: ${pet.happiness}/100 • 🍪 Petiscos: ${data.treats}`
      :pet.status==='vet'
        ?`🏥 Resgate por ${money(pet.rescue_cost)} moedas. Prazo: ${pet.vet_deadline?new Date(pet.vet_deadline).toLocaleString('pt-BR'):'—'}`
        :`🍎 Fome: ${pet.food}/100 • 💕 Felicidade: ${pet.happiness}/100 • 🍪 Petiscos: ${data.treats}`
    );
    statusCard.classList.add('poro-status-card');
    care.append(statusCard);

    const rename=block('Nome do Poro');rename.classList.add('poro-config-card');
    const renameRow=h('div','poro-inline-control');const nickname=h('input','text-input');nickname.type='text';nickname.maxLength=40;
    nickname.value=petName;nickname.setAttribute('aria-label','Novo nome do Poro');
    const saveName=async()=>{
      const name=nickname.value.trim();if(name.length<2||name.length>40){toast('Digite um nome entre 2 e 40 caracteres.');return;}
      await safeRun(()=>API('/api/pets/rename',{nickname:name}),'Nome do Poro atualizado!');
    };
    nickname.addEventListener('keydown',e=>{if(e.key==='Enter')saveName();});
    renameRow.append(nickname,button('Renomear',saveName,'soft-action'));rename.append(renameRow);adventures.append(rename);

    const equip=block('🏆 Item colecionável',pet.equipped_collectible?'Equipado: '+pet.equipped_collectible.name:'Escolha um item do inventário para equipar no retrato do Poro.');
    equip.classList.add('poro-config-card');
    const inv=await API('/api/inventory');
    const collectibles=inv.collectibles||[];
    const equipmentRow=h('div','poro-equipment-control');
    if(collectibles.length){
      const selector=h('select','select-input');selector.setAttribute('aria-label','Selecionar colecionável para o Poro');
      const none=h('option','','Nenhum item');none.value='';selector.append(none);
      for(const item of collectibles){const op=h('option','',item.name+' (×'+item.quantity+')');op.value=String(item.id);selector.append(op);}
      selector.value=pet.equipped_collectible?String(pet.equipped_collectible.id):'';
      equipmentRow.append(selector,button('Equipar',()=>safeRun(()=>API('/api/pets/equip-collectible',{collectible_id:selector.value?Number(selector.value):null}),'Item equipado atualizado!')));
    }else equipmentRow.append(h('p','poro-item-empty','Colecionáveis ganhos em expedições aparecerão aqui.'));
    equip.append(equipmentRow);
    if(pet.equipped_collectible){const info=button('Ver item equipado',()=>showProfileItemDetail(pet.equipped_collectible,'collectible'),'soft-action poro-item-detail');equip.append(info);}
    adventures.append(equip);

    if(pet.status==='ativo'){
      const change=block('Trocar de Poro','Escolha outro Poro. A troca substitui o atual, mas seus colecionáveis continuam no inventário.');
      change.classList.add('poro-change-card');
      const toggle=button('Escolher outro Poro',()=>{choices.hidden=!choices.hidden;toggle.setAttribute('aria-expanded',String(!choices.hidden));},'soft-action');
      toggle.setAttribute('aria-expanded','false');
      const choices=h('div','poro-change-options');choices.hidden=true;
      const speciesSelect=h('select','select-input');speciesSelect.setAttribute('aria-label','Escolha a espécie do novo Poro');
      for(const specie of data.species||[]){
        const opt=h('option','',poroSpeciesName(specie.name));opt.value=String(specie.id);speciesSelect.append(opt);
      }
      const newName=h('input','text-input');newName.placeholder='Nome do novo Poro';newName.maxLength=40;
      newName.setAttribute('aria-label','Nome do novo Poro');
      const confirmChange=button('Confirmar troca',async()=>{
        const name=newName.value.trim();
        if(name.length<2 || name.length>40){toast('Digite um nome de 2 a 40 caracteres.');newName.focus();return;}
        if(!window.confirm(`Trocar ${petName} por ${name}? O progresso do Poro atual será substituído.`))return;
        try{
          const updated=await API('/api/pets/change',{species_id:Number(speciesSelect.value),nickname:name});
          if(updated?.ok){resetCachedData();toast('Seu novo Poro chegou!');await loadPet();}
        }catch(error){toast('⚠ '+(error?.message||'Não foi possível trocar o Poro.'));}
      });
      choices.append(speciesSelect,newName,confirmChange);
      change.append(toggle,choices);adventures.append(change);
    }

    if(pet.status==='missao'){
      const expedition=data.expedition;
      const mission=block('🗺️ Em missão',`Seu Poro está em ${expedition?.name||'uma aventura'} e não pode receber carinho nem comida.`);
      adventures.append(mission);
      const when=h('p','expedition-time',expedition?.ready?'Seu Poro voltou!':'Volta em: '+countdown(expedition?.ends_at));adventures.append(when);
      if(expedition?.ready)adventures.append(button('Receber recompensas',async()=>{
        const result=await safeRun(()=>API('/api/pets/expedition/collect',{}),r=>`+${r.coins_gained} moedas${r.converted_coins?' (+'+r.converted_coins+' por card repetido)':''}${r.collectible?' e '+r.collectible.name:''}${r.card?' e um card!':''}`);
        if(result?.card)showCard(result.card,'Card encontrado pelo Poro!');
      }));
      return;
    }
    if(pet.status==='vet'){
      const rescueCard=block('🏥 Veterinário','Resgate seu Poro para ele voltar a receber cuidados e sair em novas expedições.');
      rescueCard.classList.add('poro-rescue-card');
      rescueCard.append(button('Resgatar Poro',()=>safeRun(()=>API('/api/pets/rescue',{}),'Companheiro resgatado!')));
      care.append(rescueCard);
      adventures.append(block('🗺️ Expedições','Resgate seu Poro no veterinário para voltar a explorar.'));
      return;
    }

    const careCard=block('Cuidados','Alimente seu Poro com um petisco do inventário ou faça carinho nele.');
    careCard.classList.add('poro-care-actions-card');
    const actions=h('div','pet-actions');
    if(inv.treats.length){const choose=h('select','select-input');inv.treats.forEach(t=>{const opt=h('option','',t.name+' (+'+t.food+' fome) · '+t.quantity);opt.value=t.sku;choose.append(opt);});careCard.append(choose);
      actions.append(button('🍪 Alimentar',()=>petCare('feed',choose.value)));}
    else actions.append(button('Petiscos na Loja →',()=>chooseTab('loja','treat3')));
    actions.append(button('💗 Acariciar',()=>petCare('pet'),'soft-action'));careCard.append(actions);care.append(careCard);
    const ex=block('🗺️ Expedições dos Poros','Envie seu Poro em uma aventura. Ele não poderá receber cuidados durante a missão e voltará com fome.');
    for(const option of data.expedition_options||[]){
      const row=h('div','expedition-choice');
      if(option.image_url)row.append(mediaCover(option.image_url,'🗺️',option.name,'expedition-cover'));
      row.append(h('strong','',option.name),h('small','',`${option.minutes/60}h • -${option.food} fome • ${option.coins[0]}–${option.coins[1]} moedas • ${option.card_chance}% chance de card${option.collectible_chance?' • '+option.collectible_chance+'% colecionável':''}`));
      row.append(button('Enviar',()=>safeRun(()=>API('/api/pets/expedition/start',{mission:option.id}),'Seu Poro iniciou a missão!'),'soft-action'));ex.append(row);
    }adventures.append(ex);
  }
  // Exibe sempre a arte cadastrada. O emoji e usado apenas se nao houver
  // imagem ou se o endereco da imagem deixar de funcionar.
  function iconArtwork(imageUrl,emoji){
    const placeholder=()=>h('span','icon-emoji',emoji||'🏅');
    const url=String(imageUrl||'').trim();
    if(!url)return placeholder();
    const img=h('img','icon-artwork');
    img.src=url;img.alt='';img.loading='lazy';img.decoding='async';
    img.onerror=()=>{if(img.isConnected)img.replaceWith(placeholder());};
    return img;
  }
  function gameIcon(game){return iconArtwork(game.image_url,game.icon||'🎮');}
  async function loadUiAssets(){
    try{const result=await API('/api/assets');state.assets=result.items||[];applyUiAssets();}
    catch(_){/* assets opcionais; UI padrao continua funcionando */}
  }
  function applyUiAssets(){
    // O favicon faz parte das artes configuraveis, sem afetar os icones do PWA.
    const favicon=document.querySelector('link[rel="icon"]');
    if(favicon){
      const chosen=(state.assets||[]).find(asset=>asset.key==='favicon' && asset.image_url);
      favicon.href=chosen?.image_url||'/icons/icon-192.png';
      const ext=(chosen?.image_url||'').toLowerCase().split('?')[0];
      favicon.type=ext.endsWith('.svg')?'image/svg+xml':ext.endsWith('.webp')?'image/webp':/\.jpe?g$/.test(ext)?'image/jpeg':'image/png';
    }
    // Limpa personalizacoes antigas para permitir remover/alterar uma imagem.
    for(const host of document.querySelectorAll('.asset-icon-host')){
      host.querySelectorAll(':scope > .ui-asset-icon').forEach(img=>img.remove());
      const svg=host.querySelector(':scope > svg');if(svg)svg.hidden=false;
      host.classList.remove('asset-icon-host');
    }
    for(const el of document.querySelectorAll('.asset-image-background')){
      el.style.backgroundImage='';el.classList.remove('asset-image-background');
    }
    // Conteudos dinamicos sao recriados a cada mudanca de aba.
    for(const a of state.assets||[]){
      if(!a.selector||!a.image_url)continue;
      let targets=[];
      try{targets=[...document.querySelectorAll(a.selector)].slice(0,80);}catch(_){continue;}
      for(const el of targets){
        if(a.mode==='image'&&el.tagName==='IMG'){
          if(el.getAttribute('src')!==a.image_url)el.src=a.image_url;
        } else if(a.mode==='icon'){
          const svg=el.querySelector(':scope > svg');
          el.querySelectorAll(':scope > .ui-asset-icon').forEach(old=>old.remove());
          const img=h('img','ui-asset-icon');img.src=a.image_url;img.alt='';
          el.prepend(img);el.classList.add('asset-icon-host');
          if(svg)svg.hidden=true;
        } else {
          el.style.backgroundImage=`url(${JSON.stringify(a.image_url)})`;
          el.classList.add('asset-image-background');
        }
      }
    }
  }
  function mediaCover(src,emoji,title,cls='item-cover'){
    const wrapper=h('div',cls);if(src){const img=h('img');img.src=src;img.alt=title;img.loading='lazy';img.onerror=()=>{img.remove();wrapper.textContent=emoji;};wrapper.append(img);}else wrapper.textContent=emoji;
    return wrapper;
  }
  async function loadShop(){const [shop,me,daily]=await Promise.all([API('/api/shop'),API('/api/me'),API('/api/daily/status')]);$('shopWallet').textContent=`🪙 ${money(me.coins)}`;state.reset=daily.next_reset;state.dailyReward=Number(daily.reward||0);$('dailyCoins').disabled=daily.coins_claimed||state.dailyClaimInFlight;$('dailyCoins').textContent=state.dailyClaimInFlight?'Confirmando resgate…':daily.coins_claimed?'✓ Resgatado':`Resgatar ${money(daily.reward)} moedas`;updateCountdowns();const pane=$('shopPane');pane.replaceChildren();for(const s of shop.products){const box=block(s.name,s.kind==='cards'?`${s.amount} cartas aleatórias · guarda no Inventário`:s.sku==='vaccine'?'1 vacina para Poros em recuperação':`${s.amount} petisco(s) · +${s.food||15} fome por unidade`);box.id='shop-'+s.sku;box.classList.add('product-card');box.prepend(mediaCover(s.image_url,s.emoji||'🎁',s.name,'product-cover'));if(s.rates)box.append(h('p','rates',Object.entries(s.rates).map(([k,v])=>`${tierLabels[k]} ${v}%`).join(' · ')));box.append(button(`Comprar · 🪙 ${money(s.price)}`,()=>safeRun(()=>API('/api/shop/purchase',{sku:s.sku}),result=>result.pack_id?`Pacote guardado no Inventário!`:`${result.treats_gained} item(ns) adicionado(s) ao Inventário!`)));pane.append(box);}if(state.focusShop){const selected=$('shop-'+state.focusShop);state.focusShop=null;if(selected){selected.classList.add('shop-focus');selected.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'center'});setTimeout(()=>selected.classList.remove('shop-focus'),1800);}}}
  async function loadMissions(){
    const data=await API('/api/missions');state.missionReset=data.next_reset;
    const pane=$('missionPane');pane.replaceChildren();
    const completed=data.items.filter(x=>x.claimed).length;
    $('missionCount').textContent=`${completed}/${data.items.length} resgatadas`;
    for(const [kind,label] of [['unica','Missões Únicas'],['diaria','Missões Diárias (3 por dia)'],['semanal','Missões Semanais']]){
      const section=h('section','mission-category');section.append(h('h2','mission-category-title',label));
      const items=data.items.filter(x=>x.kind===kind);
      if(!items.length)section.append(h('p','mission-placeholder','Nenhuma missão disponível nesta categoria.'));
      for(const m of items){
        const box=block(poroLegacyText(m.title),`Progresso: ${m.progress}/${m.goal} · Recompensa: 🪙 ${m.reward}`);
        box.classList.add('mission-card');box.prepend(mediaCover(m.image_url,m.emoji||'🎯',poroLegacyText(m.title),'mission-cover'));
        const bar=h('div','mission-meter');const fill=h('div','mission-fill');fill.style.width=Math.min(100,100*m.progress/m.goal)+'%';bar.append(fill);box.append(bar);
        const action=button(m.claimed?'✓ Resgatada':m.progress>=m.goal?'Resgatar recompensa':'Em andamento',()=>safeRun(()=>API('/api/missions/'+m.code+'/claim',{}),`+${m.reward} moedas!`,result=>{applyConfirmedCoins(result,m.reward);action.textContent='✓ Resgatada';action.dataset.keepDisabled='1';action.disabled=true;}));
        action.disabled=m.claimed||m.progress<m.goal;box.append(action);section.append(box);
      }
      pane.append(section);
    }
    updateCountdowns();
  }
  async function loadNotification(){
    try{
      const d=await API('/api/notifications/preferences');state.notification=!!d.enabled;
      // V1.0 concedia permissão sem registrar subscription Web Push.
      // Converte a antiga preferência em opt-in novo e efetivo neste dispositivo.
      if(state.notification && 'serviceWorker' in navigator && 'PushManager' in window){
        const reg=await navigator.serviceWorker.ready;
        const subscription=await reg.pushManager.getSubscription();
        if(!subscription){state.notification=false;await API('/api/notifications/preferences',{enabled:false});}
      }
    }catch(_){state.notification=false;}
    updateNotificationUI();
  }
  function updateNotificationUI(message){const permitted=window.isSecureContext&&'Notification' in window;const active=state.notification&&permitted&&Notification.permission==='granted';$('notificationsToggle').classList.toggle('on',!!active);$('notificationsToggle').setAttribute('aria-checked',String(!!active));$('notificationsStatus').textContent=message||(!permitted?'Notificações exigem HTTPS e navegador compatível.':'');$('notificationsStatus').hidden=!$('notificationsStatus').textContent;}
  function vapidBytes(key){
    const normalized=(key+'='.repeat((4-key.length%4)%4)).replace(/-/g,'+').replace(/_/g,'/');
    const decoded=atob(normalized);return Uint8Array.from(decoded,c=>c.charCodeAt(0));
  }
  async function toggleNotifications(){
    if(state.notificationBusy)return;state.notificationBusy=true;
    try{
      if(!window.isSecureContext||!('Notification' in window)||!('serviceWorker' in navigator)||!('PushManager' in window))throw Error('Este navegador não suporta notificações Web Push.');
      const reg=await navigator.serviceWorker.ready;
      if(!state.notification){
        const key=await API('/api/push/key');
        if(!key.enabled)throw Error('O administrador precisa configurar as chaves VAPID no Render.');
        if(await Notification.requestPermission()!=='granted')throw Error('Permissão não concedida.');
        const sub=await reg.pushManager.getSubscription()||await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:vapidBytes(key.public_key)});
        await API('/api/push/subscribe',sub.toJSON());
        await API('/api/notifications/preferences',{enabled:true});state.notification=true;
        updateNotificationUI('Notificações ativadas! Você receberá alertas dos eventos configurados.');
      } else {
        const sub=await reg.pushManager.getSubscription();
        if(sub){await API('/api/push/unsubscribe',{endpoint:sub.endpoint});await sub.unsubscribe();}
        await API('/api/notifications/preferences',{enabled:false});state.notification=false;
        updateNotificationUI('Notificações desativadas.');
      }
    }catch(err){updateNotificationUI(err.message);}finally{state.notificationBusy=false;}
  }
    function login(){if(state.config.discord_configured)location.assign('/auth/discord/start');else report('Configure as credenciais do Discord no arquivo backend/.env antes de entrar.');}
  async function logout(){await safeRun(()=>API('/api/auth/logout',{}));showLogin();}
  async function uploadArtwork(file){
    if(!file)return '';
    const svg=file.name.toLowerCase().endsWith('.svg') || file.type==='image/svg+xml';
    const form=new FormData();form.append('image',file);
    const response=await fetch(svg?'/api/admin/upload-svg':'/api/admin/upload',{method:'POST',credentials:'same-origin',body:form});
    const result=await response.json();if(!response.ok)throw Error(result.detail||'Falha ao enviar imagem');
    return result.image_url;
  }
  async function uploadModel(files){
    const form=new FormData();for(const file of files)form.append('files',file);
    const response=await fetch('/api/admin/model-upload',{method:'POST',credentials:'same-origin',body:form});
    const result=await response.json();if(!response.ok)throw Error(result.detail||'Falha ao enviar modelo 3D');
    return result.model_url;
  }
  const adminField=(label,value,type='text')=>{const row=h('label','admin-field',label);const input=h('input','text-input');input.value=value||'';input.type=type;row.append(input);return [row,input];};
  // URL .webp recebe o mesmo tratamento de PNG/JPG. O teste permite distinguir
  // uma URL válida de bloqueio de hotlink ou arquivo inacessível na origem.
  function attachArtworkPreview(input,container){
    const preview=h('span','admin-artwork-preview');preview.hidden=true;
    const img=h('img');img.alt='Prévia da arte';img.loading='lazy';
    const status=h('small','','');preview.append(img,status);container.append(preview);
    let ticket=0;
    const render=()=>{
      const url=input.value.trim();const generation=++ticket;
      if(!url){preview.hidden=true;img.removeAttribute('src');return;}
      preview.hidden=false;status.textContent='Verificando imagem...';img.hidden=true;
      if(!/^https:\/\/|^\/uploads\//i.test(url)){
        status.textContent='Use uma URL HTTPS direta (.webp, .png ou .jpg) ou envie o arquivo.';return;
      }
      img.onload=()=>{if(generation!==ticket)return;img.hidden=false;status.textContent='Imagem carregada ('+img.naturalWidth+' × '+img.naturalHeight+').';};
      img.onerror=()=>{if(generation!==ticket)return;img.hidden=true;status.textContent='A URL não carregou. O servidor externo pode bloquear imagens incorporadas. Envie o arquivo WEBP pelo campo de upload.';};
      img.src=url;
    };
    input.addEventListener('change',render);
    input.addEventListener('blur',render);
    return render;
  }
  // Editor de registros existentes: todas as operacoes conferem permissoes novamente no servidor.
  function adminCatalogEditor(group,title,spec,collectionPromise){
    const box=block(title,group==='cards'?'Edite, arquive ou exclua permanentemente um card. Excluir apaga também cópias, reservas, favoritos, trocas e ofertas relacionadas.':'Editar ou remover do catálogo sem apagar dados já obtidos pelos usuários. Remover significa arquivar; é possível restaurar.');
    const wrap=h('div','admin-catalog-tools');
    const chooser=h('select','select-input');chooser.append(h('option','','Carregando registros...'));
    const form=h('div','admin-editor-form');form.hidden=true;
    const status=h('p','admin-entry-status');
    const inputs={};
    for(const [key,label,kind,options] of spec){
      const field=h('label','admin-field',label);
      let input;
      if(kind==='select'){
        input=h('select','select-input');
        for(const [value,text] of options){const option=h('option','',text);option.value=value;input.append(option);}
      }else{
        input=h('input','text-input');input.type=kind==='number'?'number':'text';
        if(kind==='number')input.min='0';
      }
      field.append(input);inputs[key]=input;form.append(field);
      if(key==='image_url' && kind==='text')attachArtworkPreview(input,field);
    }
    let imageFile=null,modelFile=null,khadaInput=null;
    if(['cards','pets','achievements','items'].includes(group)){
      const label=h('label','admin-field','Substituir imagem (opcional)');
      imageFile=h('input','text-input');imageFile.type='file';imageFile.accept='image/png,image/jpeg,image/webp,.webp';label.append(imageFile);form.append(label);
    }
    if(group==='pets'){
      const label=h('label','admin-field','Substituir GLB animado (opcional; em produção requer Cloudinary ou URL pública .glb)');
      modelFile=h('input','text-input');modelFile.type='file';modelFile.accept='.glb,model/gltf-binary';label.append(modelFile);form.append(label);
      const khadaLabel=h('label','admin-field','ID do modelo no Khada (TFT, opcional)');
      khadaInput=h('input','text-input');khadaInput.type='text';khadaInput.inputMode='numeric';khadaInput.placeholder='ID de um modelo Khada TFT compatível';khadaLabel.append(khadaInput);form.append(khadaLabel);
      inputs.model_url.addEventListener('input',()=>{khadaInput.value='';});
      form.append(h('small','','Configure os nomes EXATOS dos clipes do GLB para Idle, Carinho e Alimentação. Modelos por embed Khada não permitem controlar clipes a partir do Recanto.'));
    }
    const actions=h('div','admin-action-row');
    const save=button('Salvar alterações',async()=>{
      const current=rows.find(row=>String(row.id)===chooser.value);
      if(!current)return;
      const data=Object.fromEntries(spec.map(([key,,kind])=>[key,kind==='number'?Number(inputs[key].value):inputs[key].value.trim()]));
      data.action='save';
      const result=await safeRun(async()=>{
        if(imageFile?.files.length)data.image_url=await uploadArtwork(imageFile.files[0]);
        if(modelFile?.files.length)data.model_url=await uploadModel(modelFile.files);
        else if(khadaInput?.value.trim())data.model_url=khadaTftUrl(khadaInput.value);
        if(data.model_url && !khadaEmbedUrl(data.model_url) && !/\.glb(?:[?#]|$)/i.test(data.model_url)){
          throw Error('Modelo inválido: informe um ID Khada TFT ou URL direta de um .glb. Um PNG/JPG não é um modelo 3D.');
        }
        return API('/api/admin/catalog-management/'+group+'/'+encodeURIComponent(current.id),data);
      },'Alterações salvas.');
      if(result)await refresh(current.id);
    });
    const archive=button('Remover (arquivar)',async()=>{
      const current=rows.find(row=>String(row.id)===chooser.value);
      if(!current||!window.confirm('Remover '+(current.name||current.title)+' do catálogo público? Itens já obtidos serão preservados.'))return;
      const result=await safeRun(()=>API('/api/admin/catalog-management/'+group+'/'+encodeURIComponent(current.id),{action:'archive'}),'Registro arquivado.');
      if(result)await refresh(current.id);
    },'danger-action');
    const restore=button('Restaurar',async()=>{
      const current=rows.find(row=>String(row.id)===chooser.value);
      if(!current)return;
      const result=await safeRun(()=>API('/api/admin/catalog-management/'+group+'/'+encodeURIComponent(current.id),{action:'restore'}),'Registro restaurado.');
      if(result)await refresh(current.id);
    },'soft-action');
    actions.append(save,archive,restore);
    if(group==='cards'){
      const destroy=button('Excluir definitivamente do banco',async()=>{
        const current=rows.find(row=>String(row.id)===chooser.value);
        if(!current)return;
        let impact;
        try{impact=await API('/api/admin/cards/'+encodeURIComponent(current.id)+'/delete-preview');}
        catch(error){report(error.message||'Não foi possível verificar o card.');return;}
        const summary=`EXCLUSÃO PERMANENTE — ${current.name} (ID ${current.id})\n\n`+
          `Cópias de usuários: ${impact.owned}\n`+
          `Reservas em pacotes: ${impact.reservations}\n`+
          `Favoritos: ${impact.favorites}\n`+
          `Trocas: ${impact.trades}\n`+
          `Ofertas em moedas: ${impact.coin_offers}\n`+
          `Moedas a devolver aos compradores: ${impact.escrow_coins}\n\n`+
          'Esses registros serão APAGADOS do banco de dados, com reembolso das ofertas pendentes. A operação não pode ser desfeita. Faça backup antes de prosseguir.\n\n'+
          `Digite EXCLUIR ${current.id} para confirmar:`;
        const confirmation=window.prompt(summary);
        if(confirmation!==`EXCLUIR ${current.id}`)return;
        if(!window.confirm('Última confirmação: excluir PERMANENTEMENTE o card '+current.name+' e todas as referências listadas?'))return;
        const result=await safeRun(()=>API('/api/admin/catalog-management/cards/'+encodeURIComponent(current.id),{
          action:'delete',confirmation,card_name:current.name
        }),'Card excluído definitivamente.');
        if(result){resetCachedData();await refresh();}
      },'danger-action');
      destroy.classList.add('admin-permanent-delete');
      actions.append(destroy);
    }
    form.append(actions);wrap.append(chooser,status,form);box.append(wrap);
    let rows=[];
    const updateForm=()=>{
      const current=rows.find(row=>String(row.id)===chooser.value);
      form.hidden=!current;
      if(!current){status.textContent='Nenhum registro para editar.';return;}
      for(const [key,,kind] of spec){
        inputs[key].value=current[key]??(kind==='number'?0:'');
      }
      if(inputs.image_url)inputs.image_url.dispatchEvent(new Event('change'));
      status.textContent=current.active?'● Ativo':'● Arquivado (não aparece em novos catálogos)';
      status.classList.toggle('off',!current.active);
      archive.hidden=!current.active;restore.hidden=!!current.active;
      if(imageFile)imageFile.value='';if(modelFile)modelFile.value='';
      if(khadaInput)khadaInput.value=khadaIdFromUrl(current.model_url);
    };
    chooser.addEventListener('change',updateForm);
    const load=data=>{
      rows=data[group]||[];let selected=chooser.value;
      chooser.replaceChildren();
      for(const item of rows){const option=h('option','',`${item.id} · ${item.name||item.title}${item.active?'':' (arquivado)'}`);option.value=String(item.id);chooser.append(option);}
      if(rows.some(item=>String(item.id)===selected))chooser.value=selected;
      updateForm();
    };
    const refresh=async(id)=>{
      const data=await API('/api/admin/catalog-management');
      if(id!=null)chooser.value=String(id);
      load(data);
      if(id!=null){chooser.value=String(id);updateForm();}
    };
    collectionPromise.then(load).catch(err=>{status.textContent='Não foi possível carregar registros: '+err.message;});
    return box;
  }

  async function openAdmin(force=false){
    const dialog=$('adminModal');
    dialog.hidden=false;document.body.classList.add('page-open');
    if(state.adminReady && !force)return;
    if(state.adminLoading)return;
    state.adminLoading=true;
    const pane=$('adminContent');
    pane.replaceChildren(h('div','admin-loading','Carregando ferramentas administrativas...'));
    try{
      const authorizedTask=API('/api/admin/authorized-ids');
      const missionsTask=API('/api/admin/missions');
      const catalogTask=API('/api/catalog');
      const gamesTask=API('/api/games/preferences');
      const [opts,game]=await Promise.all([API('/api/admin/settings'),API('/api/game/config')]);
      pane.replaceChildren();
      pane.append(h('p','', 'Apenas IDs do Discord autorizados podem administrar os catálogos e as configurações.'));
    const adminBox=block('Administradores por Discord ID','Somente IDs autorizados podem editar o Recanto. O ID principal é permanente.');
    const idsSummary=h('p','','Carregando administradores...');adminBox.append(idsSummary);
    authorizedTask.then(ids=>{idsSummary.textContent='Administradores fixos: '+ids.permanent.join(', ')+(ids.additional.length?' · IDs extras: '+ids.additional.join(', '):'');})
      .catch(err=>{idsSummary.textContent='Não foi possível listar os administradores: '+err.message;});
    const [adminFieldRow,adminInput]=adminField('Discord ID do novo administrador','');adminBox.append(adminFieldRow);
    adminBox.append(button('Autorizar ID',()=>safeRun(()=>API('/api/admin/authorized-ids',{discord_id:adminInput.value,action:'add'}),'ID autorizado!')),
      button('Revogar ID adicional',()=>safeRun(()=>API('/api/admin/authorized-ids',{discord_id:adminInput.value,action:'remove'}),'Permissão revogada.')));
    pane.append(adminBox);
    const card=block('Cadastrar card','Nome, raridade e imagem (opcional).');const [n,ni]=adminField('Nome','');const [url,ui]=adminField('URL HTTPS da imagem PNG/JPG/WEBP ou /uploads/...','');const [collectionRow,collectionInput]=adminField('Coleção do card','Recanto Original');card.append(n,collectionRow,url);attachArtworkPreview(ui,url);const cardFile=h('input','text-input');cardFile.type='file';cardFile.accept='image/png,image/jpeg,image/webp,.webp';card.append(h('label','','Ou envie imagem PNG/JPG/WEBP (até 4 MB)'),cardFile);const rarity=h('select','select-input');['comum','raro','lendário','prismático'].forEach(t=>{const o=h('option','',tierLabels[t]);o.value=t;rarity.append(o);});card.append(rarity,button('Cadastrar card',()=>safeRun(async()=>{const image_url=cardFile.files.length?await uploadArtwork(cardFile.files[0]):ui.value;return API('/api/admin/cards',{name:ni.value,rarity:rarity.value,collection:collectionInput.value,image_url});},'Card cadastrado!')));pane.append(card);
    const deleteAllCards=block('⚠ Excluir TODOS os Cards','Operação permanente. Apaga o catálogo inteiro, cópias dos membros, Cards favoritos, reservas, trocas e ofertas de moedas relacionadas. Ofertas pendentes são reembolsadas. Pacotes comprados e ainda fechados permanecem no inventário e serão completados com novos Cards quando abertos.');
    deleteAllCards.classList.add('admin-card-bulk-delete');
    deleteAllCards.append(button('Apagar todos os Cards de uma vez',async()=>{
      let impact;
      try{impact=await API('/api/admin/cards/delete-all-preview');}
      catch(err){toast('⚠ '+err.message);return;}
      if(!impact.cards){toast('O catálogo já está vazio.');return;}
      const summary=`EXCLUSÃO TOTAL — ${impact.cards} CARDS\n\n`+
        `Cópias de usuários: ${impact.owned}\n`+
        `Reservas em pacotes: ${impact.reservations}\n`+
        `Favoritos: ${impact.favorites}\n`+
        `Trocas: ${impact.trades}\n`+
        `Ofertas de moedas: ${impact.coin_offers}\n`+
        `Moedas de ofertas pendentes que serão devolvidas: ${impact.escrow_coins}\n\n`+
        'ATENÇÃO: a operação é irreversível. Faça um backup do banco antes de prosseguir.\n\n'+
        'Digite EXCLUIR TODOS OS CARDS para confirmar:';
      const confirmation=window.prompt(summary);
      if(confirmation!=='EXCLUIR TODOS OS CARDS')return;
      if(!window.confirm('CONFIRMAÇÃO FINAL: apagar permanentemente TODOS os '+impact.cards+' Cards e todas as cópias?'))return;
      const result=await safeRun(()=>API('/api/admin/cards/delete-all',{confirmation}),res=>
        `${res.cards_deleted} Cards apagados. ${res.refunded_coins} moedas devolvidas nas ofertas pendentes.`);
      if(result){resetCachedData();state.adminReady=false;await openAdmin(true);}
    },'danger-action'));
    pane.append(deleteAllCards);
    const moveCard=block('Alterar coleção de card existente','Informe o ID do card (visível no catálogo administrativo) e o nome da coleção.');
    const [cardIdLabel,cardIdInput]=adminField('ID do card','', 'number');
    const [newCollectionLabel,newCollectionInput]=adminField('Nova coleção','Recanto Original');
    const idSelect=h('select','select-input');
    idSelect.append(h('option','','Carregando catálogo...'));
    catalogTask.then(catalog=>{idSelect.replaceChildren();for(const c of catalog.items){const o=h('option','',`#${c.id} · ${c.name} (${c.collection||'Recanto Original'})`);o.value=String(c.id);idSelect.append(o);}})
      .catch(err=>{idSelect.replaceChildren(h('option','','Catálogo indisponível: '+err.message));});
    moveCard.append(h('label','','Selecione um card'),idSelect,newCollectionLabel,
      button('Atualizar coleção',()=>safeRun(()=>API('/api/admin/cards/collection',{card_id:Number(idSelect.value),collection:newCollectionInput.value}),'Coleção atualizada!')));
    pane.append(moveCard);
    // Busca unica, em paralelo com o restante do painel, sem segurar sua abertura.
    const existingCatalog=API('/api/admin/catalog-management');
    pane.append(adminCatalogEditor('cards','Gerenciar cards cadastrados',[
      ['name','Nome','text'],['rarity','Raridade','select',Object.entries(tierLabels)],
      ['collection','Coleção','text'],['image_url','Imagem HTTPS ou /uploads/... (vazio remove)','text']
    ],existingCatalog));
    pane.append(adminCatalogEditor('items','Gerenciar itens da Loja',[
      ['name','Nome do produto','text'],['price','Preço em moedas','number'],
      ['image_url','Imagem HTTPS ou /uploads/... (vazio remove)','text']
    ],existingCatalog));
    pane.append(adminCatalogEditor('pets','Gerenciar Poros',[
      ['name','Nome','text'],['emoji','Emoji','text'],['image_url','Capa HTTPS (vazio remove)','text'],
      ['model_url','URL do modelo .glb OU embed Khada (vazio remove)','text'],
      ['idle_animation','Animação idle (opcional)','text'],['pet_animation','Animação de carinho (opcional)','text'],
      ['feed_animation','Animação de alimentação (opcional)','text'],['vet_animation','Animação de veterinário (opcional)','text']
    ],existingCatalog));
    pane.append(adminCatalogEditor('achievements','Gerenciar selos cadastrados',[
      ['title','Título','text'],['description','Descrição','text'],['icon','Emoji','text'],
      ['event','Evento','select',[['trade','Trocas'],['card','Cards recebidos'],['adopt','Poros adotados'],['pet','Carinhos'],['feed','Alimentações'],['mission','Missões resgatadas'],['voice_minutes','Voz no Discord']]],
      ['target','Meta','number'],['image_url','Imagem HTTPS (vazio remove)','text']
    ],existingCatalog));
    const featured=block('Coleção em destaque','Banner que aparece no Catálogo. Existem três coleções padrão: Celebridades, Personagens e Memes.');
    const [featuredNameLabel,featuredName]=adminField('Nome da coleção','Celebridades');
    const [featuredUrlLabel,featuredUrl]=adminField('URL da capa (opcional)','');
    const featuredFile=h('input','text-input');featuredFile.type='file';featuredFile.accept='image/png,image/jpeg,image/webp,.webp';
    featured.append(featuredNameLabel,featuredUrlLabel,h('label','','Ou escolha uma capa'),featuredFile,button('Salvar destaque',()=>safeRun(async()=>API('/api/admin/collections/featured',{name:featuredName.value,image_url:featuredFile.files.length?await uploadArtwork(featuredFile.files[0]):featuredUrl.value}),'Coleção em destaque atualizada!')));pane.append(featured);
    const pet=block('Cadastrar Poro','Aceita imagem, modelo 3D GLB/GLTF e nomes de animações do arquivo.');
    const [pn,pni]=adminField('Nome do Poro','');const [pe,pei]=adminField('Emoji para fallback','🐾');const [pu,pui]=adminField('Imagem de capa (HTTPS ou /uploads/...)','');
    const petFile=h('input','text-input');petFile.type='file';petFile.accept='image/png,image/jpeg,image/webp,.webp';
    const [modelurl,mui]=adminField('URL do modelo .glb ou embed Khada (opcional)','');
    const [khadaRow,khadaId]=adminField('ID de modelo Khada TFT (opcional)','');khadaId.inputMode='numeric';khadaId.placeholder='ID do modelo encontrado em Khada → Tacticians';
    const modelFile=h('input','text-input');modelFile.type='file';modelFile.multiple=true;modelFile.accept='.glb,.gltf,.bin,.png,.jpg,.jpeg,.webp';
    const animKeys=[['idle_animation','Parado / idle'],['pet_animation','Carinho'],['feed_animation','Alimentação'],['vet_animation','Veterinário']];
    const animInputs={};const fields=[];
    for(const [key,label] of animKeys){const [container,inp]=adminField('Nome exato da animação: '+label,'');fields.push(container);animInputs[key]=inp;}
    pet.append(pn,pe,pu,h('label','','Ou envie uma capa PNG/JPG/WEBP (até 4 MB)'),petFile,modelurl,
      khadaRow,h('small','','Para modelos TFT do Khada: encontre o ID em modelviewer.lol e cole acima. O embed gratuito conserva marca e barra do Khada.'),
      h('label','','Ou selecione .glb; para .gltf, selecione também .bin e texturas (até 40 MB no total)'),modelFile,...fields,
      button('Cadastrar Poro',()=>safeRun(async()=>{
        const image_url=petFile.files.length?await uploadArtwork(petFile.files[0]):pui.value;
        const model_url=modelFile.files.length?await uploadModel(modelFile.files):(khadaId.value.trim()?khadaTftUrl(khadaId.value):mui.value);
        if(model_url && !khadaEmbedUrl(model_url) && !/\.glb(?:[?#]|$)/i.test(model_url)){
          throw Error('Modelo inválido: use o ID do Khada TFT ou URL direta de arquivo .glb.');
        }
        const animations=Object.fromEntries(Object.entries(animInputs).map(([key,inp])=>[key,inp.value]));
        return API('/api/admin/pets',{name:pni.value,emoji:pei.value,image_url,model_url,...animations});
      },'Poro cadastrado!')));pane.append(pet);
    // 0.1.21 — Colecionáveis estáticos e resultados das expedições.
    const collectibleBlock=block('Gerenciar Colecionáveis','Itens colecionáveis estáticos que podem ser encontrados nas expedições. Arquivar preserva o inventário existente.');
    const currentCollectibles=(await API('/api/admin/collectibles')).items||[];
    const collectiblesChoice=h('select','select-input');
    const refreshCollectibles=()=>{collectiblesChoice.replaceChildren();const empty=h('option','','+ Novo colecionável');empty.value='';collectiblesChoice.append(empty);
      for(const item of currentCollectibles){const opt=h('option','',`${item.id} · ${item.name}${item.active?'':' (arquivado)'}`);opt.value=String(item.id);collectiblesChoice.append(opt);}};
    refreshCollectibles();
    const [collectName,collectNameInput]=adminField('Nome','');
    const [collectInfo,collectInfoInput]=adminField('Descrição','');
    const [collectEmoji,collectEmojiInput]=adminField('Emoji caso não tenha imagem','🏆');
    const [collectCover,collectCoverInput]=adminField('URL HTTPS da imagem (opcional)','');
    const collectFile=h('input','text-input');collectFile.type='file';collectFile.accept='image/png,image/jpeg,image/webp,.webp';
    const collectEnabled=h('input');collectEnabled.type='checkbox';collectEnabled.checked=true;
    collectiblesChoice.onchange=()=>{const obj=currentCollectibles.find(x=>String(x.id)===collectiblesChoice.value);
      collectNameInput.value=obj?.name||'';collectInfoInput.value=obj?.description||'';collectEmojiInput.value=obj?.emoji||'🏆';
      collectCoverInput.value=obj?.image_url||'';collectEnabled.checked=obj?.active!==false;collectFile.value='';};
    const saveCollectibles=async()=>{const id=collectiblesChoice.value?Number(collectiblesChoice.value):null;
      const payload={id,name:collectNameInput.value,description:collectInfoInput.value,emoji:collectEmojiInput.value,
        image_url:collectFile.files.length?await uploadArtwork(collectFile.files[0]):collectCoverInput.value,active:collectEnabled.checked};
      return API('/api/admin/collectibles',payload);};
    collectibleBlock.append(h('label','','Editar existente ou criar novo'),collectiblesChoice,collectName,collectInfo,collectEmoji,collectCover,
      h('label','','Ou enviar imagem'),collectFile,h('label','admin-check','Ativo'),collectEnabled,
      button('Salvar colecionável',async()=>{const result=await safeRun(saveCollectibles,'Colecionável salvo!');if(result){state.adminReady=false;state.adminGroup='Poros';await openAdmin(true);}}));
    pane.append(collectibleBlock);

    const expeditionBlock=block('Configurar Expedições','A chance de card e de colecionável são independentes. Em cada expedição, o resultado é definido no servidor.');
    const expData=await API('/api/admin/expeditions');
    const expChoice=h('select','select-input');for(const opt of expData.items||[]){const item=h('option','',opt.name);item.value=opt.id;expChoice.append(item);}
    const [expCover,expCoverInput]=adminField('Imagem da expedição (HTTPS ou /uploads/...)','');
    const expFile=h('input','text-input');expFile.type='file';expFile.accept='image/png,image/jpeg,image/webp,.webp';
    const [expChance,expChanceInput]=adminField('Probabilidade de ganhar um card (0–100%)','0','number');expChanceInput.min='0';expChanceInput.max='100';
    const weights={};const weightFields=[];
    for(const [id,label] of Object.entries(tierLabels)){const [field,input]=adminField('Peso da raridade '+label,'0','number');input.min='0';input.max='100';input.step='0.1';weights[id]=input;weightFields.push(field);}
    const cardChoice=h('select','select-input');let op=h('option','','Aleatório, seguindo os pesos das raridades');op.value='';cardChoice.append(op);
    for(const card of expData.cards||[]){op=h('option','',`${card.name} · ${tierLabels[card.rarity]||card.rarity}`);op.value=String(card.id);cardChoice.append(op);}
    const collectibleChoice=h('select','select-input');op=h('option','','Nenhum colecionável');op.value='';collectibleChoice.append(op);
    for(const item of expData.collectibles||[]){op=h('option','',item.name);op.value=String(item.id);collectibleChoice.append(op);}
    const [collectChance,collectChanceInput]=adminField('Probabilidade de ganhar o colecionável (0–100%)','0','number');collectChanceInput.min='0';collectChanceInput.max='100';
    const showExpedition=()=>{const item=expData.items.find(x=>x.id===expChoice.value);if(!item)return;
      expCoverInput.value=item.image_url||'';expFile.value='';expChanceInput.value=item.card_chance;
      cardChoice.value=item.featured_card_id||'';collectibleChoice.value=item.collectible_id||'';collectChanceInput.value=item.collectible_chance||0;
      for(const [tier,input] of Object.entries(weights))input.value=item.rarity_weights?.[tier]??0;};
    expChoice.onchange=showExpedition;showExpedition();
    expeditionBlock.append(h('label','','Expedição'),expChoice,expCover,h('label','','Ou enviar imagem'),expFile,
      expChance,h('label','','Peso das raridades (não precisa somar 100)'),...weightFields,
      h('label','','Card específico opcional (se já possuir, converter em moedas)'),cardChoice,
      h('label','','Colecionável como recompensa opcional'),collectibleChoice,collectChance,
      button('Salvar configuração da expedição',async()=>{
        const payload={image_url:expFile.files.length?await uploadArtwork(expFile.files[0]):expCoverInput.value,
          card_chance:Number(expChanceInput.value),collectible_chance:Number(collectChanceInput.value),
          rarity_weights:Object.fromEntries(Object.entries(weights).map(([tier,input])=>[tier,Number(input.value)])),
          featured_card_id:cardChoice.value?Number(cardChoice.value):null,collectible_id:collectibleChoice.value?Number(collectibleChoice.value):null};
        const result=await safeRun(()=>API('/api/admin/expeditions/'+encodeURIComponent(expChoice.value),payload),'Expedição atualizada!');
        if(result){state.adminReady=false;state.adminGroup='Poros';await openAdmin(true);}
      }));
    pane.append(expeditionBlock);
    const covers=block('Capas da Loja e Missões','As capas são opcionais. Elas aparecem nos produtos e nas missões, sem alterar as regras.');
    const source=h('select','select-input');[['shop','Produtos da Loja'],['mission','Missões diárias']].forEach(([value,label])=>{const o=h('option','',label);o.value=value;source.append(o);});
    const target=h('select','select-input');const fillTargets=()=>{
      target.replaceChildren();(source.value==='shop'?[['pack3','Pacote 3 cards'],['pack5','Pacote 5 cards'],['treat3','Biscoitos'],['fruit','Frutinha'],['feast','Banquete'],['vaccine','Vacina']]:[['daily_card','Card diário'],['daily_coins','Moedas diárias'],['trade','Troca'],['pet','Carinho'],['feed','Alimentar'],['adopt','Adoção'],['pack','Pacote']]).forEach(([value,label])=>{const o=h('option','',label);o.value=value;target.append(o);});
    };source.addEventListener('change',fillTargets);fillTargets();
    const [coverRow,coverUrl]=adminField('Capa (HTTPS ou /uploads/...); vazio remove','');const coverFile=h('input','text-input');coverFile.type='file';coverFile.accept='image/png,image/jpeg,image/webp,.webp';
    covers.append(source,target,coverRow,h('label','','Ou selecione imagem no PC'),coverFile,button('Salvar capa',()=>safeRun(async()=>{
      const image_url=coverFile.files.length?await uploadArtwork(coverFile.files[0]):coverUrl.value;
      return API('/api/admin/covers',{kind:source.value,key:target.value,image_url});
    },'Capa atualizada!')));pane.append(covers);
    const ach=block('Criar selo','A conquista pode ser automática ou depender de futura integração de voz.');const [an,ani]=adminField('Título','');const [ad,adi]=adminField('Descrição','');const [ai,aii]=adminField('Emoji','🏅');const [at,ati]=adminField('Meta numérica','1','number');const type=h('select','select-input');for(const [code,label] of Object.entries({trade:'Trocas',card:'Cards recebidos',adopt:'Poros adotados',pet:'Carinhos',feed:'Alimentações',mission:'Missões resgatadas',voice_minutes:'Minutos em voz (integração futura)'})){const o=h('option','',label);o.value=code;type.append(o);}ach.append(an,ad,ai,at,type,button('Criar selo',()=>safeRun(()=>API('/api/admin/achievements',{title:ani.value,description:adi.value,icon:aii.value,event:type.value,target:Number(ati.value)}),'Selo criado!')));pane.append(ach);
    // Gerenciador de assets: aplica a arte a elementos sem alterar seus cliques ou regras.
    const assetPane=block('🖼️ Central de Assets','Personalize o favicon, menus de PC e celular, logos, jogos e fundos. Envie PNG/JPG/WEBP ou SVG seguro; as artes ficam salvas no servidor (Cloudinary em produção).');
    const existingAssets=(await API('/api/assets')).items;
    const baseSlots=[
      ['favicon','link[rel="icon"]','image','Favicon (aba do navegador)'],
      ['logo-login','#loginScreen .brand-logo','image','Logo na tela de login'],
      ['logo-loading','#splashScreen .splash-logo','image','Logo na tela de carregamento'],
      ['fundo-login','#loginScreen','background','Fundo do login'],
      ['fundo-app','#homeScreen','background','Fundo geral do aplicativo'],
      ['barra-inferior','.bottom-nav','background','Barra inferior'],
      ['menu-config','.desktop-side-link#desktopSettings','icon','Ícone Configurações (PC)'],
      ['botao-config','#settings','icon','Icone de configuracoes'],
      ['botao-perfis','#searchUsers','icon','Icone da busca de perfis'],
      ['nav-feed','[data-tab="feed"] .nav-circle, .desktop-side-link[data-tab="feed"]','icon','Ícone Feed'],
      ['nav-perfil','[data-tab="perfil"] .nav-circle, .desktop-side-link[data-tab="perfil"]','icon','Icone Perfil'],
      ['nav-cards','[data-tab="cards"] .nav-circle, .desktop-side-link[data-tab="cards"]','icon','Icone Cards'],
      ['nav-inventario','[data-tab="inventario"] .nav-circle, .desktop-side-link[data-tab="inventario"]','icon','Icone Inventario'],
      ['nav-pet','[data-tab="pet"] .nav-circle, .desktop-side-link[data-tab="pet"]','icon','Ícone dos Poros'],
      ['nav-loja','[data-tab="loja"] .nav-circle, .desktop-side-link[data-tab="loja"]','icon','Icone Loja'],
      ['nav-missoes','[data-tab="missoes"] .nav-circle, .desktop-side-link[data-tab="missoes"]','icon','Icone Missoes'],
      ['moedas-perfil','.stats-list .stat:nth-child(1) .stat-icon','icon','Icone de moedas'],
      ['cards-perfil','.stats-list .stat:nth-child(2) .stat-icon','icon','Icone de cards'],
      ['petiscos-perfil','.stats-list .stat:nth-child(3) .stat-icon','icon','Icone de petiscos'],
      ['card-diario','#dailyCardIcon','background','Fundo do card diario'],
      ['capa-pack-revelacao','.flip-back','background','Verso do card na abertura']
    ];
    const allSlots=[...baseSlots];
    const chooseSlot=h('select','select-input');
    for(const [key,sel,mode,name] of allSlots){const o=h('option','',name);o.value=key;chooseSlot.append(o);}
    gamesTask.then(gamesData=>{for(const g of gamesData.catalog){const entry=[`game:${g.id}`,'','icon',`Jogo · ${g.name}`];allSlots.push(entry);const o=h('option','',entry[3]);o.value=entry[0];chooseSlot.append(o);}}).catch(()=>{});
    const [customKeyRow,customKey]=adminField('Ou crie uma chave personalizada (opcional)','');
    const [customSelectorRow,customSelector]=adminField('Seletor CSS do elemento personalizado (opcional)','');
    const modeSelect=h('select','select-input');for(const [key,label] of [['background','Imagem de fundo'],['icon','Icone sobre o elemento'],['image','Imagem (tag img)']]){const op=h('option','',label);op.value=key;modeSelect.append(op);}
    const [assetUrlRow,assetUrl]=adminField('URL HTTPS da imagem ou /uploads/...','');
    const assetFile=h('input','text-input');assetFile.type='file';assetFile.accept='.svg,image/svg+xml,image/png,image/jpeg,image/webp';
    const assetPreview=h('div','admin-asset-preview');
    const preview=()=>{const entry=existingAssets.find(a=>a.key===chooseSlot.value);assetPreview.replaceChildren();if(entry?.image_url){const pic=h('img');pic.src=entry.image_url;pic.alt='Arte atual';assetPreview.append(pic,h('span','',entry.image_url));}else assetPreview.append(h('span','', 'Nenhuma imagem configurada para este elemento.'));};
    chooseSlot.onchange=()=>{const sel=allSlots.find(row=>row[0]===chooseSlot.value);modeSelect.value=sel?.[2]||'background';assetUrl.value=existingAssets.find(row=>row.key===chooseSlot.value)?.image_url||'';assetFile.value='';preview();};chooseSlot.onchange();
    const saveAsset=async(remove=false)=>{
      const slot=allSlots.find(row=>row[0]===chooseSlot.value);
      const key=customKey.value.trim()||chooseSlot.value;
      const selector=customKey.value.trim()?customSelector.value.trim():(slot?.[1]||'');
      const mode=customKey.value.trim()?modeSelect.value:(slot?.[2]||'icon');
      const image_url=remove?'':(assetFile.files.length?await uploadArtwork(assetFile.files[0]):assetUrl.value.trim());
      const result=await API('/api/admin/assets',{key,selector,mode,image_url});
      if(result.ok){assetFile.value='';assetUrl.value='';const all=await API('/api/assets');state.assets=all.items||[];existingAssets.splice(0,existingAssets.length,...state.assets);applyUiAssets();preview();}
      return result;
    };
    assetPane.append(h('label','','Elemento a personalizar'),chooseSlot,customKeyRow,customSelectorRow,
      h('label','','Formato do asset personalizado'),modeSelect,assetUrlRow,
      h('label','','Ou envie um arquivo de imagem'),assetFile,assetPreview,
      button('Salvar imagem',()=>safeRun(()=>saveAsset(false),'Asset salvo!')),
      button('Remover imagem do elemento',()=>safeRun(()=>saveAsset(true),'Asset removido.'),'soft-action'));
    assetPane.append(h('p','asset-help','Os ícones de menu alteram PC e celular juntos. O favicon muda a aba do navegador; o ícone de instalação do PWA continua separado. SVGs perigosos são recusados. Para outros elementos, use chave e seletor CSS.'));
    pane.append(assetPane);
    const missionData={items:[]};
    const missionBlock=block('Missões do Recanto','Crie e edite missões únicas, diárias ou semanais. As semanais entram na semana atual; após a próxima segunda-feira, cadastre/reative as missões da nova semana.');
    const existing=h('select','select-input');
    existing.append(Object.assign(h('option','','Nova missão'),{value:''}));
    missionsTask.then(data=>{missionData.items=data.items||[];for(const row of missionData.items){const o=h('option','',poroLegacyText(row.title)+' ['+row.code+']');o.value=row.code;existing.append(o);}})
      .catch(err=>{missionBlock.append(h('p','', 'Missões indisponíveis: '+err.message));});
    const mFields={};
    for(const [key,label,value] of [['code','Código único (ex: voz_30)',''],['title','Título',''],['goal','Meta numérica','1'],['reward','Recompensa em moedas','10'],['emoji','Emoji','🎯'],['image_url','Capa URL HTTPS (opcional)','']]){
      const [wrap,inp]=adminField(label,value,(['goal','reward'].includes(key)?'number':'text'));
      mFields[key]=inp;missionBlock.append(wrap);
    }
    const missionType=h('select','select-input');for(const [v,t] of [['unica','Única'],['diaria','Diária'],['semanal','Semanal']]){const opt=h('option','',t);opt.value=v;missionType.append(opt);}
    const missionEvent=h('select','select-input');for(const [v,t] of [['adopt','Adotar Poro'],['trade','Trocar card'],['daily_card','Resgatar card'],['daily_coins','Resgatar moedas'],['pet','Acariciar Poro'],['feed','Alimentar Poro'],['pack','Abrir pack'],['voice_minutes','Minutos em canal de voz'],['message_count','Mensagens de texto']]){const opt=h('option','',t);opt.value=v;missionEvent.append(opt);}
    const enabled=h('input');enabled.type='checkbox';enabled.checked=true;
    existing.onchange=()=>{const row=missionData.items.find(m=>m.code===existing.value);if(!row)return;
      for(const key of Object.keys(mFields))mFields[key].value=row[key]??'';
      missionType.value=row.kind;missionEvent.value=row.event;enabled.checked=row.enabled;};
    missionBlock.prepend(h('label','','Editar missão cadastrada ou criar nova'),existing);
    const imageUpload=h('input','text-input');imageUpload.type='file';imageUpload.accept='image/png,image/jpeg,image/webp,.webp';
    missionBlock.append(h('label','','Tipo de missão'),missionType,h('label','','Ação que conta progresso'),missionEvent,h('label','','Ou envie a imagem da missão'),imageUpload,h('label','','Missão ativa'),enabled,
      button('Salvar missão',async()=>{const payload=Object.fromEntries(Object.entries(mFields).map(([k,v])=>[k,v.value]));
        payload.goal=Number(payload.goal);payload.reward=Number(payload.reward);payload.kind=missionType.value;payload.event=missionEvent.value;payload.enabled=enabled.checked;
        const result=await safeRun(async()=>{if(imageUpload.files.length)payload.image_url=await uploadArtwork(imageUpload.files[0]);return API('/api/admin/missions',payload);},'Missão cadastrada/atualizada!');if(result){state.adminReady=false;await openAdmin(true);}}));
    const missionVisibility=h('div','admin-action-row');
    missionVisibility.append(
      button('Remover missão (desativar)',async()=>{
        if(!existing.value){toast('Selecione uma missão cadastrada.');return;}
        if(!window.confirm('Desativar esta missão? O progresso histórico será preservado.'))return;
        const result=await safeRun(()=>API('/api/admin/missions/'+encodeURIComponent(existing.value)+'/visibility',{enabled:false}),'Missão removida da lista ativa.');
        if(result){state.adminReady=false;await openAdmin(true);}
      },'danger-action'),
      button('Restaurar missão',async()=>{
        if(!existing.value){toast('Selecione uma missão cadastrada.');return;}
        const result=await safeRun(()=>API('/api/admin/missions/'+encodeURIComponent(existing.value)+'/visibility',{enabled:true}),'Missão reativada.');
        if(result){state.adminReady=false;await openAdmin(true);}
      },'soft-action')
    );
    missionBlock.append(missionVisibility);
    pane.append(missionBlock);
    const integrations=block('Integrações','Missões de voz e mensagens requerem RECANTO_BOT_SECRET no Render e um pequeno envio de eventos pelo seu bot existente. Notificações exigem chaves VAPID e o job agendado; consulte o guia no ZIP.');
    pane.append(integrations);
    const settings=block('Valores configuráveis','Recompensas, preços e prazos.');for(const [key,value] of Object.entries(opts.settings)){const [fld,inp]=adminField(key,value,'number');settings.append(fld,button('Salvar '+key,()=>safeRun(()=>API('/api/admin/settings',{key,value:Number(inp.value)}),'Valor salvo!'),'soft-action'));}pane.append(settings);
    if(game.local_development && ['localhost','127.0.0.1'].includes(location.hostname)){
      const dev=block('Ferramentas de teste local','Simulações exclusivas do ambiente local.');
      dev.append(button('Adicionar 5.000 moedas para minha conta',()=>safeRun(()=>API('/api/dev/grant-coins',{amount:5000}),'Moedas de teste adicionadas!')));
      dev.append(button('Simular abandono → veterinário',()=>safeRun(()=>API('/api/dev/advance-pet',{stage:'vet'}),'Poro no veterinário!'),'soft-action'));
      dev.append(button('Simular prazo vencido → morte',()=>safeRun(()=>API('/api/dev/advance-pet',{stage:'death'}),'Prazo encerrado!'),'soft-action'));
      pane.append(dev);
    }
    const tools=block('Ferramentas administrativas','Operações destinadas a administradores Discord. Funcionam também em celulares.');
    tools.append(button('Reiniciar meus resgates diários',async()=>{
      const result=await safeRun(()=>API('/api/admin/reset-daily',{}),'Seus resgates foram reiniciados!');
      if(result)await openAdmin(true);
    }));
    pane.append(tools);
    // Ajuste manual de moedas: permitido apenas para administradores no backend.
    const coinTool=block('Ajustar moedas de um usuário','Para testes: utilize o ID numérico do Discord. Nenhuma outra conta será alterada.');
    const [userIdRow,userIdInput]=adminField('ID do usuário no Discord','');
    userIdInput.inputMode='numeric';userIdInput.autocomplete='off';
    const [amountRow,amountInput]=adminField('Quantidade de moedas','100','number');
    amountInput.min='1';amountInput.max='100000';amountInput.step='1';
    const coinActions=h('div','admin-action-row');
    async function adjustCoins(action){
      const discord_id=userIdInput.value.trim();
      const amount=Number(amountInput.value);
      if(!/^\d{15,22}$/.test(discord_id)){toast('Informe o ID numérico do Discord (15 a 22 dígitos).');return;}
      if(!Number.isSafeInteger(amount)||amount<1||amount>100000){toast('Informe entre 1 e 100.000 moedas.');return;}
      if(!window.confirm((action==='add'?'Adicionar ':'Remover ')+amount+' moedas '+(action==='add'?'para':'de')+' '+discord_id+'?'))return;
      const result=await safeRun(()=>API('/api/admin/wallet/adjust',{discord_id,amount,action}),action==='add'?'Moedas adicionadas.':'Moedas removidas.');
      if(result){coinStatus.textContent='Saldo atualizado: '+result.balance+' moedas.'; if(state.account?.id===discord_id||state.account?.discord_id===discord_id){state.account.coins=result.balance;$('desktopWallet').textContent=money(result.balance);$('valMoedas').textContent=money(result.balance);}}
    }
    coinActions.append(button('Adicionar moedas',()=>adjustCoins('add')),button('Remover moedas',()=>adjustCoins('remove'),'danger-action'));
    const coinStatus=h('p','admin-entry-status','');
    coinTool.append(userIdRow,amountRow,coinActions,coinStatus);pane.append(coinTool);
    // Exclusivo dos administradores: zera apenas as publicações do Feed.
    const feedTool=block('Limpar Feed',
      'Remove todas as publicações e curtidas da comunidade. Cards, Poros, moedas, missões, selos e o limite diário de recompensas permanecem intactos. Esta operação não pode ser desfeita.');
    const [feedConfirmField,feedConfirmInput]=adminField('Digite LIMPAR FEED para confirmar','');
    feedConfirmInput.autocomplete='off';
    feedConfirmInput.setAttribute('aria-label','Confirmação da limpeza do Feed');
    const feedClearButton=button('Apagar todas as publicações do Feed',async()=>{
      if(feedConfirmInput.value.trim()!=='LIMPAR FEED'){
        toast('Digite LIMPAR FEED para confirmar.');return;
      }
      if(!window.confirm('Excluir TODAS as publicações e curtidas do Feed? Essa operação não pode ser desfeita.'))return;
      feedClearButton.disabled=true;
      const result=await safeRun(()=>API('/api/admin/feed/clear',
        {confirmation:feedConfirmInput.value.trim()}),
        r=>`${r.removed} publicação(ões) removida(s) do Feed.`);
      if(result){
        feedConfirmInput.value='';
        tabLoadedAt.feed=0;
        loadFeedRefresh().catch(()=>{});
        feedResult.textContent=`Feed limpo. ${result.removed} publicação(ões) removida(s).`;
      }else feedClearButton.disabled=false;
    },'danger-action');
    feedClearButton.disabled=true;
    feedConfirmInput.addEventListener('input',()=>{
      feedClearButton.disabled=feedConfirmInput.value.trim()!=='LIMPAR FEED';
    });
    const feedResult=h('p','admin-entry-status','');
    feedTool.append(feedConfirmField,feedClearButton,feedResult);pane.append(feedTool);

    const reset=block('Limpar progresso para testes','ATENÇÃO: apaga o progresso de TODOS os usuários (cards obtidos, moedas, Poros, trocas, selos e missões). As contas Discord e os catálogos permanecem. A operação não pode ser desfeita.');
    const [field,confirmation]=adminField('Digite LIMPAR TUDO para confirmar','');
    const resetButton=button('Apagar progresso de todos os usuários',async()=>{
      if(confirmation.value.trim()!=='LIMPAR TUDO'){toast('Digite LIMPAR TUDO para confirmar.');return;}
      if(!window.confirm('ATENÇÃO: apagar todo o progresso de TODOS os usuários? Não é possível desfazer.'))return;
      const result=await safeRun(()=>API('/api/admin/reset-progress',{confirmation:confirmation.value.trim()}),'Progresso reiniciado!');
      if(result){confirmation.value='';resetButton.disabled=true;await openAdmin(true);}
    },'danger-action');
    resetButton.disabled=true;
    confirmation.addEventListener('input',()=>resetButton.disabled=confirmation.value.trim()!=='LIMPAR TUDO');
    reset.append(field,resetButton);pane.append(reset);
    const groups=['Geral','Feed','Economia','Cards','Loja','Poros','Missões','Selos','Assets','Usuários','Integrações'];
    const classify=(name)=>{
      const x=name.toLowerCase();
      if(x.includes('limpar feed'))return 'Feed';
      if(x.includes('valores configuráveis'))return 'Economia';
      if(x.includes('cadastrar card')||x.includes('gerenciar cards')||x.includes('coleção'))return 'Cards';
      if(x.includes('gerenciar itens')||x.includes('capa'))return 'Loja';
      if(x.includes('cadastrar poro')||x.includes('gerenciar poros')||x.includes('colecionáveis')||x.includes('expedições'))return 'Poros';
      if(x.includes('missões do recanto'))return 'Missões';
      if(x.includes('selo'))return 'Selos';
      if(x.includes('assets'))return 'Assets';
      if(x.includes('administrador')||x.includes('ids autorizados')||x.includes('ajustar moedas'))return 'Usuários';
      if(x.includes('integrações'))return 'Integrações';
      return 'Geral';
    };
    const boxes=[...pane.querySelectorAll(':scope > .game-box')];
    for(const box of boxes)box.dataset.adminGroup=classify(box.querySelector('h3')?.textContent||'');
    const nav=h('div','admin-tabs');
    const showGroup=group=>{state.adminGroup=group;for(const box of boxes)box.hidden=box.dataset.adminGroup!==group;
      for(const btn of nav.querySelectorAll('button'))btn.classList.toggle('selected',btn.dataset.group===group);};
    for(const group of groups){const btn=button(group,()=>showGroup(group),'admin-tab');btn.dataset.group=group;nav.append(btn);}
    const adminDialog=$('adminModal').querySelector('.admin-dialog');
    adminDialog.querySelector('.admin-tabs')?.remove();
    adminDialog.insertBefore(nav,pane);showGroup(state.adminGroup||'Geral');
    state.adminReady=true;pane.scrollTop=0;
    }catch(err){pane.replaceChildren(h('div','admin-loading','Não foi possível carregar a gestão: '+err.message));}
    finally{state.adminLoading=false;}
  }
  $('login').onclick=login;
  $('settings').onclick=()=>{
    $('modal').hidden=false;
    $('settingsAdmin').hidden=!(state.game?.admin===true);
    loadNotification();
    // Atualiza a permissão sem exibir o painel a quem não é administrador.
    API('/api/game/config').then(game=>{
      state.game=game;
      if(!$('modal').hidden)$('settingsAdmin').hidden=!game.admin;
    }).catch(()=>{$('settingsAdmin').hidden=true;});
  };
  $('desktopSearch').onclick=()=>searchProfiles();
  $('desktopSettings').onclick=()=>$('settings').click();
  $('desktopSettingsTop').onclick=()=>$('settings').click();
  $('desktopSeePet').onclick=()=>chooseTab('pet');
  $('mobileSeePet').onclick=()=>chooseTab('pet');
  $('refreshAdmin').onclick=()=>{resetCachedData();state.adminReady=false;openAdmin(true);};
  $('settingsAdmin').onclick=()=>{
    if($('settingsAdmin').hidden)return;
    $('modal').hidden=true;
    openAdmin(); // Validação real do ID continua no backend.
  };
  $('closeSettings').onclick=()=>{$('modal').hidden=true;};
  if(matchMedia('(min-width:768px)').matches){const t=$('missionTimer');const title=$('missionsScreen').querySelector('.content-head h1');if(t&&title)title.after(t);}
  $('logout').onclick=async()=>{try{await API('/api/auth/logout',{});showLogin();}catch(err){toast(err.message);}};
  $('notificationsToggle').onclick=toggleNotifications;
  $('darkModeToggle').onclick=toggleDarkMode;
  $('checkUpdates').onclick=async()=>{
    if(!('serviceWorker' in navigator)){toast('Atualizações automáticas disponíveis apenas no PWA instalado/HTTPS.');return;}
    try{const reg=await navigator.serviceWorker.getRegistration();if(!reg){toast('Abra o Recanto no endereço HTTPS e instale o aplicativo.');return;}await reg.update();toast('Verificação realizada. Se houver uma versão nova, aparecerá a opção Atualizar.');}
    catch(_){toast('Não foi possível verificar atualizações agora.');}
  };
  $('installApp').onclick=async()=>{
    if(matchMedia('(display-mode: standalone)').matches){toast('O Recanto já está instalado.');return;}
    if(state.installEvent){
      const ev=state.installEvent;state.installEvent=null;ev.prompt();
      try{await ev.userChoice;}catch(_){}updateInstallButton();return;
    }
    toast(/iPhone|iPad/i.test(navigator.userAgent)?'No Safari, toque em Compartilhar → Adicionar à Tela de Início.':'No Chrome, abra o menu ⋮ e escolha Instalar aplicativo ou Adicionar à tela inicial.');
  };
  $('searchUsers').onclick=searchProfiles;
  $('closeProfiles').onclick=()=>{$('profilesModal').hidden=true;};
  document.querySelectorAll('[data-inventory-tab]').forEach(btn=>btn.addEventListener('click',()=>inventoryPane(btn.dataset.inventoryTab).catch(err=>toast(err.message))));
  $('revealNext').onclick=revealNext;
  $('flipStage').onclick=revealNext;
  $('revealExit').onclick=()=>{$('packReveal').hidden=true;state.reveal=null;chooseTab('inventario');};

  $('dailyCoins').onclick=async()=>{
    const el=$('dailyCoins');if(state.dailyClaimInFlight||el.disabled)return;
    state.dailyClaimInFlight=true;
    const originalText=el.textContent;
    const expected=Number(state.dailyReward||0);
    // Valor provisório explicitamente sinalizado até confirmação do backend.
    pendingCoinsPreview+=expected;paintCoins();
    el.disabled=true;el.classList.add('action-pending');el.setAttribute('aria-busy','true');
    el.textContent='Confirmando resgate…';
    try{
      const response=await API('/api/daily/coins',{});
      pendingCoinsPreview-=expected;
      applyConfirmedCoins(response,expected);
      el.textContent='✓ Resgatado';el.disabled=true;
      state.dailyClaimInFlight=false;state.reset=state.reset||null;
      updateCountdowns();resetCachedData();toast(`+${money(response.coins_gained??expected)} moedas resgatadas!`);
      reconcileAfterAction();
    }catch(err){
      pendingCoinsPreview-=expected;paintCoins();
      el.textContent=originalText;el.disabled=false;
      toast('⚠ '+(err?.message||'Não foi possível resgatar.'));
      resetCachedData();reconcileAfterAction();
    }finally{
      state.dailyClaimInFlight=false;el.classList.remove('action-pending');el.removeAttribute('aria-busy');
    }
  };
  $('dailyCard').onclick=async()=>{const result=await safeRun(()=>API('/api/daily/card',{}),'Card diário recebido!',r=>{applyConfirmedCoins({coins_gained:r?.card?.bonus_coins??0});$('dailyCard').disabled=true;$('dailyCard').textContent='⏳ Aguardar 5h';});if(result?.card)showCard(result.card,`+${result.card.bonus_coins??result.card_bonus??state.game?.rules?.['card_bonus_'+result.card.rarity]??1} moedas pelo card!`);};
  document.querySelectorAll('[data-tab]').forEach(btn=>btn.addEventListener('click',()=>chooseTab(btn.dataset.tab)));
  document.querySelectorAll('[data-card-tab]').forEach(btn=>btn.addEventListener('click',()=>cardPane(btn.dataset.cardTab).catch(err=>toast(err.message))));
  $('closeCardDetail').onclick=closeCardDetail;$('closeAdmin').onclick=()=>{$('adminModal').hidden=true;document.body.classList.remove('page-open');};
  $('backToMyProfile').onclick=()=>{$('publicProfilePage').hidden=true;$('profilesModal').hidden=true;chooseTab('perfil');};
  $('backToSearchTop').onclick=()=>{$('publicProfilePage').hidden=true;searchProfiles();};
  for(const id of ['modal','cardModal','profilesModal'])$(id).addEventListener('click',e=>{if(e.target===$(id)){if(id==='cardModal')closeCardDetail();else $(id).hidden=true;}});
  window.addEventListener('keydown',e=>{if(e.key==='Escape')for(const id of ['modal','profilesModal'])$(id).hidden=true;closeCardDetail();});
  
  async function showWelcome(me){
    $('loginScreen').hidden=true;$('homeScreen').hidden=true;
    const splash=$('splashScreen');splash.hidden=false;splash.classList.remove('splash-fade');
    const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
    renderProfile(me);
    // Renderizar o perfil imediatamente; carregar detalhes em segundo plano.
    const firstTab=chooseTab('perfil');
    await Promise.race([firstTab,sleep(280)]);
    // Trabalho secundário só depois da primeira tela pronta.
    setTimeout(()=>{loadUiAssets().catch(()=>{});},650);
    setTimeout(()=>{if(state.account && !document.hidden)prefetchTabs().catch(()=>{});},1500);
    if(!reduced){splash.classList.add('splash-fade');await sleep(150);}
    splash.hidden=true;splash.classList.remove('splash-fade');
  }
  // iOS/Android: usar a altura real visível, sem permitir que o body role e desloque a tela.
  function syncViewport(){
    const height=window.innerHeight;
    if(height>200)document.documentElement.style.setProperty('--recanto-height',`${Math.round(height)}px`);
  }
  syncViewport();
  window.addEventListener('resize',syncViewport,{passive:true});
  // Não use visualViewport.height: o teclado do iOS/Android encolhe e desloca o app.
  window.addEventListener('pageshow',syncViewport,{passive:true});
  loadTheme();
  loadUiAssets().catch(()=>{});
  updateInstallButton();
  window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();state.installEvent=e;updateInstallButton();});
  window.addEventListener('appinstalled',()=>{state.installEvent=null;updateInstallButton();toast('Recanto instalado com sucesso!');});
  window.matchMedia('(display-mode: standalone)').addEventListener?.('change',updateInstallButton);
  startMobileGestures();
  startFeedPolling();
  setInterval(updateCountdowns,1000);
  (async()=>{
    // Enquanto a sessão é verificada, não exibir o botão de login para quem já está autenticado.
    $('loginScreen').hidden=true;
    $('splashScreen').hidden=false;
    const params=new URLSearchParams(location.search);
    if(params.has('login_error')){report('Não foi possível concluir o login Discord: '+params.get('login_error'));history.replaceState(null,'',location.pathname);}
    try{
      // /api/config não deve bloquear a sessão nem a primeira renderização.
      const configTask=retryBootstrap('/api/config').then(c=>{state.config=c;}).catch(()=>{});
      const me=await retryBootstrap('/api/me');
      if(me?.authenticated){report('');await showWelcome(me);return;}
      showLogin();
      await configTask;
    }catch(err){if(!state.account){showLogin();report('Conexão temporariamente indisponível. Tente novamente em instantes.');}}
  })();
  // Atualizações do PWA: nunca reinstalar; confirmar no próprio app.
  // Não interrompe a abertura de pacotes nem formulários em andamento.
  if(window.isSecureContext && 'serviceWorker' in navigator){
    let pendingWorker = null;
    let refreshing = false;
    const hadControllerAtBoot = !!navigator.serviceWorker.controller;
    const banner=$('updateBanner');
    const presentUpdate = reg => {
      if(reg.waiting && navigator.serviceWorker.controller){
        pendingWorker=reg.waiting;
        banner.hidden=false;
      }
    };
    $('updateNow').onclick=()=>{
      if(pendingWorker){$('updateNow').disabled=true;pendingWorker.postMessage({type:'SKIP_WAITING'});}
      else {banner.hidden=true;location.reload();}
    };
    $('updateLater').onclick=()=>{banner.hidden=true;};
    navigator.serviceWorker.addEventListener('controllerchange',()=>{
      // Evita recarregar desnecessariamente na PRIMEIRA instalação do PWA.
      if(!hadControllerAtBoot || refreshing)return;
      refreshing=true;
      location.reload();
    });
    window.addEventListener('load',async()=>{
      try{
        const reg=await navigator.serviceWorker.register('/sw.js', {updateViaCache:'none'});
        presentUpdate(reg);
        reg.addEventListener('updatefound',()=>{
          const installing=reg.installing;
          if(installing)installing.addEventListener('statechange',()=>{
            if(installing.state==='installed')presentUpdate(reg);
          });
        });
        const check=()=>reg.update().catch(()=>{});
        // Evita múltiplas verificações de atualização a cada retorno ao PWA.
        setInterval(()=>{if(!document.hidden)check();},60*60*1000);
      }catch(_){/* O Recanto também funciona sem Service Worker */}
    });
  }
})();
