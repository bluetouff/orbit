'use strict';
const C=OrbitCore,$=id=>document.getElementById(id);
const ASSET_BASE=new URL('.',document.currentScript.src);
const FAV_KEY='orbit.favs.v1',SETTINGS_KEY='orbit.settings.v2';
function readStorage(key,fallback){try{return JSON.parse(localStorage.getItem(key))??fallback;}catch{return fallback;}}
const saved=readStorage(FAV_KEY,[]);
const state={snapshot:null,selected:new Set((Array.isArray(saved)?saved:[]).filter(id=>typeof id==='string'&&C.ID.test(id)).slice(0,50)),
  settings:C.settings(readStorage(SETTINGS_KEY,null)),view:'fav',onboarding:false,analysis:null,loading:true,error:false,activeCoin:null};
state.onboarding=state.selected.size===0;
let busy=false,refreshTimer,toastTimer,manageLimit=80,pendingImport=null,rects=[],canvasFrame=0;
const logos=new Map(),canvas=$('map'),ctx=canvas.getContext('2d');
const pct=v=>v==null?'Unavailable':(v>=0?'+':'')+v.toFixed(Math.abs(v)>=10?1:2)+'%';
const price=v=>v==null?'Unavailable':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:v<1?8:v<100?2:0}).format(v);
const big=v=>v==null?'Unavailable':new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:2,style:'currency',currency:'USD'}).format(v);
const date=v=>C.time(v)===null?'Unknown':new Date(v).toLocaleString('en-GB',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'UTC'})+' UTC';
const age=ms=>ms==null||ms<0?'Unknown':ms<60000?'Just now':ms<3600000?Math.floor(ms/60000)+'m ago':ms<86400000?Math.floor(ms/3600000)+'h ago':Math.floor(ms/86400000)+'d ago';
const periods={'1h':'1-hour','24h':'24-hour','7d':'7-day','30d':'30-day'};
function el(tag,className,content){const n=document.createElement(tag);if(className)n.className=className;if(content!==undefined)n.textContent=content;return n;}
function icon(name){const n=el('img','icon');n.src=new URL('icons/'+name+'.svg',ASSET_BASE).href;n.alt='';return n;}
function coinImage(c){if(!c.has_logo)return el('span','coin-logo');const n=el('img','coin-logo');n.src='./logos/'+encodeURIComponent(c.id)+'.png';n.alt='';n.loading='lazy';n.addEventListener('error',()=>{n.replaceWith(el('span','coin-logo'));},{once:true});return n;}
function button(label,className,handler){const n=el('button',className,label);n.type='button';if(handler)n.addEventListener('click',handler);return n;}
function toast(message){$('toast').textContent=message;$('toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.remove('show'),3500);}
function save(){try{localStorage.setItem(FAV_KEY,JSON.stringify([...state.selected]));localStorage.setItem(SETTINGS_KEY,JSON.stringify(state.settings));}catch{toast('Browser storage is unavailable. Export your watchlist to keep it.');}}
function coins(){return state.snapshot?.coins||[];}
function byId(id){return coins().find(c=>c.id===id);}
function sourceCoins(){return state.view==='market'?coins().slice(0,100):[...state.selected].map(byId).filter(Boolean);}
function eventsFor(c){return state.analysis?.byId.get(c.id);}
function toggleCoin(id){
  if(!C.ID.test(id))return;
  if(state.selected.has(id))state.selected.delete(id);
  else if(state.selected.size<50)state.selected.add(id);
  else {toast('Your watchlist is limited to 50 coins.');return;}
  save();render();renderChoosers();
  if(state.activeCoin===id)renderAsset();
}
function changeSetting(key,value){state.settings=C.settings({...state.settings,[key]:value});save();render();}
function render(){
  state.analysis=C.analyze(state.snapshot,state.settings.tf);
  $('shell').classList.toggle('onboarding',state.onboarding);
  $('welcome').hidden=!state.onboarding;
  $('signalsPanel').hidden=state.onboarding||!state.settings.signalsOpen;
  $('workspace').classList.toggle('with-signals',!$('signalsPanel').hidden);
  $('workspace').classList.toggle('with-welcome',state.onboarding);
  $('watchCount').textContent=state.selected.size;
  document.querySelectorAll('[data-tf]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tf===state.settings.tf)));
  document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===state.view)));
  $('filterSelect').value=state.settings.filter;$('sizeSelect').value=state.settings.metric;
  $('signalsToggle').setAttribute('aria-expanded',String(state.settings.signalsOpen));
  $('mapTitle').textContent=state.onboarding?'Your selection':state.view==='market'?'Market':'Watchlist';
  const list=sourceCoins(),returns=list.map(c=>c[C.TF[state.settings.tf]]).filter(Number.isFinite);
  const missing=state.view==='fav'?state.selected.size-list.length:0;
  $('mapSummary').textContent=list.length+' coins'+(missing?' · '+missing+' unavailable':'')+(returns.length?' · mean '+pct(returns.reduce((a,b)=>a+b,0)/returns.length):'');
  $('periodCaption').textContent=periods[state.settings.tf]+' performance · USD';
  renderSources();renderSignals();drawMap();renderSelection();
}
function renderSelection(){
  $('welcomeCount').textContent=state.selected.size+' of 50 selected';$('manageCount').textContent=state.selected.size+' / 50 selected';
  $('finishWelcome').disabled=state.selected.size===0;
}
function renderSources(){
  const source=C.sourceState(state.snapshot,'coingecko_markets');
  $('marketAge').textContent=(source.usable?'Received ':'Market data: '+source.kind+' · ')+age(source.age);
  $('marketAge').classList.toggle('warning',!source.usable);
  $('marketAge').title='Snapshot collected '+date(source.stamp);
  $('connectionStatus').textContent=state.error?'Connection interrupted · retrying':state.loading?'Connecting':'Same-origin data';
  const summary=$('marketSummary');summary.replaceChildren();
  const global=C.sourceState(state.snapshot,'coingecko_global').usable?state.snapshot?.global:null;
  if(global?.cap!=null)summary.append(el('span','', 'Market '+big(global.cap)));
  if(global?.btc!=null)summary.append(el('span','', 'BTC dominance '+global.btc.toFixed(1)+'%'));
  const box=$('sourceStatus');box.replaceChildren();
  for(const [key,name] of [['coingecko_markets','CoinGecko'],['lunarcrush','LunarCrush'],['fred','FRED']]){
    const s=C.sourceState(state.snapshot,key),row=el('div','source-row'),heading=el('div','source-heading');
    heading.append(el('b','',name),el('span','source-state '+s.kind,s.kind==='current'?'Current':s.kind));
    row.append(heading,el('span','source-time',s.stamp?'Collected '+age(s.age):'Collection time unavailable'));
    row.title='Collected '+date(s.stamp);
    if(key==='fred'){
      const m=state.snapshot?.macro;
      for(const [k,label] of [['us10y','10Y'],['usd','Broad USD']])if(m?.[k])row.append(el('span','source-observation',label+' '+m[k].value+(k==='us10y'?'%':'')+' · observed '+(m[k].date||'unknown')));
    }
    if(key==='lunarcrush'&&s.usable){const n=coins().filter(c=>c.galaxy_score!==null).length;row.append(el('span','source-observation',n+' assets covered · context only'));}
    box.append(row);
  }
}
function renderSignals(){
  const list=sourceCoins(),analysis=state.analysis,items=[];
  for(const c of list)for(const event of eventsFor(c)?.events||[])items.push({c,event});
  items.sort((a,b)=>b.event.score-a.event.score||a.c.id.localeCompare(b.c.id));
  $('signalCount').textContent=items.length;$('panelCount').textContent=items.length;
  $('signalsPanel').querySelector('.eyebrow').textContent=state.view==='market'?'In the top 100':'In your watchlist';
  $('signalContext').textContent=periods[state.settings.tf]+' · '+analysis.price.n+' reference assets';
  const container=$('signalList'),focused=container.contains(document.activeElement)?document.activeElement.dataset.signal:null;container.replaceChildren();
  if(!items.length){
    let title='No active signals',body='No thresholds crossed in this selection.';
    if(!state.snapshot){title='Waiting for market data';body='Signals will appear after a valid snapshot arrives.';}
    else if(!analysis.current){title='Signals paused';body='Current market data is required.';}
    else if(!list.length){title='Your signals start here';body='Choose the coins you want to follow.';}
    else if(!list.some(c=>eventsFor(c)?.available)){title='Signals unavailable';body='The selected period needs valid returns and at least 20 reference assets.';}
    container.append(el('h3','empty-title',title),el('p','empty-description',body));
  }
  for(const {c,event} of items){
    const row=button('', 'signal-item '+event.kind,()=>openAsset(c.id));
    row.dataset.signal=c.id+'-'+event.kind;
    const top=el('span','signal-item-top');top.append(coinImage(c),el('b','',c.name),el('span',c[C.TF[state.settings.tf]]>=0?'up':'down',pct(c[C.TF[state.settings.tf]])));
    row.append(top,el('strong','signal-label',event.label),el('span','signal-meta',event.kind==='divergence'?'24H price / turnover · CoinGecko':state.settings.tf.toUpperCase()+' · CoinGecko'),el('span','signal-time',date(state.snapshot.snapshot)));
    container.append(row);
  }
  if(items.length&&list.some(c=>!eventsFor(c)?.available))container.append(el('p','empty-description','Some assets have insufficient or stale data.'));
  if(state.settings.tf!=='24h')container.append(el('p','empty-description','Price anomalies only. Activity comparisons are available in 24H.'));
  if(focused)container.querySelector(`[data-signal="${CSS.escape(focused)}"]`)?.focus({preventScroll:true});
}
function filteredCoins(){return sourceCoins().filter(c=>{
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
    let title='A little more focus.',body='Your chosen coins will appear here.';
    if(!state.snapshot){title=state.error?'Market data unavailable':'Loading market data';body=state.error?'We will retry automatically. Your watchlist is kept.':'';}
    else if(state.settings.filter!=='all'&&sourceCoins().length){title='No matching coins';body='Nothing in this selection matches the current filter.';}
    else if(state.selected.size){title='Selected coins unavailable';body='Your selection is kept until these assets return to the feed.';}
    $('mapMessageTitle').textContent=title;$('mapMessageBody').textContent=body;$('resetFilter').hidden=state.settings.filter==='all';
  }
  for(const r of rects){
    paintTile(r);
    const b=button('', 'tile-hit',()=>openAsset(r.id));b.dataset.tile=r.id;
    const p=r.coin[C.TF[state.settings.tf]],events=eventsFor(r.coin)?.events||[];
    b.setAttribute('aria-label',r.coin.name+', '+pct(p)+', '+state.settings.tf+(events.length?', '+events.map(e=>e.label).join(', '):''));
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
  const c=r.coin,p=c[C.TF[state.settings.tf]],result=eventsFor(c),strength=Math.min(Math.abs(p||0)/12,1);
  ctx.save();ctx.beginPath();ctx.roundRect(x,y,w,h,Math.min(6,w/2,h/2));ctx.clip();
  ctx.fillStyle=p==null?'#24282c':p>=0?`hsl(154 40% ${23+strength*13}%)`:`hsl(354 39% ${25+strength*13}%)`;ctx.fillRect(x,y,w,h);
  if(result?.events.length){ctx.strokeStyle=result.divergence!=null?'#85d8ed':'#f7d877';ctx.lineWidth=4;ctx.strokeRect(x+1,y+1,w-2,h-2);}
  const img=logo(c),badge=result?.events.length&&Math.min(w,h)>76?22:0;
  const content=C.tileContent(w,h-badge,!!img),text=p==null?'N/A':pct(p);
  let fs=content.font;
  ctx.font=`650 ${fs}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;
  const measured=ctx.measureText(text).width;if(measured>w-content.pad*2)fs*=Math.max(0,w-content.pad*2)/measured;
  const block=content.logo+(img?content.gap:0)+fs,top=y+badge+(h-badge-block)/2;
  if(img&&content.logo>8){ctx.save();ctx.beginPath();ctx.arc(x+w/2,top+content.logo/2,content.logo/2,0,Math.PI*2);ctx.clip();ctx.drawImage(img,x+(w-content.logo)/2,top,content.logo,content.logo);ctx.restore();}
  if(fs>=6){ctx.font=`650 ${fs}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;ctx.fillStyle='#fff';ctx.textAlign='center';ctx.textBaseline='top';ctx.fillText(text,x+w/2,top+content.logo+(img?content.gap:0));}
  if(badge){ctx.font='600 10px system-ui';ctx.textAlign='left';ctx.textBaseline='top';ctx.fillStyle=result.divergence!=null?'#b9edfa':'#fff0b3';ctx.fillText(result.divergence!=null?'DIVERGENCE':'ANOMALY',x+10,y+8,w-20);}
  ctx.restore();
}
function showTooltip(r){const t=$('tileTooltip');t.textContent=r.coin.name+' · '+r.coin.symbol.toUpperCase()+' · '+pct(r.coin[C.TF[state.settings.tf]]);t.hidden=false;t.style.left=Math.max(8,Math.min(r.x+8,$('stage').clientWidth-t.offsetWidth-8))+'px';t.style.top=Math.max(8,Math.min(r.y+8,$('stage').clientHeight-t.offsetHeight-8))+'px';}
function hideTooltip(){$('tileTooltip').hidden=true;}
function renderChoosers(){renderChoices('welcomeResults',$('welcomeSearch').value,12,false);renderChoices('manageResults',$('manageSearch').value,manageLimit,$('selectedOnly').checked);renderSelection();}
function renderChoices(target,query,limit,onlySelected){
  const container=$(target),focused=container.contains(document.activeElement)?document.activeElement.dataset.coin:null;
  const q=C.text(query,80).toLowerCase();
  const base=onlySelected?[...state.selected].map(id=>byId(id)||{id,name:id,symbol:'unavailable',current_price:null,has_logo:false}):coins();
  const matching=base.filter(c=>!q||c.name.toLowerCase().includes(q)||c.symbol.toLowerCase().includes(q)||c.id===q);
  container.replaceChildren();
  for(const c of matching.slice(0,limit)){
    const selected=state.selected.has(c.id),row=button('', 'coin-choice',()=>toggleCoin(c.id));row.dataset.coin=c.id;row.setAttribute('aria-pressed',String(selected));
    const identity=el('span','coin-identity');identity.append(el('b','',c.name),el('small','',c.symbol.toUpperCase()));
    const values=el('span','coin-values');values.append(el('span','',price(c.current_price)),el('small',c[C.TF[state.settings.tf]]>=0?'up':'down',pct(c[C.TF[state.settings.tf]])));
    row.append(coinImage(c),identity,values,icon(selected?'check':'plus'));row.setAttribute('aria-label',(selected?'Remove ':'Add ')+c.name);container.append(row);
  }
  if(!matching.length)container.append(el('p','empty-description',state.loading?'Loading coins...':!state.snapshot?'Market data is unavailable.':onlySelected?'No selected coins match.':'No matching coin in the current feed.'));
  if(target==='manageResults')$('moreCoins').hidden=matching.length<=limit;
  if(focused)container.querySelector(`[data-coin="${CSS.escape(focused)}"]`)?.focus({preventScroll:true});
}
function openDialog(id){const d=$(id);d._opener=document.activeElement;if(!d.open)d.showModal();}
function openAsset(id){if(!byId(id))return;hideTooltip();state.activeCoin=id;renderAsset();openDialog('assetDialog');}
function metric(label,value){const n=el('div','detail-metric');n.append(el('span','',label),el('b','',value));return n;}
function renderAsset(){
  const restoreFocus=$('assetContent').contains(document.activeElement)?document.activeElement.id:null;
  const c=byId(state.activeCoin);if(!c){$('assetContent').replaceChildren(el('p','', 'This asset is no longer in the current snapshot.'));return;}
  const identity=$('assetIdentity');identity.replaceChildren(coinImage(c));const name=el('div');name.append(el('h2','',c.name),el('span','muted',c.symbol.toUpperCase()));name.querySelector('h2').id='assetTitle';identity.append(name);
  const body=$('assetContent');body.replaceChildren();
  const head=el('div','asset-price');head.append(el('b','',price(c.current_price)),el('span',c[C.TF[state.settings.tf]]>=0?'up':'down',pct(c[C.TF[state.settings.tf]])+' · '+state.settings.tf.toUpperCase()));body.append(head);
  const fav=button(state.selected.has(c.id)?'Remove from watchlist':'Add to watchlist','secondary',()=>toggleCoin(c.id));fav.id='assetFavorite';fav.prepend(icon('star'));body.append(fav);
  body.append(el('p','detail-date',(c.last_updated?'Price observed '+date(c.last_updated):'Price observation time unavailable')+' · snapshot collected '+date(state.snapshot.snapshot)));
  if(c.spark.length>1){const chart=el('canvas','spark');chart.setAttribute('role','img');chart.setAttribute('aria-label','7-day price history');body.append(chart,el('p','detail-date','7-day price history · CoinGecko'));requestAnimationFrame(()=>drawSpark(chart,c.spark));}
  const performance=el('div','detail-grid');for(const tf of Object.keys(C.TF))performance.append(metric(tf.toUpperCase(),pct(c[C.TF[tf]])));body.append(performance);
  const result=eventsFor(c),section=el('section','detail-signals');section.append(el('h3','', 'Signals'));
  if(!result?.available)section.append(el('p','',result?.reason||'Signals unavailable'));
  else if(!result.events.length)section.append(el('p','', 'No thresholds crossed for this asset.'));
  else for(const event of result.events){const item=el('div','signal-explanation');item.append(el('h4','',event.label));
    const explain=event.kind==='price'?`The ${state.settings.tf.toUpperCase()} return is ${Math.abs(result.priceZ).toFixed(2)} standard deviations ${result.priceZ>0?'above':'below'} the reference mean.`:event.kind==='activity'?`Log-transformed 24H volume / market cap is ${result.activityZ.toFixed(2)} standard deviations above the reference mean.`:`Price z-score ${result.priceZ.toFixed(2)}; activity z-score ${result.activityZ.toFixed(2)}. Absolute gap ${Math.abs(result.divergence).toFixed(2)}, above the 1.2 threshold.`;
    item.append(el('p','',explain));section.append(item);
  }
  section.append(el('p','detail-date',`${state.analysis.price.n} reference assets · CoinGecko · ${date(state.snapshot.snapshot)}`),el('p','detail-date','Cross-sectional comparison. Not evidence of buying, selling or future returns.'));
  const method=button('Methodology','text-button',()=>openDialog('methodDialog'));method.id='assetMethod';section.append(method);body.append(section);
  const social=C.sourceState(state.snapshot,'lunarcrush');
  body.append(el('h3','detail-subtitle','Social context'));
  body.append(el('p','muted',social.usable&&c.galaxy_score!==null?'Galaxy Score '+c.galaxy_score+'/100'+(c.sentiment!==null?' · sentiment '+c.sentiment+'%':'')+' · LunarCrush, '+date(social.stamp)+'. Symbol-based match; indicative only.':'LunarCrush data unavailable for this asset.'));
  const metrics=el('div','detail-grid');metrics.append(metric('Market cap',big(c.market_cap)),metric('24H volume',big(c.total_volume)),metric('All-time high',price(c.ath)),metric('Circulating supply',c.circulating_supply==null?'Unavailable':new Intl.NumberFormat('en-US',{notation:'compact'}).format(c.circulating_supply)));body.append(metrics);
  const link=el('a','external-link','View on CoinGecko');link.id='assetExternalLink';link.href='https://www.coingecko.com/en/coins/'+encodeURIComponent(c.id);link.target='_blank';link.rel='noopener noreferrer';link.append(icon('external-link'));body.append(link);
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
  file.text().then(raw=>{pendingImport=C.importWatchlist(raw);$('importSummary').textContent=pendingImport.coins.length+' coins in this file. Display preferences will also be restored.';updateImportPreview();openDialog('importDialog');}).catch(e=>toast(e.message)).finally(()=>$('importFile').value='');
}
function updateImportPreview(){
  if(!pendingImport)return;
  try{const ids=C.mergeWatchlist([...state.selected],pendingImport.coins,document.querySelector('[name="importMode"]:checked').value==='replace');const unknown=ids.filter(id=>!byId(id)).length;$('importWarning').textContent=ids.length+' coins after import'+(unknown?' · '+unknown+' currently unavailable; identifiers will be kept.':'.');$('confirmImport').disabled=false;}catch(e){$('importWarning').textContent=e.message;$('confirmImport').disabled=true;}
}
document.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',()=>b.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(d=>{d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();}});d.addEventListener('close',()=>{if(d.id==='assetDialog')state.activeCoin=null;const opener=d._opener;if(opener?.isConnected)opener.focus();else if(opener?.id)$(opener.id)?.focus();else if(opener?.dataset.tile)$('tileButtons').querySelector(`[data-tile="${CSS.escape(opener.dataset.tile)}"]`)?.focus();else if(opener?.dataset.signal)$('signalList').querySelector(`[data-signal="${CSS.escape(opener.dataset.signal)}"]`)?.focus();});});
$('manageBtn').addEventListener('click',()=>{manageLimit=80;renderChoosers();openDialog('manageDialog');$('manageSearch').focus();});
$('settingsBtn').addEventListener('click',()=>openDialog('settingsDialog'));
$('methodBtn').addEventListener('click',()=>openDialog('methodDialog'));
$('finishWelcome').addEventListener('click',()=>{state.onboarding=false;state.settings.filter='all';save();render();$('manageBtn').focus();});
$('welcomeSearch').addEventListener('input',renderChoosers);$('manageSearch').addEventListener('input',()=>{manageLimit=80;renderChoosers();});$('selectedOnly').addEventListener('change',renderChoosers);
$('moreCoins').addEventListener('click',()=>{manageLimit+=80;renderChoosers();});
document.querySelectorAll('[data-tf]').forEach(b=>b.addEventListener('click',()=>changeSetting('tf',b.dataset.tf)));
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{state.view=b.dataset.view;state.onboarding=state.view==='fav'&&!state.selected.size;render();}));
$('filterSelect').addEventListener('change',e=>changeSetting('filter',e.target.value));$('sizeSelect').addEventListener('change',e=>changeSetting('metric',e.target.value));
$('resetFilter').addEventListener('click',()=>changeSetting('filter','all'));
$('signalsToggle').addEventListener('click',()=>changeSetting('signalsOpen',!state.settings.signalsOpen));$('closeSignals').addEventListener('click',()=>{changeSetting('signalsOpen',false);$('signalsToggle').focus();});
for(const id of ['homeImport','importBtn'])$(id).addEventListener('click',()=>$('importFile').click());
$('importFile').addEventListener('change',prepareImport);document.querySelectorAll('[name="importMode"]').forEach(n=>n.addEventListener('change',updateImportPreview));
$('confirmImport').addEventListener('click',()=>{try{state.selected=new Set(C.mergeWatchlist([...state.selected],pendingImport.coins,document.querySelector('[name="importMode"]:checked').value==='replace'));state.settings=pendingImport.settings;state.onboarding=state.selected.size===0;save();$('importDialog').close();if($('settingsDialog').open)$('settingsDialog').close();pendingImport=null;render();renderChoosers();toast('Watchlist imported.');}catch(e){toast(e.message);}});
$('exportBtn').addEventListener('click',()=>{const data={version:1,coins:[...state.selected],settings:state.settings};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=el('a');a.href=url;a.download='orbit2-watchlist.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$('fullscreenBtn').addEventListener('click',async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else if(document.documentElement.requestFullscreen)await document.documentElement.requestFullscreen();else toast('Full screen is not supported by this browser.');}catch{toast('Full screen could not be opened.');}});
document.addEventListener('fullscreenchange',()=>{const active=!!document.fullscreenElement,b=$('fullscreenBtn');b.title=active?'Exit full screen':'Full screen';b.setAttribute('aria-label',b.title);b.replaceChildren(icon(active?'minimize':'maximize'));drawMap();});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
window.addEventListener('storage',e=>{if(e.key===FAV_KEY){const v=readStorage(FAV_KEY,[]);if(Array.isArray(v))state.selected=new Set(v.filter(id=>typeof id==='string'&&C.ID.test(id)).slice(0,50));render();renderChoosers();}});
new ResizeObserver(drawMap).observe($('stage'));
setInterval(()=>{if(document.hidden)return;render();if($('assetDialog').open)renderAsset();},15000);
render();renderChoosers();refresh();
