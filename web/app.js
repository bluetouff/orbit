'use strict';
const C=OrbitCore,$=id=>document.getElementById(id),t=(key,values)=>OrbitI18n.t(key,values);
const ASSET_BASE=new URL('.',document.currentScript.src);
const FAV_KEY='orbit.favs.v1',SETTINGS_KEY='orbit.settings.v2';
function readStorage(key,fallback){try{return JSON.parse(localStorage.getItem(key))??fallback;}catch{return fallback;}}
const saved=readStorage(FAV_KEY,[]);
const state={snapshot:null,selected:new Set((Array.isArray(saved)?saved:[]).filter(id=>typeof id==='string'&&C.ID.test(id)).slice(0,50)),
  settings:C.settings(readStorage(SETTINGS_KEY,null)),view:'fav',catalog:'all',onboarding:false,picking:false,analysis:null,loading:true,error:false,activeCoin:null,assetTab:'signals'};
state.onboarding=state.selected.size===0||new URL(location.href).searchParams.get('view')==='home';
let busy=false,refreshTimer,toastTimer,manageLimit=80,pendingImport=null,rects=[],canvasFrame=0;
const logos=new Map(),canvas=$('map'),ctx=canvas.getContext('2d');
const locale=()=>OrbitI18n.language==='fr'?'fr-FR':'en-US';
const decimal=(v,digits=2)=>new Intl.NumberFormat(locale(),{minimumFractionDigits:digits,maximumFractionDigits:digits}).format(v);
const pct=v=>v==null?t('Unavailable'):(v>=0?'+':'')+decimal(v,Math.abs(v)>=10?1:2)+'%';
const price=(v,token=false)=>v==null?t('Unavailable'):new Intl.NumberFormat(locale(),{style:'currency',currency:'USD',minimumFractionDigits:token&&v>=1?2:0,maximumFractionDigits:v<1?8:token||v<100?2:0}).format(v);
const big=v=>v==null?t('Unavailable'):new Intl.NumberFormat(locale(),{notation:'compact',maximumFractionDigits:2,style:'currency',currency:'USD'}).format(v);
const date=v=>C.time(v)===null?t('Unknown'):new Date(v).toLocaleString(OrbitI18n.language==='fr'?'fr-FR':'en-GB',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'UTC'})+' UTC';
const age=ms=>ms==null||ms<0?t('Unknown'):ms<60000?t('Just now'):ms<3600000?t('{n}m ago',{n:Math.floor(ms/60000)}):ms<86400000?t('{n}h ago',{n:Math.floor(ms/3600000)}):t('{n}d ago',{n:Math.floor(ms/86400000)});
const periods={'1h':'1-hour','24h':'24-hour','7d':'7-day','30d':'30-day'};
function el(tag,className,content,translate=true){const n=document.createElement(tag);if(className)n.className=className;if(content!==undefined)n.textContent=translate?t(content):content;return n;}
function icon(name){const n=el('img','icon');n.src=new URL('icons/'+name+'.svg',ASSET_BASE).href;n.alt='';return n;}
function coinImage(c){if(!c.has_logo)return el('span','coin-logo');const n=el('img','coin-logo');n.src='./logos/'+encodeURIComponent(c.id)+'.png';n.alt='';n.loading='lazy';n.addEventListener('error',()=>{n.replaceWith(el('span','coin-logo'));},{once:true});return n;}
function button(label,className,handler){const n=el('button',className,label);n.type='button';if(handler)n.addEventListener('click',handler);return n;}
function toast(message){$('toast').textContent=t(message);$('toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.remove('show'),3500);}
function save(){try{localStorage.setItem(FAV_KEY,JSON.stringify([...state.selected]));localStorage.setItem(SETTINGS_KEY,JSON.stringify(state.settings));}catch{toast('Browser storage is unavailable. Export your watchlist to keep it.');}}
function coins(){return state.snapshot?.coins||[];}
function xstockCoins(){return coins().filter(C.isXstock);}
function byId(id){return coins().find(c=>c.id===id);}
function sourceCoins(){return state.view==='market'?coins().filter(c=>!C.isXstock(c)).slice(0,100):state.view==='xstocks'?xstockCoins().slice(0,50):[...state.selected].map(byId).filter(Boolean);}
function mapCoins(){return state.onboarding&&!state.selected.size?['bitcoin','ethereum','solana','chainlink','uniswap','aave'].map(byId).filter(Boolean):sourceCoins();}
function eventsFor(c){return state.analysis?.byId.get(c.id);}
function toggleCoin(id){
  if(!C.ID.test(id))return;
  if(state.selected.has(id))state.selected.delete(id);
  else if(state.selected.size<50)state.selected.add(id);
  else {toast('Your watchlist is limited to 50 assets.');return;}
  save();render();renderChoosers();
  if(state.activeCoin===id)renderAsset();
}
function changeSetting(key,value){state.settings=C.settings({...state.settings,[key]:value});save();render();}
function render(){
  state.analysis=C.analyze(state.snapshot,state.settings.tf);
  $('shell').classList.toggle('onboarding',state.onboarding);
  $('shell').classList.toggle('home',state.onboarding&&!state.picking);
  $('welcome').hidden=!state.onboarding||!state.picking;
  $('homeIntro').hidden=!state.onboarding||state.picking;
  $('homeFaq').hidden=!state.onboarding||state.picking;
  $('signalsPanel').hidden=state.onboarding||!state.settings.signalsOpen;
  $('workspace').classList.toggle('with-signals',!$('signalsPanel').hidden);
  $('workspace').classList.toggle('with-welcome',state.onboarding&&state.picking);
  $('workspace').classList.toggle('with-home',state.onboarding&&!state.picking);
  $('buildWatchlist').firstChild.textContent=t(state.selected.size?'Open my watchlist':'Build my watchlist')+' ';
  $('watchCount').textContent=state.selected.size;
  document.querySelectorAll('[data-tf]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tf===state.settings.tf)));
  document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===state.view)));
  $('filterSelect').value=state.settings.filter;$('sizeSelect').value=state.settings.metric;
  $('signalsToggle').setAttribute('aria-expanded',String(state.settings.signalsOpen));
  $('signalsToggleLabel').textContent=t(state.view==='xstocks'?'Details':'Signals');
  $('signalCount').hidden=state.view==='xstocks';
  $('closeSignals').title=t(state.view==='xstocks'?'Hide details':'Hide signals');
  $('closeSignals').setAttribute('aria-label',$('closeSignals').title);
  $('mapTitle').textContent=t(state.onboarding?(state.selected.size?'Your selection':'Market preview'):state.view==='xstocks'?'xStocks':state.view==='market'?'Crypto market':'Watchlist');
  const list=mapCoins(),returns=list.filter(c=>C.quoteState(state.snapshot,c).usable).map(c=>c[C.TF[state.settings.tf]]).filter(Number.isFinite);
  const xcount=list.filter(C.isXstock).length;
  $('mapScope').hidden=!xcount&&state.view!=='xstocks';
  const older=list.filter(c=>C.isXstock(c)&&C.quoteState(state.snapshot,c).age>600000).length;
  $('mapScope').textContent=t('Delayed token quotes')+(older?' · '+t('{n} quotes older than 10 min',{n:older}):'');
  for(const option of $('filterSelect').options)option.disabled=state.view==='xstocks'&&['anomaly','divergence'].includes(option.value);
  const missing=state.view==='fav'?state.selected.size-sourceCoins().length:0;
  $('mapSummary').textContent=t(list.length===1?'{n} asset':'{n} assets',{n:list.length})+(missing?t(' · {n} unavailable',{n:missing}):'')+(returns.length?t(' · mean {value}',{value:pct(returns.reduce((a,b)=>a+b,0)/returns.length)}):'');
  if(state.view==='xstocks')$('mapSummary').textContent=t('Top {n} · {total} xStocks in the catalog',{n:list.length,total:xstockCoins().length});
  $('periodCaption').textContent=t('{period} performance · USD',{period:t(periods[state.settings.tf])});
  renderSources();renderMarketContext();renderSignals();drawMap();renderSelection();
}
function renderSelection(){
  $('welcomeCount').textContent=t('{n} of 50 selected',{n:state.selected.size});$('manageCount').textContent=t('{n} / 50 selected',{n:state.selected.size});
  $('finishWelcome').disabled=state.selected.size===0;
}
function renderSources(){
  const list=mapCoins(),hasXstocks=list.some(C.isXstock),hasCrypto=list.some(c=>!C.isXstock(c));
  const crypto=C.sourceState(state.snapshot,'coingecko_markets'),xstocks=C.sourceState(state.snapshot,'coingecko_xstocks');
  const source=state.view==='xstocks'||(hasXstocks&&!hasCrypto)?xstocks:crypto;
  $('marketAge').textContent=source.usable?t('Received {age}',{age:age(source.age)}):t('Market data: {state} · {age}',{state:t(source.kind),age:age(source.age)});
  $('marketAge').classList.toggle('warning',!source.usable);
  $('marketAge').title=t('Snapshot collected {date}',{date:date(source.stamp)});
  if(hasXstocks&&hasCrypto&&!xstocks.usable){$('marketAge').textContent=t('xStocks data: {state}',{state:t(xstocks.kind)});$('marketAge').classList.add('warning');$('marketAge').title=t('Collected {date}',{date:date(xstocks.stamp)});}
  $('connectionStatus').textContent=t(state.error?'Connection interrupted · retrying':state.loading?'Connecting':'Same-origin data');
  const summary=$('marketSummary');summary.replaceChildren();
  const global=C.sourceState(state.snapshot,'coingecko_global').usable?state.snapshot?.global:null;
  if(global?.cap!=null)summary.append(el('span','',t('Crypto {value}',{value:big(global.cap)})));
  if(global?.btc!=null)summary.append(el('span','',t('BTC dominance {value}%',{value:decimal(global.btc,1)})));
  const box=$('sourceStatus');box.replaceChildren();
  for(const [key,name] of [['coingecko_markets','CoinGecko · Crypto'],['coingecko_xstocks','CoinGecko · xStocks'],['lunarcrush','LunarCrush'],['fred','FRED']]){
    const s=C.sourceState(state.snapshot,key),row=el('div','source-row'),heading=el('div','source-heading');
    heading.append(el('b','',name),el('span','source-state '+s.kind,s.kind==='current'?'Collection current':s.kind));
    row.append(heading,el('span','source-time',s.stamp?t('Collected {age}',{age:age(s.age)}):'Collection time unavailable'));
    row.title=t('Collected {date}',{date:date(s.stamp)});
    if(key==='coingecko_xstocks')row.append(el('span','source-observation',t('Collection every ~{n} min · quotes may be delayed',{n:Math.ceil((state.snapshot?.status?.[key]?.ttl||60)/60)})));
    const retry=state.snapshot?.status?.[key]?.retry_at;
    if(!s.usable&&retry)row.append(el('span','source-observation',t('Provider pause · retry after {date}',{date:date(retry)})));
    if(key==='fred'){
      const m=state.snapshot?.macro;
      for(const [k,label] of [['us10y','10Y'],['usd','Broad USD']])if(m?.[k])row.append(el('span','source-observation',t(label)+' '+m[k].value+(k==='us10y'?'%':'')+' · '+t('observed')+' '+(m[k].date||t('unknown'))));
    }
    if(key==='lunarcrush'&&s.usable){const n=coins().filter(c=>c.galaxy_score!==null).length;row.append(el('span','source-observation',t('{n} assets covered · context only',{n})));}
    box.append(row);
  }
}
function renderMarketContext(){
  const box=$('marketContext'),m=state.analysis.market;box.replaceChildren();
  if(state.view==='xstocks'){
    box.append(el('h3','context-title','Stocks & ETFs, tokenized'),el('p','xstock-copy','Follow token prices and add xStocks to the same watchlist as your crypto.'));
    const metrics=el('div','context-metrics');metrics.append(metric('In the feed',String(xstockCoins().length)),metric('Currency','USD'));box.append(metrics);
    box.append(el('p','context-note','Token capitalization is not the value of the underlying company.'));
    return;
  }
  const heading=el('div','context-heading');heading.append(el('h3','','Crypto context'),el('span','',state.settings.tf.toUpperCase()));box.append(heading);
  if(!m.available){box.append(el('p','context-note',state.analysis.current?'Insufficient reference coverage':'Market data is not current'));return;}
  const metrics=el('div','context-metrics');metrics.append(metric('Market median',pct(m.median)),metric('Assets rising',decimal(100*m.up/m.n,1)+'%'));box.append(metrics);
  const bar=el('div','breadth-bar');bar.setAttribute('role','img');bar.setAttribute('aria-label',t('{up} rising, {flat} unchanged, {down} falling',{up:m.up,flat:m.flat,down:m.down}));
  for(const [kind,count] of [['rising',m.up],['flat',m.flat],['falling',m.down]]){const part=el('span',kind);part.style.width=(100*count/m.n)+'%';bar.append(part);}
  box.append(bar,el('p','context-note',t('{n} / {total} assets · stablecoins included',{n:m.n,total:m.total})));
  const quality=el('p','context-quality'+(m.dated<m.n?' limited':''),t('{dated} / {n} observation times supplied',{dated:m.dated,n:m.n}));
  quality.title=t('Collection time does not establish when a provider observed a price.');box.append(quality);
}
function renderSignals(){
  const list=sourceCoins(),analysis=state.analysis,items=[];
  for(const c of list)for(const event of eventsFor(c)?.events||[])items.push({c,event});
  items.sort((a,b)=>b.event.score-a.event.score||a.c.id.localeCompare(b.c.id));
  $('signalCount').textContent=items.length;$('panelCount').textContent=items.length;
  $('signalsPanel').querySelector('.eyebrow').textContent=t(state.view==='xstocks'?'Tokenized markets':state.view==='market'?'In the top 100':'In your watchlist');
  $('signalsTitle').firstChild.textContent=t(state.view==='xstocks'?'Price tracking':'Signals')+' ';
  $('panelCount').hidden=state.view==='xstocks';
  $('signalContext').textContent=t('{period} · {n} reference assets',{period:t(periods[state.settings.tf]),n:analysis.price.n});
  const container=$('signalList'),focused=container.contains(document.activeElement)?document.activeElement.dataset.signal:null;container.replaceChildren();
  const xcount=list.filter(C.isXstock).length,onlyXstocks=state.view==='xstocks'||(list.length&&xcount===list.length);
  if(onlyXstocks){
    $('signalContext').textContent=t('CoinGecko · token market data');
    container.append(el('h3','empty-title','A separate market'),el('p','empty-description','xStocks are outside the crypto reference. Price, performance and volume remain available in each asset sheet.'),el('p','empty-description','A token provides economic exposure, without shareholder voting rights.'));
    return;
  }
  if(xcount)container.append(el('p','catalog-note',t('{n} xStocks tracked separately from crypto signals',{n:xcount})));
  if(!items.length){
    let title='No active signals',body='No thresholds crossed in this selection.';
    if(!state.snapshot){title='Waiting for market data';body='Signals will appear after a valid snapshot arrives.';}
    else if(!analysis.current){title='Signals paused';body='Current market data is required.';}
    else if(!list.length){title='Your signals start here';body='Choose the assets you want to follow.';}
    else if(!list.some(c=>eventsFor(c)?.available)){title='Signals unavailable';body='The selected period needs valid returns and at least 20 reference assets.';}
    container.append(el('h3','empty-title',title),el('p','empty-description',body));
  }
  for(const {c,event} of items){
    const row=button('', 'signal-item '+event.kind,()=>openAsset(c.id));
    row.dataset.signal=c.id+'-'+event.kind;
    const top=el('span','signal-item-top');top.append(coinImage(c),el('b','',c.name,false),el('span',c[C.TF[state.settings.tf]]>=0?'up':'down',pct(c[C.TF[state.settings.tf]])));
    const reading=signalReading(c,event.kind),label=el('span','signal-label-row');
    label.append(el('strong','signal-label',event.label),el('b','signal-score',decimal(reading.value)));
    row.append(top,label,signalGauge(reading,true),el('span','signal-meta',event.kind==='divergence'?'24H z-score gap · threshold > 1.2':t('{period} z-score · threshold {threshold}',{period:t(state.settings.tf.toUpperCase()),threshold:event.kind==='price'?'|z| > 2':'> 2'})));
    row.title='CoinGecko · '+t('Collected {date}',{date:date(state.snapshot.snapshot)});
    container.append(row);
  }
  if(items.length&&list.some(c=>!eventsFor(c)?.available))container.append(el('p','empty-description','Some assets have insufficient or stale data.'));
  if(state.settings.tf!=='24h')container.append(el('p','empty-description','Price anomalies only. Activity comparisons are available in 24H.'));
  if(focused)container.querySelector(`[data-signal="${CSS.escape(focused)}"]`)?.focus({preventScroll:true});
}
function filteredCoins(){return mapCoins().filter(c=>{
  if(state.onboarding)return true;
  const p=c[C.TF[state.settings.tf]],r=eventsFor(c);
  return state.settings.filter==='all'||state.settings.filter==='gainers'&&p!=null&&p>0||state.settings.filter==='losers'&&p!=null&&p<0||state.settings.filter==='divergence'&&r?.divergence!=null||state.settings.filter==='anomaly'&&r?.events.some(e=>e.kind!=='divergence');
});}
function drawMap(){cancelAnimationFrame(canvasFrame);canvasFrame=requestAnimationFrame(paintMap);}
function paintMap(){
  const stage=$('stage'),w=stage.clientWidth,h=stage.clientHeight,dpr=Math.min(devicePixelRatio||1,2);
  if(w<=0||h<=0)return;
  canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
  const list=filteredCoins(),max=Math.max(1,...list.map(c=>Math.abs(c[C.TF[state.settings.tf]]||0)));
  // Keep selection order stable. Only areas change with the chosen metric.
  rects=C.squarify(list.map(c=>({id:c.id,coin:c,value:state.settings.metric==='perf'?.12+.88*Math.abs(c[C.TF[state.settings.tf]]||0)/max:Math.max(1,c[state.settings.metric]||1)})),{x:0,y:0,w,h});
  const hits=$('tileButtons'),focused=document.activeElement?.dataset?.tile;
  hits.replaceChildren();$('mapMessage').hidden=!!list.length;
  if(!list.length){
    let title='A little more focus.',body='Your chosen assets will appear here.';
    if(!state.snapshot){title=state.error?'Market data unavailable':'Loading market data';body=state.error?'We will retry automatically. Your watchlist is kept.':'';}
    else if(state.settings.filter!=='all'&&sourceCoins().length){title='No matching assets';body='Nothing in this selection matches the current filter.';}
    else if(state.view==='xstocks'){title='xStocks unavailable';body='The xStocks feed is unavailable. Please try again later.';}
    else if(state.selected.size){title='Selected assets unavailable';body='Your selection is kept until these assets return to the feed.';}
    $('mapMessageTitle').textContent=t(title);$('mapMessageBody').textContent=t(body);$('resetFilter').hidden=state.settings.filter==='all';
  }
  for(const r of rects){
    paintTile(r);
    const b=button('', 'tile-hit',()=>openAsset(r.id));b.dataset.tile=r.id;
    const p=r.coin[C.TF[state.settings.tf]],events=eventsFor(r.coin)?.events||[];
    b.setAttribute('aria-label',r.coin.name+', '+pct(p)+', '+t(state.settings.tf.toUpperCase())+(C.isXstock(r.coin)?', '+t('Price observed {date}',{date:date(r.coin.last_updated)}):'')+(events.length?', '+events.map(e=>t(e.label)).join(', '):''));
    b.style.left=r.x+'px';b.style.top=r.y+'px';b.style.width=r.w+'px';b.style.height=r.h+'px';
    b.addEventListener('pointerenter',()=>showTooltip(r));b.addEventListener('pointerleave',hideTooltip);b.addEventListener('focus',()=>showTooltip(r));b.addEventListener('blur',hideTooltip);
    b.addEventListener('keydown',e=>{const delta={ArrowRight:1,ArrowDown:1,ArrowLeft:-1,ArrowUp:-1}[e.key];if(delta){e.preventDefault();const buttons=[...hits.children],index=buttons.indexOf(b);buttons[(index+delta+buttons.length)%buttons.length]?.focus();}});
    hits.append(b);
  }
  if(focused)hits.querySelector(`[data-tile="${CSS.escape(focused)}"]`)?.focus({preventScroll:true});
}
function logo(c){
  if(!c.has_logo)return null;
  const entry=logos.get(c.id);
  if(entry)return entry.ok?entry.img:null;
  const img=new Image(),item={img,ok:false};logos.set(c.id,item);
  img.onload=()=>{item.ok=true;drawMap();};img.onerror=()=>{item.ok=false;};img.src='./logos/'+encodeURIComponent(c.id)+'.png';return null;
}
function paintTile(r){
  const x=r.x+2,y=r.y+2,w=Math.max(0,r.w-4),h=Math.max(0,r.h-4);
  if(w<1||h<1)return;
  const c=r.coin,p=c[C.TF[state.settings.tf]],result=eventsFor(c),strength=Math.min(Math.abs(p||0)/12,1),xstock=C.isXstock(c),stale=xstock&&!C.quoteState(state.snapshot,c).usable;
  ctx.save();ctx.beginPath();ctx.roundRect(x,y,w,h,Math.min(6,w/2,h/2));ctx.clip();
  ctx.fillStyle=p==null||stale?'#24282c':p>=0?`hsl(154 40% ${23+strength*13}%)`:`hsl(354 39% ${25+strength*13}%)`;ctx.fillRect(x,y,w,h);
  if(result?.events.length){ctx.strokeStyle=result.divergence!=null?'#85d8ed':'#f7d877';ctx.lineWidth=4;ctx.strokeRect(x+1,y+1,w-2,h-2);}
  const img=logo(c),badge=(xstock||result?.events.length)&&Math.min(w,h)>76?22:0;
  const content=C.tileContent(w,h-badge,!!img),text=p==null?'N/A':pct(p);
  let fs=content.font;
  ctx.font=`650 ${fs}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;
  const measured=ctx.measureText(text).width;if(measured>w-content.pad*2)fs*=Math.max(0,w-content.pad*2)/measured;
  const block=content.logo+(img?content.gap:0)+fs,top=y+badge+(h-badge-block)/2;
  if(img&&content.logo>8){ctx.save();ctx.beginPath();ctx.arc(x+w/2,top+content.logo/2,content.logo/2,0,Math.PI*2);ctx.clip();ctx.drawImage(img,x+(w-content.logo)/2,top,content.logo,content.logo);ctx.restore();}
  if(fs>=6){ctx.font=`650 ${fs}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;ctx.fillStyle='#fff';ctx.textAlign='center';ctx.textBaseline='top';ctx.fillText(text,x+w/2,top+content.logo+(img?content.gap:0));}
  if(badge){ctx.font='600 10px system-ui';ctx.textAlign='left';ctx.textBaseline='top';ctx.fillStyle=xstock?'#d3dee4':result.divergence!=null?'#b9edfa':'#fff0b3';ctx.fillText(xstock?c.symbol.toUpperCase():t(result.divergence!=null?'DIVERGENCE':'ANOMALY'),x+10,y+8,w-20);}
  ctx.restore();
}
function showTooltip(r){const node=$('tileTooltip');node.textContent=r.coin.name+' · '+r.coin.symbol.toUpperCase()+' · '+pct(r.coin[C.TF[state.settings.tf]])+(C.isXstock(r.coin)?' · '+t('Price observed {date}',{date:date(r.coin.last_updated)}):'');node.hidden=false;node.style.left=Math.max(8,Math.min(r.x+8,$('stage').clientWidth-node.offsetWidth-8))+'px';node.style.top=Math.max(8,Math.min(r.y+8,$('stage').clientHeight-node.offsetHeight-8))+'px';}
function hideTooltip(){$('tileTooltip').hidden=true;}
function renderChoosers(){
  for(const prefix of ['welcome','manage']){
    const control=$(prefix+'Catalog');
    if(!control.children.length)for(const [value,label] of [['all','All assets'],['crypto','Crypto'],['xstock','xStocks']]){
      const b=button(label,'',()=>{state.catalog=value;manageLimit=80;renderChoosers();});b.dataset.catalog=value;control.append(b);
    }
    for(const b of control.children){b.setAttribute('aria-pressed',String(b.dataset.catalog===state.catalog));b.textContent=t({all:'All assets',crypto:'Crypto',xstock:'xStocks'}[b.dataset.catalog]);}
    const note=$(prefix+'CatalogNote'),source=C.sourceState(state.snapshot,'coingecko_xstocks');
    note.textContent=t(state.catalog==='xstock'?(source.usable?'Delayed token quotes':xstockCoins().length?'Collection interrupted · last received quotes shown.':'The xStocks feed is unavailable. Please try again later.'):'Crypto and xStocks, in one watchlist.');
    note.classList.toggle('limited',state.catalog==='xstock'&&!source.usable);
  }
  renderChoices('welcomeResults',$('welcomeSearch').value,12,false);renderChoices('manageResults',$('manageSearch').value,manageLimit,$('selectedOnly').checked);renderSelection();
}
function renderChoices(target,query,limit,onlySelected){
  const container=$(target),focused=container.contains(document.activeElement)?document.activeElement.dataset.coin:null;
  const q=C.text(query,80).toLowerCase();
  const base=onlySelected?[...state.selected].map(id=>byId(id)||{id,name:id,symbol:'unavailable',current_price:null,has_logo:false}):coins();
  const matching=base.filter(c=>(state.catalog==='all'||(C.isXstock(c)?'xstock':'crypto')===state.catalog)&&(!q||c.name.toLowerCase().includes(q)||c.symbol.toLowerCase().includes(q)||c.id===q));
  container.replaceChildren();
  for(const c of matching.slice(0,limit)){
    const selected=state.selected.has(c.id),row=button('', 'coin-choice',()=>toggleCoin(c.id));row.dataset.coin=c.id;row.setAttribute('aria-pressed',String(selected));
    const identity=el('span','coin-identity');identity.append(el('b','',c.name,false),el('small','',c.symbol.toUpperCase(),false));
    if(C.isXstock(c)){const badge=el('span','asset-badge','xStock');identity.lastChild.append(badge);}
    const values=el('span','coin-values');values.append(el('span','',price(c.current_price,C.isXstock(c))),el('small',c[C.TF[state.settings.tf]]>=0?'up':'down',pct(c[C.TF[state.settings.tf]])));
    if(C.isXstock(c)){const status=C.quoteState(state.snapshot,c);values.lastChild.className='muted';values.lastChild.textContent=t('Quoted {age}',{age:age(status.age)});values.title=t('Price observed {date}',{date:date(c.last_updated)});}
    row.append(coinImage(c),identity,values,icon(selected?'check':'plus'));row.setAttribute('aria-label',t(selected?'Remove {name}':'Add {name}',{name:c.name}));container.append(row);
  }
  if(!matching.length)container.append(el('p','empty-description',state.loading?'Loading assets...':!state.snapshot?'Market data is unavailable.':onlySelected?'No selected assets match.':'No matching asset in the current feed.'));
  if(target==='manageResults')$('moreCoins').hidden=matching.length<=limit;
  if(focused)container.querySelector(`[data-coin="${CSS.escape(focused)}"]`)?.focus({preventScroll:true});
}
function openDialog(id){const d=$(id);d._opener=document.activeElement;if(!d.open)d.showModal();}
function openAsset(id){const c=byId(id);if(!c)return;hideTooltip();state.activeCoin=id;state.assetTab=C.isXstock(c)?'market':'signals';renderAsset();openDialog('assetDialog');$('assetDialog').scrollTop=0;}
function metric(label,value){const n=el('div','detail-metric');n.append(el('span','',label),el('b','',value));return n;}
function signalReading(c,kind){
  const result=eventsFor(c),event=result?.events.find(e=>e.kind===kind);
  const value=kind==='price'?result?.priceZ:kind==='activity'?result?.activityZ:
    Number.isFinite(result?.priceZ)&&Number.isFinite(result?.activityZ)?result.priceZ-result.activityZ:null;
  return {kind,value:Number.isFinite(value)?value:null,active:!!event,threshold:kind==='divergence'?1.2:2,
    label:{price:'Price anomaly',activity:'Turnover anomaly',divergence:'Price / activity gap'}[kind],
    status:event?.label||(!result?.available?result?.reason||'Signals unavailable':kind!=='price'&&state.settings.tf!=='24h'?'24H only':!Number.isFinite(value)?'Insufficient activity data':'Within threshold')};
}
function signalGauge(reading,compact=false){
  const {kind,value,threshold,active,label}=reading,extent=Math.max(4,Math.ceil(Math.abs(value||0)));
  const gauge=el('div','signal-gauge '+kind+(active?' is-active':'')+(value===null?' is-unavailable':'')+(compact?' compact':''));
  gauge.setAttribute('role','img');
  gauge.setAttribute('aria-label',value===null?t(label)+': '+t(reading.status):t('{label}: {value} {unit}. Threshold {rule} {threshold}',{label:t(label),value:decimal(value),unit:t(kind==='divergence'?'z-score gap':'z-score'),rule:t(kind==='activity'?'above':'absolute value above'),threshold:decimal(threshold,kind==='divergence'?1:0)}));
  const track=el('span','gauge-track');track.setAttribute('aria-hidden','true');
  if(value!==null){
    const position=v=>(v+extent)/(2*extent)*100;
    const band=el('span','gauge-band');band.style.left=(kind==='activity'?0:position(-threshold))+'%';band.style.right=(100-position(threshold))+'%';track.append(band);
    const zero=el('span','gauge-zero');track.append(zero);
    for(const boundary of kind==='activity'?[threshold]:[-threshold,threshold]){const tick=el('span','gauge-threshold');tick.style.left=position(boundary)+'%';track.append(tick);}
    const fill=el('span','gauge-fill');fill.style.left=Math.min(50,position(value))+'%';fill.style.width=Math.abs(position(value)-50)+'%';track.append(fill);
    const marker=el('span','gauge-marker');marker.style.left=position(value)+'%';track.append(marker);
  }
  gauge.append(track);
  if(!compact){const scale=el('span','gauge-scale');scale.setAttribute('aria-hidden','true');scale.append(el('span','',value===null?'':String(-extent)),el('span','',value===null?'Unavailable':(kind==='activity'?'z > ':'|z| > ')+decimal(threshold,kind==='divergence'?1:0)),el('span','',value===null?'':'+'+extent));gauge.append(scale);}
  return gauge;
}
function renderAssetSignals(c){
  const result=eventsFor(c),section=el('section','asset-signals'),summary=el('div','signal-summary');
  summary.append(el('h3','',result?.available?(result.events.length?t(result.events.length>1?'{n} signals detected':'{n} signal detected',{n:result.events.length}):'No thresholds crossed'):'Signals unavailable'),el('span','',state.settings.tf.toUpperCase()));
  section.append(summary);
  const comparisons=el('div','asset-comparisons'),relative=result?.relativeBTC;
  for(const [key,label,value] of [['btc','vs BTC',relative?.value],['median','vs market median',result?.medianGap]]){
    const item=metric(label,Number.isFinite(value)?key==='btc'?pct(value):(value>=0?'+':'')+decimal(value)+' '+t('pp'):'N/A');item.dataset.comparison=key;
    item.title=t(key==='btc'?(relative?.reason||'Relative return, not a percentage-point difference.'):'Difference from the market median, in percentage points.');
    const number=item.querySelector('b');if(Number.isFinite(value))number.classList.add(value>0?'up':value<0?'down':'muted');comparisons.append(item);
  }
  section.append(comparisons);
  const dated=result?.observation==='current',unknownBTC=Number.isFinite(relative?.value)&&!relative.dated;
  const qualityText=!state.analysis.current?'Market data is not current':dated?(unknownBTC?'Bitcoin observation time unknown':'Dated asset price'):result?.observation==='unknown'?'Collection only · observation time unknown':result?.reason||'Price observation time unavailable';
  const observationLabel=el('p','comparison-quality'+(!state.analysis.current||!dated||unknownBTC?' limited':''),qualityText);
  observationLabel.title=t('Collection time does not establish when a provider observed a price.');section.append(observationLabel);
  for(const kind of ['price','activity','divergence']){
    const reading=signalReading(c,kind),row=el('div','signal-reading '+kind+(reading.active?' is-active':''));row.dataset.reading=kind;
    const heading=el('div','reading-heading'),copy=el('div'),value=el('div','reading-value');
    copy.append(el('h4','',reading.label),el('p','',reading.status));
    value.append(el('b','',reading.value===null?'N/A':(reading.value>=0?'+':'')+decimal(reading.value)),el('span','',kind==='divergence'?'z gap':'z-score'));
    heading.append(copy,value);row.append(heading,signalGauge(reading));section.append(row);
  }
  const foot=el('div','signal-footnote');
  if(c.last_updated)foot.append(el('p','observation-quality',t('Price observed {date}',{date:date(c.last_updated)})));
  if(relative?.reason)foot.append(el('p','',t('vs BTC')+': '+t(relative.reason)));
  foot.append(el('p','',t('{price} price / {activity} activity peers · CoinGecko',{price:state.analysis.price.n,activity:state.analysis.activity.n})),el('p','',t('Collected {date}',{date:date(state.snapshot.snapshot)})),el('p','', 'Snapshot comparisons, not independent confirmations or forecasts.'));
  const method=button('Methodology','text-button',()=>openDialog('methodDialog'));method.id='assetMethod';foot.append(method);section.append(foot);
  return section;
}
function selectAssetTab(tab,focus=false){
  state.assetTab=tab;
  for(const id of ['signals','market']){
    const selected=tab===id,b=$('assetTab-'+id);if(!b)continue;b.setAttribute('aria-selected',String(selected));b.tabIndex=selected?0:-1;
    $('assetPane-'+id).hidden=!selected;
  }
  $('assetDialog').scrollTop=0;
  if(focus)$('assetTab-'+tab)?.focus({preventScroll:true});
  const chart=$('assetPane-market').querySelector('.spark'),c=byId(state.activeCoin);
  if(tab==='market'&&chart&&c)requestAnimationFrame(()=>drawSpark(chart,c.spark));
}
function renderAsset(){
  const restoreFocus=$('assetContent').contains(document.activeElement)?document.activeElement.id:null;
  const scrollTop=$('assetDialog').scrollTop;
  const c=byId(state.activeCoin);if(!c){$('assetContent').replaceChildren(el('p','', 'This asset is no longer in the current snapshot.'));return;}
  const xstock=C.isXstock(c),quoteStatus=C.quoteState(state.snapshot,c);
  const identity=$('assetIdentity');identity.replaceChildren(coinImage(c));const name=el('div');name.append(el('h2','',c.name,false),el('span','muted',c.symbol.toUpperCase(),false));name.querySelector('h2').id='assetTitle';identity.append(name);
  const body=$('assetContent');body.replaceChildren();
  if(xstock){
    state.assetTab='market';
    const note=el('div','xstock-notice');note.append(el('span','asset-badge','xStock'),el('p','','Token market data. Economic exposure to a stock or ETF, without shareholder voting rights.'));
    const docs=el('a','','xStocks documentation');docs.href='https://docs.xstocks.fi/docs/frequently-asked-questions';docs.target='_blank';docs.rel='noopener noreferrer';note.append(docs);body.append(note);
  }
  const head=el('div','asset-price'),quote=el('div','asset-quote');quote.append(el('b','',price(c.current_price,C.isXstock(c))),el('span',c[C.TF[state.settings.tf]]>=0?'up':'down',pct(c[C.TF[state.settings.tf]])+' · '+t(state.settings.tf.toUpperCase())));
  const fav=button('','icon-button',()=>toggleCoin(c.id));fav.id='assetFavorite';fav.title=t(state.selected.has(c.id)?'Remove from watchlist':'Add to watchlist');fav.setAttribute('aria-label',fav.title);fav.setAttribute('aria-pressed',String(state.selected.has(c.id)));fav.append(icon('star'));head.append(quote,fav);body.append(head);
  if(xstock){
    if(!quoteStatus.usable)quote.lastChild.className='muted';
    const label=!quoteStatus.source.usable?'Collection interrupted · last received quote.':quoteStatus.age>600000?'Provider quote older than 10 min.':quoteStatus.kind==='delayed'?'Delayed quote.':quoteStatus.kind==='current'?'Last quoted price.':'Quote timestamp unavailable or invalid.';
    body.append(el('p',quoteStatus.usable?'observation-quality':'quote-warning',t(label)+' '+t('Price observed {date}',{date:date(c.last_updated)})));
  }
  const tabs=el('div','asset-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label',t('Asset details'));
  for(const [id,label] of xstock?[['market','Token market data']]:[['signals','Signals'],['market','Market data']]){
    const tab=button(label,'',()=>selectAssetTab(id));tab.id='assetTab-'+id;tab.setAttribute('role','tab');tab.setAttribute('aria-controls','assetPane-'+id);
    tab.addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();selectAssetTab(xstock?'market':e.key==='Home'?'signals':e.key==='End'?'market':state.assetTab==='signals'?'market':'signals',true);}});
    tabs.append(tab);
  }
  body.append(tabs);
  const market=el('section','asset-market');
  for(const [id,pane] of xstock?[['market',market]]:[['signals',renderAssetSignals(c)],['market',market]]){pane.id='assetPane-'+id;pane.setAttribute('role','tabpanel');pane.setAttribute('aria-labelledby','assetTab-'+id);pane.tabIndex=0;body.append(pane);}
  market.append(el('p','detail-date',(c.last_updated?t('Price observed {date}',{date:date(c.last_updated)}):t('Price observation time unavailable'))+t(' · snapshot collected {date}',{date:date(quoteStatus.source.stamp)})));
  if(c.spark.length>1){const chart=el('canvas','spark');chart.setAttribute('role','img');chart.setAttribute('aria-label',t('7-day price history'));market.append(chart,el('p','detail-date','7-day price history · CoinGecko'));}
  const performance=el('div','detail-grid');for(const tf of Object.keys(C.TF))performance.append(metric(tf.toUpperCase(),pct(c[C.TF[tf]])));market.append(performance);
  const social=C.sourceState(state.snapshot,'lunarcrush');
  if(!xstock){market.append(el('h3','detail-subtitle','Social context'));
    market.append(el('p','muted',social.usable&&c.galaxy_score!==null?t('Galaxy Score {score}/100{sentiment} · LunarCrush, {date}. Symbol-based match; indicative only.',{score:c.galaxy_score,sentiment:c.sentiment!==null?t(' · sentiment {value}%',{value:c.sentiment}):'',date:date(social.stamp)}):'LunarCrush data unavailable for this asset.'));}
  const metrics=el('div','detail-grid');metrics.append(metric(xstock?'Token market cap':'Market cap',big(c.market_cap)),metric(xstock?'Token volume · 24H':'24H volume',big(c.total_volume)),metric('All-time high',price(c.ath,xstock)),metric('Circulating supply',c.circulating_supply==null?'Unavailable':new Intl.NumberFormat(locale(),{notation:'compact'}).format(c.circulating_supply)));market.append(metrics);
  if(xstock)market.append(el('p','detail-date','Token capitalization is not the value of the underlying company.'));
  const link=el('a','external-link','View on CoinGecko');link.id='assetExternalLink';link.href='https://www.coingecko.com/en/coins/'+encodeURIComponent(c.id);link.target='_blank';link.rel='noopener noreferrer';link.append(icon('external-link'));market.append(link);
  selectAssetTab(state.assetTab);$('assetDialog').scrollTop=scrollTop;
  if(restoreFocus)$(restoreFocus)?.focus({preventScroll:true});
}
function drawSpark(cnv,points){const w=cnv.clientWidth,h=96,dpr=Math.min(devicePixelRatio||1,2);cnv.width=w*dpr;cnv.height=h*dpr;const x=cnv.getContext('2d');x.scale(dpr,dpr);const min=Math.min(...points),max=Math.max(...points),range=max-min||1;x.beginPath();points.forEach((p,i)=>{const a=i/(points.length-1)*(w-8)+4,b=h-8-(p-min)/range*(h-16);i?x.lineTo(a,b):x.moveTo(a,b);});x.strokeStyle=points.at(-1)>=points[0]?'#7cdeb1':'#ff9da6';x.lineWidth=2;x.stroke();}
async function refresh(){
  if(busy||document.hidden)return;
  busy=true;const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),12000);
  try{
    const response=await fetch('./data.json',{headers:{Accept:'application/json'},signal:controller.signal});
    if(!response.ok)throw new Error('Snapshot unavailable');
    const raw=await response.text();if(raw.length>6000000)throw new Error('Snapshot too large');
    const snapshot=C.normalizeSnapshot(JSON.parse(raw));
    if(state.snapshot&&C.time(snapshot.snapshot)<C.time(state.snapshot.snapshot))throw new Error('Older snapshot');
    const changed=state.snapshot?.snapshot!==snapshot.snapshot;
    state.snapshot=snapshot;state.error=false;
    if(changed)for(const [id,entry]of logos)if(!entry.ok)logos.delete(id);
  }catch{state.error=true;}finally{
    clearTimeout(timeout);busy=false;state.loading=false;render();renderChoosers();if($('assetDialog').open)renderAsset();
    clearTimeout(refreshTimer);refreshTimer=setTimeout(refresh,30000+Math.random()*15000);
  }
}
function prepareImport(){const file=$('importFile').files[0];if(!file)return;if(file.size>16384){toast('Watchlist files must be smaller than 16 KB.');return;}
  file.text().then(raw=>{pendingImport=C.importWatchlist(raw);$('importSummary').textContent=t('{n} assets in this file. Display preferences will also be restored.',{n:pendingImport.coins.length});updateImportPreview();openDialog('importDialog');}).catch(e=>toast(e.message)).finally(()=>$('importFile').value='');
}
function updateImportPreview(){
  if(!pendingImport)return;
  try{const ids=C.mergeWatchlist([...state.selected],pendingImport.coins,document.querySelector('[name="importMode"]:checked').value==='replace');const unknown=ids.filter(id=>!byId(id)).length;$('importWarning').textContent=t('{n} assets after import',{n:ids.length})+(unknown?t(' · {n} currently unavailable; identifiers will be kept.',{n:unknown}):'.');$('confirmImport').disabled=false;}catch(e){$('importWarning').textContent=t(e.message);$('confirmImport').disabled=true;}
}
document.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',()=>b.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(d=>{d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();}});d.addEventListener('close',()=>{if(d.id==='assetDialog')state.activeCoin=null;const opener=d._opener;if(opener?.isConnected)opener.focus();else if(opener?.id)$(opener.id)?.focus();else if(opener?.dataset.tile)$('tileButtons').querySelector(`[data-tile="${CSS.escape(opener.dataset.tile)}"]`)?.focus();else if(opener?.dataset.signal)$('signalList').querySelector(`[data-signal="${CSS.escape(opener.dataset.signal)}"]`)?.focus();});});
$('manageBtn').addEventListener('click',()=>{manageLimit=80;state.catalog=state.view==='xstocks'?'xstock':'all';renderChoosers();openDialog('manageDialog');$('manageSearch').focus();});
$('homeLink').addEventListener('click',e=>{e.preventDefault();state.onboarding=true;state.picking=false;state.view='fav';render();});
$('buildWatchlist').addEventListener('click',()=>{if(state.selected.size){state.onboarding=false;render();$('manageBtn').focus();}else{state.picking=true;render();$('welcomeSearch').focus();}});
$('exploreMarket').addEventListener('click',()=>{state.onboarding=false;state.view='market';render();document.querySelector('[data-view="market"]').focus();});
$('settingsBtn').addEventListener('click',()=>openDialog('settingsDialog'));
$('methodBtn').addEventListener('click',()=>openDialog('methodDialog'));
$('finishWelcome').addEventListener('click',()=>{state.onboarding=false;state.settings.filter='all';save();render();$('manageBtn').focus();});
$('welcomeSearch').addEventListener('input',renderChoosers);$('manageSearch').addEventListener('input',()=>{manageLimit=80;renderChoosers();});$('selectedOnly').addEventListener('change',renderChoosers);
$('moreCoins').addEventListener('click',()=>{manageLimit+=80;renderChoosers();});
document.querySelectorAll('[data-tf]').forEach(b=>b.addEventListener('click',()=>changeSetting('tf',b.dataset.tf)));
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{state.view=b.dataset.view;state.onboarding=state.view==='fav'&&!state.selected.size;if(state.view==='xstocks'&&['anomaly','divergence'].includes(state.settings.filter))changeSetting('filter','all');else render();}));
$('filterSelect').addEventListener('change',e=>changeSetting('filter',e.target.value));$('sizeSelect').addEventListener('change',e=>changeSetting('metric',e.target.value));
$('resetFilter').addEventListener('click',()=>changeSetting('filter','all'));
$('signalsToggle').addEventListener('click',()=>changeSetting('signalsOpen',!state.settings.signalsOpen));$('closeSignals').addEventListener('click',()=>{changeSetting('signalsOpen',false);$('signalsToggle').focus();});
for(const id of ['homeImport','introImport','importBtn'])$(id).addEventListener('click',()=>$('importFile').click());
$('importFile').addEventListener('change',prepareImport);document.querySelectorAll('[name="importMode"]').forEach(n=>n.addEventListener('change',updateImportPreview));
$('confirmImport').addEventListener('click',()=>{try{state.selected=new Set(C.mergeWatchlist([...state.selected],pendingImport.coins,document.querySelector('[name="importMode"]:checked').value==='replace'));state.settings=pendingImport.settings;state.onboarding=state.selected.size===0;save();$('importDialog').close();if($('settingsDialog').open)$('settingsDialog').close();pendingImport=null;render();renderChoosers();toast('Watchlist imported.');}catch(e){toast(e.message);}});
$('exportBtn').addEventListener('click',()=>{const data={version:1,coins:[...state.selected],settings:state.settings};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=el('a');a.href=url;a.download='orbit2-watchlist.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$('fullscreenBtn').addEventListener('click',async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else if(document.documentElement.requestFullscreen)await document.documentElement.requestFullscreen();else toast('Full screen is not supported by this browser.');}catch{toast('Full screen could not be opened.');}});
document.addEventListener('fullscreenchange',()=>{const active=!!document.fullscreenElement,b=$('fullscreenBtn');b.title=t(active?'Exit full screen':'Full screen');b.setAttribute('aria-label',b.title);b.replaceChildren(icon(active?'minimize':'maximize'));drawMap();});
document.addEventListener('orbit:language',()=>{render();renderChoosers();if($('assetDialog').open)renderAsset();if(pendingImport){$('importSummary').textContent=t('{n} assets in this file. Display preferences will also be restored.',{n:pendingImport.coins.length});updateImportPreview();}});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
window.addEventListener('storage',e=>{if(e.key===FAV_KEY){const v=readStorage(FAV_KEY,[]);if(Array.isArray(v))state.selected=new Set(v.filter(id=>typeof id==='string'&&C.ID.test(id)).slice(0,50));render();renderChoosers();}});
new ResizeObserver(drawMap).observe($('stage'));
setInterval(()=>{if(document.hidden)return;render();if($('assetDialog').open)renderAsset();},15000);
render();renderChoosers();refresh();
