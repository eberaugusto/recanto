"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const PREFETCH_TTL=25000;
  const getCache=new Map();
  const cacheable=url=>/^(\/api\/(game\/config|achievements|games\/preferences|shop|daily\/status|catalog|cards|inventory|pets|missions|collections\/featured|assets|community\/profiles))(\?|$|\/)/.test(url);
  function resetCachedData(){getCache.clear();}
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
    const options = { credentials: 'same-origin', headers: {Accept:'application/json'} };
    if (data !== undefined) {options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(data);}
    const response=await fetch(url,options);
    let result;try{result=await response.json();}catch(_){result={detail:'O servidor não respondeu corretamente.'};}
    if(!response.ok)throw Error(result.detail||`Erro HTTP ${response.status}`);
    return result;
  };
  let prefetchPromise=null;
  function prefetchTabs(){
    if(prefetchPromise)return prefetchPromise;
    const urls=['/api/game/config','/api/achievements','/api/games/preferences','/api/daily/status','/api/catalog','/api/shop','/api/inventory','/api/pets','/api/missions','/api/collections/featured'];
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
  const labels={perfil:'Perfil',cards:'Cards',inventario:'Inventário',pet:'Pet',loja:'Loja',missoes:'Missões'};
  const tierLabels={comum:'Comum',raro:'Raro',lendário:'Lendário',prismático:'Prismático'};
  const state={assets:[],account:null,config:{},game:null,tab:'perfil',cardTab:'colecao',reset:null,cardReset:null,missionReset:null,installEvent:null,notification:false,notificationBusy:false,tabTransition:0,focusShop:null,petAction:null,inventoryTab:'packs',reveal:null,revealIndex:0,revealFace:false,badgesVisible:8,darkMode:false,cardFilters:{rarity:'todos',collection:'todas',alphabetical:'padrao',missing:false,newOnly:false},detailClosing:false};
  const toast=(message)=>{const el=$('toast');el.textContent=message;el.hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>{el.hidden=true;},4800);};
  const report=msg=>{$('message').textContent=msg||'';};
  const button=(text,handler,style='main-action')=>{const b=h('button',style,text);b.type='button';b.addEventListener('click',handler);return b;};
  const block=(title,body)=>{const div=h('div','game-box');if(title)div.append(h('h3','',title));if(body)div.append(h('p','',body));return div;};
  const safeRun=async(action,success)=>{try {const result=await action();resetCachedData();if(success)toast(typeof success==='function'?success(result):success);await refreshProfile();await refreshActive();return result;}catch(err){toast('⚠ '+err.message);return null;}};
  function countdown(iso){if(!iso)return '—';const delta=new Date(iso).getTime()-Date.now();if(delta<=0)return 'Disponível agora';let s=Math.ceil(delta/1000);const d=Math.floor(s/86400);s%=86400;const hour=Math.floor(s/3600);s%=3600;const minute=Math.floor(s/60);const sec=s%60;return (d?`${d}d `:'')+`${String(hour).padStart(2,'0')}:${String(minute).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;}
  function updateCountdowns(){if(state.reset){const t=countdown(state.reset);$('cardCountdown').textContent=$('dailyCard').disabled?'Novo card em '+countdown(state.cardReset):'Disponível agora (a cada 5h)!';$('coinCountdown').textContent=$('dailyCoins').disabled?'Próximo resgate: '+t:'Resgate disponível!';}if(state.missionReset)$('missionTimer').textContent='Missões reiniciam em: '+countdown(state.missionReset);}
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
    btn.hidden=false;
    const installed=matchMedia('(display-mode: standalone)').matches || navigator.standalone===true;
    btn.disabled=installed;
    btn.querySelector('span').textContent=installed?'Instalado':'Instalar';
  }
  function renderProfile(me){state.account=me;$('loginScreen').hidden=true;$('homeScreen').hidden=false;$('modal').hidden=true;$('userName').textContent='Olá, '+me.name;$('valMoedas').textContent=money(me.coins);$('valCards').textContent=money(me.cards);$('valPetiscos').textContent=money(me.treats);avatar($('userAvatar'),me.name,me.avatar_url);const recent=$('latestCard');recent.replaceChildren();recent.classList.toggle('has-card',!!me.last_card);recent.setAttribute('aria-label',me.last_card?'Ampliar último card: '+me.last_card.name:'Nenhum card obtido ainda');recent.onclick=me.last_card?()=>showCard(me.last_card,'Último card recebido'):null;if(me.last_card&&me.last_card.image_url){const img=h('img');img.src=me.last_card.image_url;img.alt=me.last_card.name;recent.append(img);}else recent.textContent=me.last_card?me.last_card.name:'?';}
  $('latestCard').addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&state.account?.last_card){e.preventDefault();showCard(state.account.last_card,'Último card recebido');}});
  async function refreshProfile(){if(!state.account)return;const me=await API('/api/me');if(me.authenticated)renderProfile(me);else showLogin();}
  function showLogin(){resetCachedData();state.account=null;$('loginScreen').hidden=false;$('splashScreen').hidden=true;$('homeScreen').hidden=true;$('modal').hidden=true;}
  async function refreshActive(){if(!state.account)return;
    if(state.tab==='perfil')await loadProfileExtras();
    if(state.tab==='cards')await loadCards();
    if(state.tab==='inventario')await loadInventory();
    if(state.tab==='pet')await loadPet();
    if(state.tab==='loja')await loadShop();
    if(state.tab==='missoes')await loadMissions();
  }
  async function chooseTab(tab,focusSku=null){
    if(!labels[tab]||!state.account)return;
    const pages={perfil:$('profileContent'),cards:$('cardsScreen'),inventario:$('inventoryScreen'),pet:$('petScreen'),loja:$('shopScreen'),missoes:$('missionsScreen')};
    const oldPage=pages[state.tab];const nextPage=pages[tab];const changed=state.tab!==tab;
    const seq=++state.tabTransition;
    state.tab=tab;if(tab==='loja'&&focusSku)state.focusShop=focusSku;
    document.querySelectorAll('[data-tab]').forEach(b=>{b.classList.toggle('nav-active',b.dataset.tab===tab);b.setAttribute('aria-current',b.dataset.tab===tab?'page':'false');});
    if(changed&&oldPage&&!oldPage.hidden&&typeof oldPage.animate==='function'&&!matchMedia('(prefers-reduced-motion: reduce)').matches){
      await oldPage.animate([{opacity:1,transform:'translateX(0)'},{opacity:0,transform:'translateX(-7px)'}],{duration:105,easing:'ease-in'}).finished.catch(()=>{});
      if(seq!==state.tabTransition)return;
    }
    Object.entries(pages).forEach(([key,node])=>{node.hidden=key!==tab;node.classList.remove('page-enter');});
    if(changed){void nextPage.offsetWidth;nextPage.classList.add('page-enter');}
    try{await refreshActive();applyUiAssets();}catch(err){if(seq===state.tabTransition)toast('⚠ Não foi possível carregar esta aba. Tente novamente.');}
  }
  async function loadProfileExtras(){
    const [ach,game]=await Promise.all([API('/api/achievements'),API('/api/game/config')]);state.game=game;
    if(!$('badgesSection')){const b=h('section','profile-badges');b.id='badgesSection';$('profileContent').append(b);}
    const b=$('badgesSection');b.replaceChildren();
    const heading=h('div','badge-title');heading.append(h('strong','','🏅 Selos'),h('small','',`${ach.unlocked}/${ach.total} desbloqueados`));b.append(heading);
    const line=h('div','badge-strip');
    const visible=Math.max(8,state.badgesVisible||8);
    const shown=ach.items.slice(0,visible);
    for(const a of shown){const chip=h('button','badge-chip'+(a.locked?' locked':''),a.icon);chip.title=a.title+' — '+a.description+(a.available?'':' (integração com Discord futuramente)');chip.addEventListener('click',()=>toast(chip.title));line.append(chip);}
    b.append(line);
    if(ach.items.length>8){
      const remaining=Math.max(0,ach.items.length-shown.length);
      const expanded=shown.length>=ach.items.length;
      const toggle=button(expanded?'Mostrar menos ↑':`Mais (${remaining}) ↓`,()=>{state.badgesVisible=expanded?8:Math.min(ach.items.length,shown.length+8);loadProfileExtras().catch(e=>toast(e.message));},'badge-more');
      toggle.setAttribute('aria-expanded',String(expanded));
      b.append(toggle);
    }
    if(game.admin){const admin=button('⚙ Gestão do Recanto',()=>openAdmin(),'soft-action admin-open');admin.id='openAdmin';b.append(admin);}
    let gamesSection=$('gamesSection');if(!gamesSection){gamesSection=h('section','profile-games');gamesSection.id='gamesSection';b.after(gamesSection);}
    const prefs=await API('/api/games/preferences');gamesSection.replaceChildren();
    const head=h('div','badge-title');head.append(h('strong','','🎮 Jogos favoritos'),button('Editar',()=>editFavoriteGames(prefs),'game-edit'));gamesSection.append(head);
    const lineGames=h('div','game-icons');
    if(!prefs.selected.length)lineGames.append(h('p','', 'Escolha até cinco jogos para exibir no seu perfil.'));
    for(const g of prefs.selected){const chip=h('span','game-icon');chip.append(gameIcon(g));chip.title=g.name;chip.setAttribute('aria-label',g.name);lineGames.append(chip);}
    gamesSection.append(lineGames);applyUiAssets();
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
  function showCard(item,extra=''){
    const p=$('cardDetail');p.replaceChildren();const modal=$('cardModal');modal.classList.remove('detail-closing');state.detailClosing=false;
    const art=h('div','detail-art tier-'+item.rarity);if(item.image_url){const img=h('img');img.src=item.image_url;img.alt=item.name;art.append(img);}else art.textContent='✦';
    p.append(art,h('h2','',item.name),h('p','',tierLabels[item.rarity]||item.rarity));
    if(item.collection)p.append(h('p','detail-meta',`Coleção: ${item.collection}`));
    if(extra)p.append(h('p','detail-meta',extra));
    const actions=h('div','detail-actions');
    if(item.owned_id)actions.append(button(item.is_favorite?'★ Remover favorito':'☆ Favoritar card',async()=>{const result=await safeRun(()=>API('/api/cards/favorite',{owned_id:item.is_favorite?null:item.owned_id}),'Favorito atualizado!');if(result)closeCardDetail();}));
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
    const rerender=()=>paintCardGrid(items,ownedIds,tab,container);
    line.append(chooser('Raridade',filters.rarity,[['todos','Todas'],...Object.entries(tierLabels)],v=>{filters.rarity=v;rerender();}));
    const collections=[...new Set([...items.map(c=>c.collection||'Recanto Original'),'Celebridades','Personagens','Memes',filters.collection].filter(c=>c!=='todas'))].sort((a,b)=>a.localeCompare(b,'pt-BR'));
    if(filters.collection!=='todas'&&!collections.includes(filters.collection))filters.collection='todas';
    line.append(chooser('Coleção',filters.collection,[['todas','Todas as coleções'],...collections.map(v=>[v,v])],v=>{filters.collection=v;rerender();}));
    line.append(chooser('Ordem',filters.alphabetical,[['padrao','Recentes / Catálogo'],['az','Alfabético A–Z'],['za','Alfabético Z–A']],v=>{filters.alphabetical=v;rerender();}));
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
    if(!list.length)container.append(block('Nenhum card encontrado','Altere os filtros para encontrar outros cards.'));
    const grid=h('div','card-grid');
    for(const item of list){grid.append(cardTile(item,c=>{
      if(tab==='catalogo'){const owners=c.owners.map(o=>`${o.name}: ${o.count}`).join(' · ');showCard(c,`${c.minted}/${c.max_copies} cópias distribuídas. Donos: ${owners||'nenhum'}`);}
      else showCard(c,`Exemplar #${c.owned_id}`);
    }));}
    container.append(grid);
  }
  async function cardPane(tab){
    state.cardTab=tab;document.querySelectorAll('[data-card-tab]').forEach(el=>el.classList.toggle('mini-active',el.dataset.cardTab===tab));
    const p=$('cardsPane');p.replaceChildren();$('cardFilters').hidden=tab==='trocas';
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
      p.append(block('Todos os cards','Limites globais: Comum 3 • Raro 2 • Lendário 1 • Prismático 1.'));
      const featured=await API('/api/collections/featured');
      const banner=h('button','featured-collection-banner');banner.type='button';
      if(featured.image_url){banner.style.backgroundImage=`linear-gradient(90deg,rgba(19,24,88,.78),rgba(19,24,88,.12)),url("${featured.image_url.replaceAll('"','%22')}")`;}
      banner.append(h('small','','✦ COLEÇÃO EM DESTAQUE'),h('strong','',featured.name),h('span','','Ver os cards desta coleção →'));
      banner.onclick=()=>{state.cardFilters.collection=featured.name;cardPane('catalogo').catch(e=>toast(e.message));};
      p.append(banner);
      const results=h('div','filtered-cards');p.append(results);renderCardFilters(data.items,new Set(mine.items.map(c=>c.card_id)),'catalogo',results);
    }
    if(tab==='trocas'){
      const [community,trades,mine]=await Promise.all([API('/api/community'),API('/api/trades'),API('/api/cards')]);$('cardsCount').textContent='Negociações';
      const form=block('Propor uma troca','Escolha um membro e indique a carta sua e a carta dele. A troca só acontece quando a outra pessoa aceitar.');
      const members=community.members.filter(m=>m.cards.length);const mineCards=mine.items;
      if(members.length&&mineCards.length){
        const memberSelect=h('select','select-input');members.forEach(m=>{const o=h('option','',m.name);o.value=m.key;memberSelect.append(o);});
        const mySelect=h('select','select-input');mineCards.forEach(c=>{const o=h('option','',c.name+' — '+c.rarity+' #'+c.owned_id);o.value=c.owned_id;mySelect.append(o);});
        const theirs=h('select','select-input');const update=()=>{theirs.replaceChildren();const mem=members.find(m=>m.key===memberSelect.value);(mem?.cards||[]).forEach(c=>{const o=h('option','',c.name+' — '+c.rarity+' #'+c.owned_id);o.value=c.owned_id;theirs.append(o);});};memberSelect.addEventListener('change',update);update();
        form.append(h('label','','Membro'),memberSelect,h('label','','Sua carta'),mySelect,h('label','','Carta desejada'),theirs,button('Enviar proposta',()=>safeRun(()=>API('/api/trades',{to_user:memberSelect.value,offered_owned_id:Number(mySelect.value),wanted_owned_id:Number(theirs.value)}),'Proposta enviada!')));
      }else form.append(h('p','',mineCards.length?'Ainda não há outros jogadores com cartas cadastradas.':'Primeiro obtenha um card para oferecer.'));
      p.append(form,h('h3','section-heading','Minhas propostas'));
      if(!trades.items.length)p.append(block('Sem propostas','As negociações aparecerão aqui.'));
      for(const t of trades.items){const row=block(`${t.from_name} ↔ ${t.to_name}`,`${t.offered?.name||'Card'} ↔ ${t.wanted?.name||'Card'} · ${t.status}`);row.classList.add('trade-row');if(t.can_accept){row.append(button('Aceitar',()=>actTrade(t.id,'accept')));row.append(button('Recusar',()=>actTrade(t.id,'reject'),'soft-action'));}if(t.can_cancel)row.append(button('Cancelar proposta',()=>actTrade(t.id,'cancel'),'soft-action'));p.append(row);}
      const [offers,eco]=await Promise.all([API('/api/coin-offers'),API('/api/card-economy')]);
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
      p.append(bid,h('h3','section-heading','Ofertas de moedas'));
      if(!offers.items.length)p.append(block('Nenhuma oferta','As propostas em moedas aparecerão aqui.'));
      for(const offer of offers.items){const row=block(`${offer.buyer_name} → ${offer.seller_name}`,`${offer.card_name} • ${money(offer.amount)} moedas • ${offer.status}`);
        if(offer.can_accept){row.append(button('Aceitar oferta',()=>decideCoinOffer(offer.id,'accept')));row.append(button('Recusar',()=>decideCoinOffer(offer.id,'reject'),'soft-action'));}
        if(offer.can_cancel)row.append(button('Cancelar e receber reembolso',()=>decideCoinOffer(offer.id,'cancel'),'soft-action'));
        p.append(row);
      }
    }
  }
    async function decideCoinOffer(id,action){await safeRun(()=>API(`/api/coin-offers/${id}/decide`,{action}),'Oferta atualizada!');}
    async function actTrade(id,action){await safeRun(()=>API(`/api/trades/${id}/decide`,{action}),action==='accept'?'Troca concluída!':'Proposta atualizada.');}
  async function loadInventory(){
    const data=await API('/api/inventory');$('inventorySummary').textContent=`${data.packs.length} pacote(s)`;
    await inventoryPane(state.inventoryTab,data);
  }
  async function inventoryPane(tab,data=null){
    state.inventoryTab=tab;document.querySelectorAll('[data-inventory-tab]').forEach(b=>b.classList.toggle('mini-active',b.dataset.inventoryTab===tab));
    const d=data||await API('/api/inventory');const pane=$('inventoryPane');pane.replaceChildren();
    if(tab==='packs'){
      if(!d.packs.length)pane.append(block('Nenhum pacote fechado','Os pacotes comprados ficam aqui até você abrir.'));
      for(const pack of d.packs){const row=h('div','inventory-row');row.append(mediaCover(pack.image_url,pack.amount===5?'🎴':'🃏','Pacote '+pack.amount,'item-cover'));
        const info=h('div','inventory-meta');info.append(h('strong','',`Pacote de ${pack.amount} cards`),h('p','','Revelação em tela cheia'));
        row.append(info,button('Abrir',()=>openPack(pack.id)));pane.append(row);}
      pane.append(button('Ver pacotes na Loja →',()=>chooseTab('loja','pack3'),'soft-action'));
    }else{
      if(!d.treats.length)pane.append(block('Sem itens de pet','Compre petiscos exclusivamente na Loja.'));
      for(const t of d.treats){const row=h('div','inventory-row');row.append(mediaCover(null,t.emoji,t.name,'item-cover'));
        const info=h('div','inventory-meta');info.append(h('strong','',t.name),h('p','',`${t.quantity} disponível(is) • +${t.food} fome`));row.append(info);
        row.append(button('Presentear',()=>giftDialog(t),'soft-action'));pane.append(row);}
      pane.append(button('Comprar petiscos na Loja →',()=>chooseTab('loja','treat3'),'soft-action'));
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
  async function openPublicProfile(uid){
    try{const [d,items]=await Promise.all([API('/api/community/profiles/'+encodeURIComponent(uid)),API('/api/inventory')]);
      const pane=$('profilesPane');pane.replaceChildren();pane.append(button('← Voltar à busca',searchProfiles,'soft-action'));
      const title=h('div','public-identity');if(d.avatar_url){const img=h('img');img.src=d.avatar_url;img.alt=d.name;title.append(img);}else title.append(h('div','profile-thumb','◉'));
      const meta=h('div');meta.append(h('h3','',d.name),h('p','',d.cards+' cards na coleção'));title.append(meta);pane.append(title);
      if(d.favorite){const fav=block('★ Card favorito',d.favorite.name);fav.classList.add('public-section','public-favorite');const art=mediaCover(d.favorite.image_url,'★',d.favorite.name,'item-cover');art.addEventListener('click',()=>showCard(d.favorite));fav.prepend(art);pane.append(fav);}
      const badges=block('🏅 Selos desbloqueados');badges.classList.add('public-section');const line=h('div','public-badges');(d.badges||[]).forEach(b=>{const badge=h('span','badge-chip',b.icon);badge.title=b.title;line.append(badge);});
      if(!d.badges?.length)line.append(h('p','','Nenhum selo por enquanto.'));badges.append(line);pane.append(badges);
      const favorites=block('🎮 Jogos favoritos');favorites.classList.add('public-section');
      const gameIcons=h('div','game-icons');if(!d.favorite_games?.length)gameIcons.append(h('p','','Nenhum jogo selecionado.'));
      for(const game of d.favorite_games||[]){const chip=h('span','game-icon');chip.append(gameIcon(game));chip.title=game.name;gameIcons.append(chip);}
      favorites.append(gameIcons);pane.append(favorites);
      if(d.pet){const pet=block('🐾 Pet: '+d.pet.name,`Fome ${d.pet.food}/100 · Felicidade ${d.pet.happiness}/100 · ${d.pet.status}`);pet.prepend(petVisual(d.pet));pane.append(pet);
        if(d.pet.status==='ativo'){const actions=h('div','social-actions');actions.append(button('💗 Acariciar',()=>visitPet(uid,'pet')));
          const opts=items.treats||[];if(opts.length){const select=h('select','select-input');opts.forEach(t=>{const o=h('option','',t.name+' (+'+t.food+')');o.value=t.sku;select.append(o);});
            actions.append(select,button('🍪 Alimentar',()=>visitPet(uid,'feed',select.value),'soft-action'));}
          else actions.append(button('Comprar petiscos →',()=>{$('profilesModal').hidden=true;chooseTab('loja','treat3');},'soft-action'));
          pane.append(actions);}}
      else pane.append(block('Sem pet','Este membro ainda não adotou uma Pequena Lenda.'));
    }catch(err){toast(err.message);}
  }
  async function visitPet(owner,action,sku='biscoito'){
    const result=await safeRun(()=>API('/api/pets/visit/'+encodeURIComponent(owner),{action,treat_sku:sku}),d=>`+${d.visitor_coins} moedas para você e +${d.owner_coins} para o dono!`);
    if(result)await openPublicProfile(owner);
  }
  let modelViewerLoad=null;
  function load3DViewer(){
    if(window.customElements?.get('model-viewer'))return Promise.resolve();
    if(!modelViewerLoad){
      // Só carrega o motor 3D quando um pet possui modelo; não atrasa Perfil, Cards ou Loja.
      modelViewerLoad=import('https://cdn.jsdelivr.net/npm/@google/model-viewer@4.1.0/dist/model-viewer.min.js').catch(()=>null);
    }
    return modelViewerLoad;
  }
  function petVisual(species,large=false){
    const wrap=h('div','pet-visual'+(large?' pet-visual-large':''));
    const fallback=mediaCover(species.image_url,species.emoji||'🐾',species.name,'pet-fallback');wrap.append(fallback);
    if(species.model_url){
      load3DViewer();
      const view=h('model-viewer','pet-model');view.setAttribute('src',species.model_url);
      view.setAttribute('alt','Modelo 3D de '+species.name);view.setAttribute('camera-controls','');
      view.setAttribute('shadow-intensity','0.6');view.setAttribute('exposure','1.1');
      view.setAttribute('interaction-prompt','none');view.setAttribute('loading','lazy');
      if(species.idle_animation){view.setAttribute('animation-name',species.idle_animation);view.setAttribute('autoplay','');}
      view.addEventListener('load',()=>{view.classList.add('model-loaded');fallback.classList.add('fallback-hidden');});
      view.addEventListener('error',()=>{view.classList.remove('model-loaded');fallback.classList.remove('fallback-hidden');});
      view.addEventListener('finished',()=>{if(species.idle_animation){view.animationName=species.idle_animation;view.play();}});
      wrap.append(view);
    }
    return wrap;
  }
  function petReaction(action){
    const visual=$('petPane').querySelector('.pet-visual-large');if(!visual)return;
    visual.classList.remove('pet-react');void visual.offsetWidth;visual.classList.add('pet-react');
    const view=visual.querySelector('model-viewer.model-loaded');
    const pet=state.activePet;const name=action==='feed'?pet?.feed_animation:pet?.pet_animation;
    if(view&&name){view.animationName=name;view.play({repetitions:1});}
    const symbol=h('span','pet-spark',action==='feed'?'🍪':'💖');visual.append(symbol);setTimeout(()=>{symbol.remove();visual.classList.remove('pet-react');},850);
  }
  async function petCare(action,sku='biscoito'){
    const result=await safeRun(()=>API('/api/pets/care',{action,treat_sku:sku}),action==='feed'?'Pet alimentado!':'Seu pet recebeu carinho!');
    if(result)petReaction(action);
  }
  async function loadPet(){
    const data=await API('/api/pets');const pane=$('petPane');pane.replaceChildren();const pet=data.pet;
    state.activePet=pet;
    $('petStatus').textContent=pet?({ativo:'Em casa','vet':'No veterinário','morto':'Falecido','missao':'Em missão'}[pet.status]):'Sem pet';
    if(!pet||pet.status==='morto'){
      pane.append(block(pet?'Seu pet faleceu':'Escolha sua Pequena Lenda',pet?'O prazo de resgate terminou. Você pode adotar outra Pequena Lenda.':'Você pode adotar apenas uma Pequena Lenda por vez. Cuide dela diariamente.'));
      const grid=h('div','pet-grid');data.species.forEach(s=>{
        const row=block(s.name,'Pequena Lenda disponível para adoção');row.prepend(petVisual(s));
        row.append(button('Adotar',()=>safeRun(()=>API('/api/pets/adopt',{species_id:s.id}),'Pequena Lenda adotada!')));grid.append(row);
      });pane.append(grid);return;
    }
    const show=block(pet.name,pet.status==='vet'?'Sua Pequena Lenda precisa de resgate.':'Cuide de seu companheiro todos os dias.');
    show.prepend(petVisual(pet,true));pane.append(show);
    if(pet.status==='missao'){
      const expedition=data.expedition;
      pane.append(block('🗺️ Em missão',`Seu pet está em ${expedition?.name||'uma aventura'} e não pode receber carinho nem comida.`));
      const when=h('p','expedition-time',expedition?.ready?'Sua Pequena Lenda voltou!':'Volta em: '+countdown(expedition?.ends_at));pane.append(when);
      if(expedition?.ready)pane.append(button('Receber recompensas',async()=>{const result=await safeRun(()=>API('/api/pets/expedition/collect',{}),r=>`+${r.coins_gained} moedas${r.card?' e um card!':''}`);if(result?.card)showCard(result.card,'Card encontrado pela Pequena Lenda!');}));
      return;
    }
    if(pet.status==='vet'){
      pane.append(block('🏥 Veterinário',`Resgate por ${money(pet.rescue_cost)} moedas. Prazo: ${pet.vet_deadline?new Date(pet.vet_deadline).toLocaleString('pt-BR'):'—'}`));
      pane.append(button('Resgatar pet',()=>safeRun(()=>API('/api/pets/rescue',{}),'Companheiro resgatado!')));return;
    }
    pane.append(block('Estado do pet',`🍎 Fome: ${pet.food}/100 • 💕 Felicidade: ${pet.happiness}/100 • 🍪 Petiscos: ${data.treats}`));
    const actions=h('div','pet-actions');const inv=await API('/api/inventory');
    if(inv.treats.length){const choose=h('select','select-input');inv.treats.forEach(t=>{const opt=h('option','',t.name+' (+'+t.food+' fome) · '+t.quantity);opt.value=t.sku;choose.append(opt);});pane.append(choose);
      actions.append(button('🍪 Alimentar',()=>petCare('feed',choose.value)));}
    else actions.append(button('Petiscos na Loja →',()=>chooseTab('loja','treat3')));
    actions.append(button('💗 Acariciar',()=>petCare('pet'),'soft-action'));pane.append(actions);
    const ex=block('🗺️ Expedições da Pequena Lenda','Envie seu pet em uma aventura. Ele não poderá receber cuidados durante a missão e voltará com fome.');
    for(const option of data.expedition_options||[]){
      const row=h('div','expedition-choice');row.append(h('strong','',option.name),h('small','',`${option.minutes/60}h • -${option.food} fome • ${option.coins[0]}–${option.coins[1]} moedas • ${option.card_chance}% chance de card`));
      row.append(button('Enviar',()=>safeRun(()=>API('/api/pets/expedition/start',{mission:option.id}),'Sua Pequena Lenda iniciou a missão!'),'soft-action'));ex.append(row);
    }pane.append(ex);
  }
  function gameIcon(game){
    if(game.image_url){const img=h('img');img.src=game.image_url;img.alt='';img.loading='lazy';return img;}
    return h('span','',game.icon||'🎮');
  }
  async function loadUiAssets(){
    try{const result=await API('/api/assets');state.assets=result.items||[];applyUiAssets();}
    catch(_){/* assets opcionais; UI padrao continua funcionando */}
  }
  function applyUiAssets(){
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
  async function loadShop(){const [shop,me,daily]=await Promise.all([API('/api/shop'),API('/api/me'),API('/api/daily/status')]);$('shopWallet').textContent=`🪙 ${money(me.coins)}`;state.reset=daily.next_reset;$('dailyCoins').disabled=daily.coins_claimed;$('dailyCoins').textContent=daily.coins_claimed?'✓ Resgatado':`Resgatar ${money(daily.reward)} moedas`;updateCountdowns();const pane=$('shopPane');pane.replaceChildren();for(const s of shop.products){const box=block(s.name,s.kind==='cards'?`${s.amount} cartas aleatórias · guarda no Inventário`:`${s.amount} petisco(s) · +${s.food||15} fome por unidade`);box.id='shop-'+s.sku;box.classList.add('product-card');box.prepend(mediaCover(s.image_url,s.emoji||'🎁',s.name,'product-cover'));if(s.rates)box.append(h('p','rates',Object.entries(s.rates).map(([k,v])=>`${tierLabels[k]} ${v}%`).join(' · ')));box.append(button(`Comprar · 🪙 ${money(s.price)}`,()=>safeRun(()=>API('/api/shop/purchase',{sku:s.sku}),result=>result.pack_id?`Pacote guardado no Inventário!`:`${result.treats_gained} item(ns) adicionado(s) ao Inventário!`)));pane.append(box);}if(state.focusShop){const selected=$('shop-'+state.focusShop);state.focusShop=null;if(selected){selected.classList.add('shop-focus');selected.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'center'});setTimeout(()=>selected.classList.remove('shop-focus'),1800);}}}
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
        const box=block(m.title,`Progresso: ${m.progress}/${m.goal} · Recompensa: 🪙 ${m.reward}`);
        box.classList.add('mission-card');box.prepend(mediaCover(m.image_url,m.emoji||'🎯',m.title,'mission-cover'));
        const bar=h('div','mission-meter');const fill=h('div','mission-fill');fill.style.width=Math.min(100,100*m.progress/m.goal)+'%';bar.append(fill);box.append(bar);
        const action=button(m.claimed?'✓ Resgatada':m.progress>=m.goal?'Resgatar recompensa':'Em andamento',()=>safeRun(()=>API('/api/missions/'+m.code+'/claim',{}),`+${m.reward} moedas!`));
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
  function updateNotificationUI(message){const permitted=window.isSecureContext&&'Notification' in window;const active=state.notification&&permitted&&Notification.permission==='granted';$('notificationsToggle').classList.toggle('on',!!active);$('notificationsToggle').setAttribute('aria-checked',String(!!active));$('notificationsStatus').textContent=message||(!permitted?'Notificações exigem HTTPS e navegador compatível.':active?'Notificações Web Push ativadas.':'Ative para receber avisos de pets, cards e novidades.');}
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
    const form=new FormData();form.append('image',file);
    const response=await fetch('/api/admin/upload',{method:'POST',credentials:'same-origin',body:form});
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
  async function openAdmin(){try{const [opts,game]=await Promise.all([API('/api/admin/settings'),API('/api/game/config')]);const pane=$('adminContent');pane.replaceChildren();pane.append(h('p','', 'Apenas IDs do Discord autorizados podem administrar os catálogos e as configurações.'));
    const adminBox=block('Administradores por Discord ID','Somente IDs autorizados podem editar o Recanto. O ID principal é permanente.');
    try{const ids=await API('/api/admin/authorized-ids');adminBox.append(h('p','',`Administradores fixos: ${ids.permanent.join(', ')}`));
      if(ids.additional.length)adminBox.append(h('p','',`IDs extras: ${ids.additional.join(', ')}`));
      const [adminFieldRow,adminInput]=adminField('Discord ID do novo administrador','');adminBox.append(adminFieldRow);
      adminBox.append(button('Autorizar ID',()=>safeRun(()=>API('/api/admin/authorized-ids',{discord_id:adminInput.value,action:'add'}),'ID autorizado!')),
        button('Revogar ID adicional',()=>safeRun(()=>API('/api/admin/authorized-ids',{discord_id:adminInput.value,action:'remove'}),'Permissão revogada.')));
    }catch(err){adminBox.append(h('p','',err.message));}pane.append(adminBox);
    const card=block('Cadastrar card','Nome, raridade e imagem (opcional).');const [n,ni]=adminField('Nome','');const [url,ui]=adminField('URL HTTPS da imagem ou /uploads/...','');const [collectionRow,collectionInput]=adminField('Coleção do card','Recanto Original');card.append(n,collectionRow,url);const cardFile=h('input','text-input');cardFile.type='file';cardFile.accept='image/png,image/jpeg,image/webp';card.append(h('label','','Ou envie imagem PNG/JPG/WEBP (até 4 MB)'),cardFile);const rarity=h('select','select-input');['comum','raro','lendário','prismático'].forEach(t=>{const o=h('option','',tierLabels[t]);o.value=t;rarity.append(o);});card.append(rarity,button('Cadastrar card',()=>safeRun(async()=>{const image_url=cardFile.files.length?await uploadArtwork(cardFile.files[0]):ui.value;return API('/api/admin/cards',{name:ni.value,rarity:rarity.value,collection:collectionInput.value,image_url});},'Card cadastrado!')));pane.append(card);
    const moveCard=block('Alterar coleção de card existente','Informe o ID do card (visível no catálogo administrativo) e o nome da coleção.');
    const [cardIdLabel,cardIdInput]=adminField('ID do card','', 'number');
    const [newCollectionLabel,newCollectionInput]=adminField('Nova coleção','Recanto Original');
    const catalog=await API('/api/catalog');const idSelect=h('select','select-input');
    for(const c of catalog.items){const o=h('option','',`#${c.id} · ${c.name} (${c.collection||'Recanto Original'})`);o.value=String(c.id);idSelect.append(o);}
    moveCard.append(h('label','','Selecione um card'),idSelect,newCollectionLabel,
      button('Atualizar coleção',()=>safeRun(()=>API('/api/admin/cards/collection',{card_id:Number(idSelect.value),collection:newCollectionInput.value}),'Coleção atualizada!')));
    pane.append(moveCard);
    const featured=block('Coleção em destaque','Banner que aparece no Catálogo. Existem três coleções padrão: Celebridades, Personagens e Memes.');
    const [featuredNameLabel,featuredName]=adminField('Nome da coleção','Celebridades');
    const [featuredUrlLabel,featuredUrl]=adminField('URL da capa (opcional)','');
    const featuredFile=h('input','text-input');featuredFile.type='file';featuredFile.accept='image/png,image/jpeg,image/webp';
    featured.append(featuredNameLabel,featuredUrlLabel,h('label','','Ou escolha uma capa'),featuredFile,button('Salvar destaque',()=>safeRun(async()=>API('/api/admin/collections/featured',{name:featuredName.value,image_url:featuredFile.files.length?await uploadArtwork(featuredFile.files[0]):featuredUrl.value}),'Coleção em destaque atualizada!')));pane.append(featured);
    const pet=block('Cadastrar Pequena Lenda','Aceita imagem, modelo 3D GLB/GLTF e nomes de animações do arquivo.');
    const [pn,pni]=adminField('Nome da Pequena Lenda','');const [pe,pei]=adminField('Emoji para fallback','🐾');const [pu,pui]=adminField('Imagem de capa (HTTPS ou /uploads/...)','');
    const petFile=h('input','text-input');petFile.type='file';petFile.accept='image/png,image/jpeg,image/webp';
    const [modelurl,mui]=adminField('URL de modelo .glb ou .gltf (opcional)','');
    const modelFile=h('input','text-input');modelFile.type='file';modelFile.multiple=true;modelFile.accept='.glb,.gltf,.bin,.png,.jpg,.jpeg,.webp';
    const animKeys=[['idle_animation','Parado / idle'],['pet_animation','Carinho'],['feed_animation','Alimentação'],['vet_animation','Veterinário']];
    const animInputs={};const fields=[];
    for(const [key,label] of animKeys){const [container,inp]=adminField('Nome exato da animação: '+label,'');fields.push(container);animInputs[key]=inp;}
    pet.append(pn,pe,pu,h('label','','Ou envie uma capa PNG/JPG/WEBP (até 4 MB)'),petFile,modelurl,
      h('label','','Ou selecione .glb; para .gltf, selecione também .bin e texturas (até 40 MB no total)'),modelFile,...fields,
      button('Cadastrar Pequena Lenda',()=>safeRun(async()=>{
        const image_url=petFile.files.length?await uploadArtwork(petFile.files[0]):pui.value;
        const model_url=modelFile.files.length?await uploadModel(modelFile.files):mui.value;
        const animations=Object.fromEntries(Object.entries(animInputs).map(([key,inp])=>[key,inp.value]));
        return API('/api/admin/pets',{name:pni.value,emoji:pei.value,image_url,model_url,...animations});
      },'Pequena Lenda cadastrada!')));pane.append(pet);
    const covers=block('Capas da Loja e Missões','As capas são opcionais. Elas aparecem nos produtos e nas missões, sem alterar as regras.');
    const source=h('select','select-input');[['shop','Produtos da Loja'],['mission','Missões diárias']].forEach(([value,label])=>{const o=h('option','',label);o.value=value;source.append(o);});
    const target=h('select','select-input');const fillTargets=()=>{
      target.replaceChildren();(source.value==='shop'?[['pack3','Pacote 3 cards'],['pack5','Pacote 5 cards'],['treat3','Biscoitos'],['fruit','Frutinha'],['feast','Banquete']]:[['daily_card','Card diário'],['daily_coins','Moedas diárias'],['trade','Troca'],['pet','Carinho'],['feed','Alimentar'],['adopt','Adoção'],['pack','Pacote']]).forEach(([value,label])=>{const o=h('option','',label);o.value=value;target.append(o);});
    };source.addEventListener('change',fillTargets);fillTargets();
    const [coverRow,coverUrl]=adminField('Capa (HTTPS ou /uploads/...); vazio remove','');const coverFile=h('input','text-input');coverFile.type='file';coverFile.accept='image/png,image/jpeg,image/webp';
    covers.append(source,target,coverRow,h('label','','Ou selecione imagem no PC'),coverFile,button('Salvar capa',()=>safeRun(async()=>{
      const image_url=coverFile.files.length?await uploadArtwork(coverFile.files[0]):coverUrl.value;
      return API('/api/admin/covers',{kind:source.value,key:target.value,image_url});
    },'Capa atualizada!')));pane.append(covers);
    const ach=block('Criar selo','A conquista pode ser automática ou depender de futura integração de voz.');const [an,ani]=adminField('Título','');const [ad,adi]=adminField('Descrição','');const [ai,aii]=adminField('Emoji','🏅');const [at,ati]=adminField('Meta numérica','1','number');const type=h('select','select-input');for(const [code,label] of Object.entries({trade:'Trocas',card:'Cards recebidos',adopt:'Pets adotados',pet:'Carinhos',feed:'Alimentações',mission:'Missões resgatadas',voice_minutes:'Minutos em voz (integração futura)'})){const o=h('option','',label);o.value=code;type.append(o);}ach.append(an,ad,ai,at,type,button('Criar selo',()=>safeRun(()=>API('/api/admin/achievements',{title:ani.value,description:adi.value,icon:aii.value,event:type.value,target:Number(ati.value)}),'Selo criado!')));pane.append(ach);
    // Gerenciador de assets: aplica a arte a elementos sem alterar seus cliques ou regras.
    const assetPane=block('🖼️ Central de Assets','Personalize jogos, logos, fundos, icones do menu e elementos da interface. Imagens PNG/JPG/WEBP ate 4 MB; em servidor online, use URL HTTPS persistente.');
    const existingAssets=(await API('/api/assets')).items;
    const baseSlots=[
      ['logo-login','#loginScreen .brand-logo','image','Logo na tela de login'],
      ['logo-loading','#splashScreen .splash-logo','image','Logo na tela de carregamento'],
      ['fundo-login','#loginScreen','background','Fundo do login'],
      ['fundo-app','#homeScreen','background','Fundo geral do aplicativo'],
      ['barra-inferior','.bottom-nav','background','Barra inferior'],
      ['botao-config','#settings','icon','Icone de configuracoes'],
      ['botao-perfis','#searchUsers','icon','Icone da busca de perfis'],
      ['nav-perfil','[data-tab="perfil"] .nav-circle','icon','Icone Perfil'],
      ['nav-cards','[data-tab="cards"] .nav-circle','icon','Icone Cards'],
      ['nav-inventario','[data-tab="inventario"] .nav-circle','icon','Icone Inventario'],
      ['nav-pet','[data-tab="pet"] .nav-circle','icon','Icone Pet'],
      ['nav-loja','[data-tab="loja"] .nav-circle','icon','Icone Loja'],
      ['nav-missoes','[data-tab="missoes"] .nav-circle','icon','Icone Missoes'],
      ['moedas-perfil','.stats-list .stat:nth-child(1) .stat-icon','icon','Icone de moedas'],
      ['cards-perfil','.stats-list .stat:nth-child(2) .stat-icon','icon','Icone de cards'],
      ['petiscos-perfil','.stats-list .stat:nth-child(3) .stat-icon','icon','Icone de petiscos'],
      ['card-diario','#dailyCardIcon','background','Fundo do card diario'],
      ['capa-pack-revelacao','.flip-back','background','Verso do card na abertura']
    ];
    const allSlots=[...baseSlots];
    const gamesData=await API('/api/games/preferences');
    for(const g of gamesData.catalog)allSlots.push([`game:${g.id}`,'','icon',`Jogo · ${g.name}`]);
    const chooseSlot=h('select','select-input');
    for(const [key,sel,mode,name] of allSlots){const o=h('option','',name);o.value=key;chooseSlot.append(o);}
    const [customKeyRow,customKey]=adminField('Ou crie uma chave personalizada (opcional)','');
    const [customSelectorRow,customSelector]=adminField('Seletor CSS do elemento personalizado (opcional)','');
    const modeSelect=h('select','select-input');for(const [key,label] of [['background','Imagem de fundo'],['icon','Icone sobre o elemento'],['image','Imagem (tag img)']]){const op=h('option','',label);op.value=key;modeSelect.append(op);}
    const [assetUrlRow,assetUrl]=adminField('URL HTTPS da imagem ou /uploads/...','');
    const assetFile=h('input','text-input');assetFile.type='file';assetFile.accept='image/png,image/jpeg,image/webp';
    const assetPreview=h('div','admin-asset-preview');
    const preview=()=>{const entry=existingAssets.find(a=>a.key===chooseSlot.value);assetPreview.replaceChildren();if(entry?.image_url){const pic=h('img');pic.src=entry.image_url;pic.alt='Arte atual';assetPreview.append(pic,h('span','',entry.image_url));}else assetPreview.append(h('span','', 'Nenhuma imagem configurada para este elemento.'));};
    chooseSlot.onchange=()=>{const sel=allSlots.find(row=>row[0]===chooseSlot.value);modeSelect.value=sel?.[2]||'background';preview();};chooseSlot.onchange();
    const saveAsset=async(remove=false)=>{
      const slot=allSlots.find(row=>row[0]===chooseSlot.value);
      const key=customKey.value.trim()||chooseSlot.value;
      const selector=customKey.value.trim()?customSelector.value.trim():(slot?.[1]||'');
      const mode=customKey.value.trim()?modeSelect.value:(slot?.[2]||'icon');
      const image_url=remove?'':(assetFile.files.length?await uploadArtwork(assetFile.files[0]):assetUrl.value.trim());
      const result=await API('/api/admin/assets',{key,selector,mode,image_url});
      if(result.ok){assetFile.value='';assetUrl.value='';const all=await API('/api/assets');state.assets=all.items;applyUiAssets();}
      return result;
    };
    assetPane.append(h('label','','Elemento a personalizar'),chooseSlot,customKeyRow,customSelectorRow,
      h('label','','Formato do asset personalizado'),modeSelect,assetUrlRow,
      h('label','','Ou envie um arquivo de imagem'),assetFile,assetPreview,
      button('Salvar imagem',()=>safeRun(()=>saveAsset(false),'Asset salvo!')),
      button('Remover imagem do elemento',()=>safeRun(()=>saveAsset(true),'Asset removido.'),'soft-action'));
    assetPane.append(h('p','asset-help','Para outros elementos, use uma chave personalizada e um seletor CSS, por exemplo #shopWallet ou .product-cover. O modo fundo preserva os cliques e textos. Para jogos, escolha o nome da lista.'));
    pane.append(assetPane);
    const missionData=await API('/api/admin/missions');
    const missionBlock=block('Missões do Recanto','Crie e edite missões únicas, diárias ou semanais. As semanais entram na semana atual; após a próxima segunda-feira, cadastre/reative as missões da nova semana.');
    const existing=h('select','select-input');
    existing.append(Object.assign(h('option','','Nova missão'),{value:''}));
    for(const row of missionData.items){const o=h('option','',row.title+' ['+row.code+']');o.value=row.code;existing.append(o);}
    const mFields={};
    for(const [key,label,value] of [['code','Código único (ex: voz_30)',''],['title','Título',''],['goal','Meta numérica','1'],['reward','Recompensa em moedas','10'],['emoji','Emoji','🎯'],['image_url','Capa URL HTTPS (opcional)','']]){
      const [wrap,inp]=adminField(label,value,(['goal','reward'].includes(key)?'number':'text'));
      mFields[key]=inp;missionBlock.append(wrap);
    }
    const missionType=h('select','select-input');for(const [v,t] of [['unica','Única'],['diaria','Diária'],['semanal','Semanal']]){const opt=h('option','',t);opt.value=v;missionType.append(opt);}
    const missionEvent=h('select','select-input');for(const [v,t] of [['adopt','Adotar pet'],['trade','Trocar card'],['daily_card','Resgatar card'],['daily_coins','Resgatar moedas'],['pet','Acariciar pet'],['feed','Alimentar pet'],['pack','Abrir pack'],['voice_minutes','Minutos em canal de voz'],['message_count','Mensagens de texto']]){const opt=h('option','',t);opt.value=v;missionEvent.append(opt);}
    const enabled=h('input');enabled.type='checkbox';enabled.checked=true;
    existing.onchange=()=>{const row=missionData.items.find(m=>m.code===existing.value);if(!row)return;
      for(const key of Object.keys(mFields))mFields[key].value=row[key]??'';
      missionType.value=row.kind;missionEvent.value=row.event;enabled.checked=row.enabled;};
    missionBlock.prepend(h('label','','Editar missão cadastrada ou criar nova'),existing);
    const imageUpload=h('input','text-input');imageUpload.type='file';imageUpload.accept='image/png,image/jpeg,image/webp';
    missionBlock.append(h('label','','Tipo de missão'),missionType,h('label','','Ação que conta progresso'),missionEvent,h('label','','Ou envie a imagem da missão'),imageUpload,h('label','','Missão ativa'),enabled,
      button('Salvar missão',async()=>{const payload=Object.fromEntries(Object.entries(mFields).map(([k,v])=>[k,v.value]));
        payload.goal=Number(payload.goal);payload.reward=Number(payload.reward);payload.kind=missionType.value;payload.event=missionEvent.value;payload.enabled=enabled.checked;
        const result=await safeRun(async()=>{if(imageUpload.files.length)payload.image_url=await uploadArtwork(imageUpload.files[0]);return API('/api/admin/missions',payload);},'Missão cadastrada/atualizada!');if(result)await openAdmin();}));
    pane.append(missionBlock);
    const integrations=block('Integrações','Missões de voz e mensagens requerem RECANTO_BOT_SECRET no Render e um pequeno envio de eventos pelo seu bot existente. Notificações exigem chaves VAPID e o job agendado; consulte o guia no ZIP.');
    pane.append(integrations);
    const settings=block('Valores configuráveis','Recompensas, preços e prazos.');for(const [key,value] of Object.entries(opts.settings)){const [fld,inp]=adminField(key,value,'number');settings.append(fld,button('Salvar '+key,()=>safeRun(()=>API('/api/admin/settings',{key,value:Number(inp.value)}),'Valor salvo!'),'soft-action'));}pane.append(settings);
    if(game.local_development){const dev=block('Ferramentas de teste local','Acelere os testes sem esperar dias. Apenas administradores Discord.');
      dev.append(button('Adicionar 5.000 moedas para minha conta',()=>safeRun(()=>API('/api/dev/grant-coins',{amount:5000}),'5.000 moedas adicionadas!')));dev.append(button('Reiniciar resgates diários',()=>safeRun(()=>API('/api/dev/reset-daily',{}),'Resgates reiniciados!')));dev.append(button('Simular abandono → veterinário',()=>safeRun(()=>API('/api/dev/advance-pet',{stage:'vet'}),'Pet no veterinário!'),'soft-action'));dev.append(button('Simular prazo vencido → morte',()=>safeRun(()=>API('/api/dev/advance-pet',{stage:'death'}),'Prazo encerrado.','soft-action')));pane.append(dev);
      const reset=block('Apagar banco para testes','Operação irreversível. Disponível apenas ao administrador autenticado no PC; as contas Discord não são removidas.');
      const scope=h('select','select-input');[['progress','Limpar progresso: cartas, moedas, pets, trocas, selos e missões'],['factory','Reset completo: progresso, catálogo, pets, capas, selos e configurações']].forEach(([v,t])=>{const opt=h('option','',t);opt.value=v;scope.append(opt);});
      const [field,confirmation]=adminField('Digite LIMPAR TUDO para confirmar','');
      const resetButton=button('Apagar dados de teste',async()=>{
        if(confirmation.value!=='LIMPAR TUDO'){toast('Digite LIMPAR TUDO para confirmar.');return;}
        const result=await safeRun(()=>API('/api/dev/reset-all',{scope:scope.value,confirmation:confirmation.value}),'Dados de teste reiniciados!');
        if(result){confirmation.value='';await openAdmin();}
      },'danger-action');resetButton.disabled=true;confirmation.addEventListener('input',()=>resetButton.disabled=confirmation.value!=='LIMPAR TUDO');
      reset.append(scope,field,resetButton);pane.append(reset);
    }
    const groups=['Geral','Economia','Cards','Loja','Pets','Missões','Selos','Assets','Usuários','Integrações'];
    const classify=(name)=>{
      const x=name.toLowerCase();
      if(x.includes('valores configuráveis'))return 'Economia';
      if(x.includes('cadastrar card')||x.includes('coleção'))return 'Cards';
      if(x.includes('capa'))return 'Loja';
      if(x.includes('pequena lenda'))return 'Pets';
      if(x.includes('missões do recanto'))return 'Missões';
      if(x.includes('selo'))return 'Selos';
      if(x.includes('assets'))return 'Assets';
      if(x.includes('administrador')||x.includes('ids autorizados'))return 'Usuários';
      if(x.includes('integrações'))return 'Integrações';
      return 'Geral';
    };
    const boxes=[...pane.querySelectorAll(':scope > .game-box')];
    for(const box of boxes)box.dataset.adminGroup=classify(box.querySelector('h3')?.textContent||'');
    const nav=h('div','admin-tabs');
    const showGroup=group=>{for(const box of boxes)box.hidden=box.dataset.adminGroup!==group;
      for(const btn of nav.querySelectorAll('button'))btn.classList.toggle('selected',btn.dataset.group===group);};
    for(const group of groups){const btn=button(group,()=>showGroup(group),'admin-tab');btn.dataset.group=group;nav.append(btn);}
    pane.prepend(nav);showGroup('Geral');
    $('adminModal').hidden=false;}catch(err){toast('⚠ '+err.message);}}
  $('login').onclick=login;$('settings').onclick=()=>{$('modal').hidden=false;loadNotification();};$('closeSettings').onclick=()=>{$('modal').hidden=true;};$('logout').onclick=async()=>{try{await API('/api/auth/logout',{});showLogin();}catch(err){toast(err.message);}};
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

  $('dailyCoins').onclick=()=>safeRun(()=>API('/api/daily/coins',{}),'Moedas resgatadas!');
  $('dailyCard').onclick=async()=>{const result=await safeRun(()=>API('/api/daily/card',{}),'Card diário recebido!');if(result?.card)showCard(result.card,`+${result.card.bonus_coins??result.card_bonus??state.game?.rules?.['card_bonus_'+result.card.rarity]??1} moedas pelo card!`);};
  document.querySelectorAll('[data-tab]').forEach(btn=>btn.addEventListener('click',()=>chooseTab(btn.dataset.tab)));
  document.querySelectorAll('[data-card-tab]').forEach(btn=>btn.addEventListener('click',()=>cardPane(btn.dataset.cardTab).catch(err=>toast(err.message))));
  $('closeCardDetail').onclick=closeCardDetail;$('closeAdmin').onclick=()=>{$('adminModal').hidden=true;};
  for(const id of ['modal','cardModal','adminModal','profilesModal'])$(id).addEventListener('click',e=>{if(e.target===$(id)){if(id==='cardModal')closeCardDetail();else $(id).hidden=true;}});
  window.addEventListener('keydown',e=>{if(e.key==='Escape')for(const id of ['modal','adminModal','profilesModal'])$(id).hidden=true;closeCardDetail();});
  
  async function showWelcome(me){
    $('loginScreen').hidden=true;$('homeScreen').hidden=true;
    const splash=$('splashScreen');splash.hidden=false;splash.classList.remove('splash-fade');
    const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
    await new Promise(resolve=>setTimeout(resolve,reduced?100:1050));
    renderProfile(me);prefetchTabs();await loadUiAssets();await chooseTab('perfil');
    if(!reduced){splash.classList.add('splash-fade');await new Promise(resolve=>setTimeout(resolve,550));}
    splash.hidden=true;splash.classList.remove('splash-fade');
  }
  loadTheme();
  updateInstallButton();
  window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();state.installEvent=e;updateInstallButton();});
  window.addEventListener('appinstalled',()=>{state.installEvent=null;updateInstallButton();toast('Recanto instalado com sucesso!');});
  setInterval(updateCountdowns,1000);
  (async()=>{
    const params=new URLSearchParams(location.search);
    if(params.has('login_error')){report('Não foi possível concluir o login Discord: '+params.get('login_error'));history.replaceState(null,'',location.pathname);}
    try{
      const results=await Promise.allSettled([retryBootstrap('/api/config'),retryBootstrap('/api/me')]);
      if(results[0].status==='fulfilled')state.config=results[0].value;
      const me=results[1].status==='fulfilled'?results[1].value:null;
      if(me?.authenticated){report('');await showWelcome(me);return;}
      if(results[1].status==='rejected')report('Conexão temporariamente indisponível. Reabra o Recanto ou tente novamente.');
      else if(results[0].status==='rejected')report('Não foi possível consultar a configuração do servidor.');
    }catch(err){if(!state.account)report('Não foi possível carregar o Recanto. Tente novamente.');}
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
        window.addEventListener('focus',check);
        document.addEventListener('visibilitychange',()=>{if(!document.hidden)check();});
        setInterval(()=>{if(!document.hidden)check();},30*60*1000);
        check();
      }catch(_){/* O Recanto também funciona sem Service Worker */}
    });
  }
})();
