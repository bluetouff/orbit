"use strict";
const TF={'1h':'price_change_percentage_1h_in_currency','24h':'price_change_percentage_24h_in_currency',
  '7d':'price_change_percentage_7d_in_currency','30d':'price_change_percentage_30d_in_currency'};
const state={tf:'24h',metric:'perf',filter:'all',lens:'perf',demo:false,universe:[],byId:new Map(),selected:new Set(),view:'fav',
  global:null,macro:{dxy:104.2,us10y:4.32,proxy:true},anomCount:0,divCount:0,accumCount:0,exhaustCount:0,regime:{label:'NEUTRAL',score:0},
  social:{},macroLive:null,snapshot:null,snapshotMs:null,providerStatus:null};

// --- favorites: capped, persisted client-side (localStorage). No account, no server. ---
const MAX_FAV=50, TOP_N=100, FAV_KEY='orbit.favs.v1';
function loadFavs(){
  try{
    const raw=localStorage.getItem(FAV_KEY); if(!raw)return [];
    const a=JSON.parse(raw); if(!Array.isArray(a))return [];
    // defensive: ids only, sane charset/length, hard cap
    return a.filter(x=>typeof x==='string'&&/^[a-z0-9][a-z0-9._-]{0,79}$/i.test(x)).slice(0,MAX_FAV);
  }catch(e){return [];}
}
function saveFavs(){
  try{localStorage.setItem(FAV_KEY,JSON.stringify([...state.selected].slice(0,MAX_FAV)));}catch(e){}
}
function favFull(){return state.selected.size>=MAX_FAV;}
function updateFavUI(){
  const n=state.selected.size;
  const b=document.getElementById('selBadge'); if(b)b.textContent=n;
  const fc=document.getElementById('favCount'); if(fc)fc.textContent=n;
}
function toggleFav(id){
  if(state.selected.has(id)){state.selected.delete(id);}
  else{ if(favFull()){showToast(`Maximum ${MAX_FAV} favorites`);return false;} state.selected.add(id); }
  saveFavs(); updateFavUI(); return true;
}
let _toastT=null;
function showToast(msg){
  const t=document.getElementById('toast'); if(!t)return;
  t.textContent=msg; t.classList.add('show');
  clearTimeout(_toastT); _toastT=setTimeout(()=>t.classList.remove('show'),1700);
}
function setView(v){
  if(state.view===v)return; state.view=v;
  document.querySelectorAll('#viewSeg button').forEach(b=>b.classList.toggle('on',b.dataset.v===v));
  if(v==='top')closeSheet();
  layout();renderStrip();
}

// Snapshot mode: one same-origin static file, built server-side. Zero third-party calls.
const DATA_URL='./data.json', LOGO_BASE='./logos/';
const EMPTY_IMG='data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
const TILE_FONT="'DIN Alternate','Aptos Display','SF Pro Display',system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI Variable Display','Segoe UI',Roboto,Helvetica,Arial,sans-serif";
const TILE_NUM_FONT="'SF Mono',ui-monospace,'IBM Plex Mono',Menlo,Consolas,monospace";
function srcLabel(){return 'snapshot';}
function logoSrc(c){return c&&c.id&&c.has_logo===true?LOGO_BASE+encodeURIComponent(c.id)+'.png':EMPTY_IMG;}
// Escape any provider-supplied string before putting it in innerHTML.
// Coin name/symbol/id come from CoinGecko and are attacker-controllable for
// low-cap tokens, so they are untrusted.
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
// Broken logos: capture-phase listener (error doesn't bubble) instead of inline onerror.
document.addEventListener('error',e=>{const t=e.target;if(t&&t.tagName==='IMG')t.style.visibility='hidden';},true);

const fmtPct=v=>(v==null?'—':(v>=0?'+':'')+v.toFixed(Math.abs(v)>=10?1:2)+'%');
function fmtAge(ms){
  if(ms==null||!Number.isFinite(ms))return 'unknown age';
  const mins=Math.max(0,Math.floor(ms/60000));
  if(mins<1)return 'under 1 min';
  if(mins<60)return mins+' min';
  const h=Math.floor(mins/60),m=mins%60;
  return h+'h'+(m?(' '+m+'m'):'');
}
function snapshotFreshness(){
  if(state.demo)return {label:'demo',cls:'demo',age:null};
  const age=state.snapshotMs?Date.now()-state.snapshotMs:null;
  const stale=age==null||age>3*60*1000;
  return {label:stale?'stale':'fresh',cls:stale?'stale':'fresh',age};
}
function sourceSummary(){
  if(state.demo)return 'demo sources';
  const s=state.providerStatus||{};
  const social=(s.lunarcrush&&s.lunarcrush.ok)||Object.keys(state.social).length?'LC ticker':'activity proxy';
  const macro=(s.fred&&s.fred.ok)||state.macroLive?'FRED':'macro proxy';
  return 'CG · '+social+' · '+macro;
}
function updateUpdated(){
  const u=document.getElementById('updated');if(!u)return;
  const f=snapshotFreshness();
  u.textContent=f.label+(f.age==null?'':' · '+fmtAge(f.age));
  u.classList.remove('fresh','stale','demo');u.classList.add(f.cls);
}
const fmtBig=v=>{if(v==null)return'—';const a=Math.abs(v);
  if(a>=1e12)return'$'+(v/1e12).toFixed(2)+'T';if(a>=1e9)return'$'+(v/1e9).toFixed(2)+'B';
  if(a>=1e6)return'$'+(v/1e6).toFixed(2)+'M';if(a>=1e3)return'$'+(v/1e3).toFixed(1)+'K';return'$'+v.toFixed(0);};
const fmtPrice=v=>{if(v==null)return'—';if(v>=1000)return'$'+v.toLocaleString('en-US',{maximumFractionDigits:0});
  if(v>=1)return'$'+v.toLocaleString('en-US',{maximumFractionDigits:2});if(v>=0.01)return'$'+v.toFixed(4);return'$'+v.toPrecision(3);};

function perfColor(pct,a=1){if(pct==null)return`rgba(90,98,110,${a})`;
  const hue=pct>=0?145:5,m=Math.min(Math.abs(pct)/12,1),sat=42+m*40,lig=20+m*22;return`hsla(${hue},${sat}%,${lig}%,${a})`;}
const perfClass=pct=>pct==null?'perf-flat':(pct>=0?'perf-up':'perf-down');
function socialScore(c){
  const s=socialOf(c);
  if(s&&s.galaxy_score!=null)return Math.max(0,Math.min(1,s.galaxy_score/100));
  if(!c.market_cap||!c.total_volume)return 0;
  return Math.max(0,Math.min(1,Math.log10(1+(c.total_volume/c.market_cap)*40)/1.7));
}

async function getJSON(url){const r=await fetch(url,{headers:{accept:'application/json'},cache:'default'});if(!r.ok)throw new Error('http '+r.status);return r.json();}
async function loadData(first){
  try{
    const d=await getJSON(DATA_URL);
    if(!d||!Array.isArray(d.coins)||!d.coins.length)throw new Error('empty');
    d.coins.forEach(c=>{ if(c.spark)c._spark=c.spark; });
    state.universe=d.coins; state.byId=new Map(d.coins.map(c=>[c.id,c]));
    state.global=d.global||null;
    state.macroLive=(d.macro&&d.macro.us10y)?d.macro:null;
    state.snapshot=d.snapshot||null; state.snapshotMs=state.snapshot?Date.parse(state.snapshot):null;
    state.providerStatus=d.status||null;
    state.social={}; d.coins.forEach(c=>{ if(c.galaxy_score!=null)
      state.social[(c.symbol||'').toUpperCase()]={galaxy_score:c.galaxy_score,sentiment:c.sentiment,social_dominance:c.social_dominance,source:c.social_source}; });
    state.demo=false; document.getElementById('demoflag').style.display='none';
    document.getElementById('pickUniv').textContent='universe: '+d.coins.length;
    updateUpdated();
  }catch(e){
    if(first){ state.demo=true; document.getElementById('demoflag').style.display='block';
      state.snapshot=null; state.snapshotMs=null; state.providerStatus=null; updateUpdated();
      state.universe=DEMO; state.byId=new Map(DEMO.map(c=>[c.id,c])); state.global=DEMO_GLOBAL;
      document.getElementById('pickUniv').textContent='universe: '+DEMO.length; }
  }
}
function socialOf(c){return c&&c.symbol?state.social[c.symbol.toUpperCase()]:null;}
function zstats(a){const n=a.length;if(n<2)return{m:0,s:0};const m=a.reduce((x,y)=>x+y,0)/n;
  const v=a.reduce((x,y)=>x+(y-m)*(y-m),0)/n;return{m,s:Math.sqrt(v)};}
function computeSignals(){
  const coins=displaySource();
  state.anomCount=0;state.divCount=0;state.accumCount=0;state.exhaustCount=0;
  if(coins.length<4){coins.forEach(c=>{c._anom=null;c._div=null;c._signal=0;});computeRegime(coins);return;}
  const tfk=TF[state.tf];
  // social axis: real Galaxy Score if enough coverage, else turnover proxy
  const gal=coins.map(c=>{const s=socialOf(c);return s&&s.galaxy_score!=null?s.galaxy_score:null;});
  const useGalaxy=gal.filter(v=>v!=null).length>=Math.max(3,Math.ceil(coins.length*0.5));
  state._socialMode=useGalaxy?'galaxy':'proxy';
  const moves=coins.map(c=>c[tfk]||0);
  const act=coins.map((c,i)=>useGalaxy?gal[i]:Math.log10(1+((c.total_volume||0)/(c.market_cap||1))*1000));
  const pm=zstats(moves),am=zstats(act.filter(v=>v!=null));
  coins.forEach((c,i)=>{
    const pz=pm.s?(moves[i]-pm.m)/pm.s:0;
    const a=act[i],az=(a!=null&&am.s)?(a-am.m)/am.s:null;
    c._pz=pz;c._tz=az==null?0:az;
    const priceAnom=Math.abs(pz)>2, actAnom=(az!=null&&az>2);
    c._anom=(priceAnom||actAnom)?{price:priceAnom,vol:actAnom,pz,tz:az,score:Math.max(Math.abs(pz),az||0)}:null;
    if(c._anom)state.anomCount++;
    if(az==null){c._div=null;return;}
    const d=pz-az;                                  // price vs social/activity
    c._div=d>1.2?{kind:'exhaust',score:d}:d<-1.2?{kind:'accum',score:d}:null;
    if(c._div){state.divCount++;if(c._div.kind==='accum')state.accumCount++;else state.exhaustCount++;}
    c._signal=Math.max(c._anom?c._anom.score:0,c._div?Math.abs(c._div.score):0);
  });
  computeRegime(coins);
}
function computeRegime(coins){
  const g=state.global;
  const breadth=coins.length?coins.filter(c=>(c.price_change_percentage_24h_in_currency||0)>0).length/coins.length:0.5;
  const capChg=g?(g.market_cap_change_percentage_24h_usd||0):0;
  let score=0.55*Math.max(-1,Math.min(1,capChg/3))+0.30*((breadth-0.5)*2);
  // real macro nudge: rising USD and rising yields pressure risk assets
  const m=state.macroLive;
  if(m){
    const u=m.usd&&m.usd.change, y=m.us10y&&m.us10y.change;
    if(u!=null)score-=Math.max(-1,Math.min(1,u/0.5))*0.075;
    if(y!=null)score-=Math.max(-1,Math.min(1,y/0.1))*0.075;
  }
  state.regime={label:score>0.22?'RISK-ON':score<-0.22?'RISK-OFF':'NEUTRAL',score,breadth};
  const tint=document.getElementById('tint');
  if(tint){const c=score>0.22?'46,170,110':score<-0.22?'210,70,80':'90,100,115';
    tint.style.background=`radial-gradient(120% 70% at 50% -10%,rgba(${c},${0.10+Math.min(Math.abs(score),1)*0.10}),transparent 60%)`;}
}
const REFRESH_MS=30000, REFRESH_JITTER_MS=15000; // crypto markets ~30 s; jitter avoids herd refreshes
let _busy=false;
async function refreshData(){
  if(state.demo||_busy||document.visibilityState==='hidden')return; _busy=true;
  try{
    await loadData(false);
    updateUpdated();
    layout();renderStrip();
  }finally{_busy=false;}
}
function scheduleRefresh(){
  setTimeout(async()=>{await refreshData();scheduleRefresh();},REFRESH_MS+Math.random()*REFRESH_JITTER_MS);
}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshData();});

const cv=document.getElementById('map'),ctx=cv.getContext('2d');
let W=0,H=0,DPR=1,tiles=new Map(),raf=null;
function resize(){const r=cv.getBoundingClientRect();DPR=Math.min(window.devicePixelRatio||1,2);
  W=r.width;H=r.height;cv.width=W*DPR;cv.height=H*DPR;ctx.setTransform(DPR,0,0,DPR,0,0);}
window.addEventListener('resize',()=>{resize();layout();});

function displaySource(){
  return state.view==='fav'
    ? [...state.selected].map(id=>state.byId.get(id)).filter(Boolean)
    : state.universe.slice(0,TOP_N);
}
function selectedCoins(){let list=displaySource();
  if(state.filter==='gainers')list=list.filter(c=>(c[TF[state.tf]]||0)>0);
  else if(state.filter==='losers')list=list.filter(c=>(c[TF[state.tf]]||0)<0);
  else if(state.filter==='anom')list=list.filter(c=>c._anom);
  else if(state.filter==='div')list=list.filter(c=>c._div);return list;}
function squarify(items,rect){
  const out=[];const total=items.reduce((s,i)=>s+i.value,0);if(total<=0)return out;
  const scale=(rect.w*rect.h)/total;let rem=items.map(i=>({...i,area:i.value*scale}));
  let x=rect.x,y=rect.y,w=rect.w,h=rect.h;
  const worst=(row,side)=>{const s=row.reduce((a,r)=>a+r.area,0),mx=Math.max(...row.map(r=>r.area)),mn=Math.min(...row.map(r=>r.area));return Math.max((side*side*mx)/(s*s),(s*s)/(side*side*mn));};
  while(rem.length){const side=Math.min(w,h);let row=[];
    while(rem.length){const test=row.concat([rem[0]]);if(row.length===0||worst(test,side)<=worst(row,side))row.push(rem.shift());else break;}
    const s=row.reduce((a,r)=>a+r.area,0);
    if(w<=h){const rh=s/w;let ox=x;for(const it of row){const iw=it.area/rh;out.push({...it,x:ox,y:y,w:iw,h:rh});ox+=iw;}y+=rh;h-=rh;}
    else{const rw=s/h;let oy=y;for(const it of row){const ih=it.area/rw;out.push({...it,x:x,y:oy,w:rw,h:ih});oy+=ih;}x+=rw;w-=rw;}}
  return out;}
function layout(){
  computeSignals();
  const list=selectedCoins();
  const showEmpty=state.view==='fav'&&state.selected.size===0;
  document.getElementById('empty').style.display=showEmpty?'flex':'none';
  document.getElementById('shell').classList.toggle('is-empty',showEmpty);
  if(!list.length){tiles.clear();return;}
  let maxAbs=0;
  if(state.metric==='perf'){for(const c of list){const p=Math.abs(c[TF[state.tf]]||0);if(p>maxAbs)maxAbs=p;}if(maxAbs<=0)maxAbs=1;}
  const items=list.map(c=>{
    let value;
    if(state.metric==='perf'){const p=Math.abs(c[TF[state.tf]]||0);value=0.12+0.88*(p/maxAbs);}
    else value=Math.max(1,c[state.metric]||1);
    return {id:c.id,coin:c,value};
  }).sort((a,b)=>b.value-a.value);
  const rects=squarify(items,{x:0,y:0,w:W,h:H});const ids=new Set(rects.map(r=>r.id));
  tiles.forEach((_,id)=>{if(!ids.has(id))tiles.delete(id);});
  for(const r of rects){let t=tiles.get(r.id);
    if(!t){t={x:r.x,y:r.y,w:r.w,h:r.h,coin:r.coin};tiles.set(r.id,t);}
    t.coin=r.coin;t.dead=false;t.x=r.x;t.y=r.y;t.w=r.w;t.h=r.h;}
}
function roundRect(x,y,w,h,r){ctx.beginPath();if(w<=0||h<=0)return;r=Math.max(0,Math.min(r,w/2,h/2));
  ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath();}
function divColor(kind,a=1){return kind==='accum'?`rgba(86,200,232,${a})`:`rgba(232,176,75,${a})`;}
function fillTileText(text,x,y){
  ctx.save();
  ctx.shadowColor='rgba(0,0,0,.28)';
  ctx.shadowBlur=2;
  ctx.shadowOffsetY=1;
  ctx.fillText(text,x,y);
  ctx.restore();
}
function drawBadge(x,y,label,bg,fg='#080a0d'){
  ctx.font="800 9px ui-monospace,'IBM Plex Mono',Menlo,Consolas,monospace";
  const tw=ctx.measureText(label).width, bw=tw+10, bh=17;
  ctx.fillStyle=bg;roundRect(x,y,bw,bh,6);ctx.fill();
  ctx.fillStyle=fg;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(label,x+bw/2,y+bh/2+0.5);
}
const logoCache=new Map();
function getLogo(c){
  if(!c||!c.id||c.has_logo!==true)return null;
  let e=logoCache.get(c.id);
  if(e)return e.ok?e.img:null;
  const img=new Image();e={img,ok:false};
  img.onload=()=>{e.ok=true;};img.onerror=()=>{e.ok=false;};
  img.src=logoSrc(c);logoCache.set(c.id,e);return null;
}
function draw(){
  const now=performance.now();
  ctx.clearRect(0,0,W,H);const g=2;
  for(const [id,t] of tiles){
    if(t.dead){tiles.delete(id);continue;}
    if(t.w<1||t.h<1)continue;
    const c=t.coin,pct=c[TF[state.tf]];
    const x=t.x+g,y=t.y+g,w=Math.max(0,t.w-g*2),hh=Math.max(0,t.h-g*2);
    if(w<1||hh<1)continue;
    const rad=Math.min(9,w*0.16,hh*0.16);
    const grad=ctx.createLinearGradient(x,y,x,y+hh);grad.addColorStop(0,perfColor(pct,0.95));grad.addColorStop(1,perfColor(pct,0.72));
    ctx.fillStyle=grad;roundRect(x,y,w,hh,rad);ctx.fill();
    ctx.lineWidth=1;ctx.strokeStyle=perfColor(pct,1);ctx.stroke();
    const ss=socialScore(c);
    if(ss>0.05&&w>26){ctx.fillStyle=`rgba(232,176,75,${0.2+ss*0.6})`;roundRect(x+4,y+hh-4,(w-8)*ss,2.5,1.2);ctx.fill();}
    if(t.pulse>0){ctx.strokeStyle=`rgba(232,176,75,${t.pulse})`;ctx.lineWidth=2;roundRect(x,y,w,hh,rad);ctx.stroke();t.pulse-=0.04;}
    const m=Math.min(w,hh);
    const cx2=x+w/2,cy2=y+hh/2;
    if(m>26){
      const sym=c.symbol.toUpperCase();
      let fs=Math.min(w*0.28,hh*0.33,29);
      fs=Math.min(fs,w*0.84/Math.max(1,sym.length)/0.56);   // fit width
      fs=Math.max(10,fs);
      const img=getLogo(c);ctx.textAlign='center';
      if(img&&m>44){
        const ls=Math.max(18,Math.min(m*0.32,42)),pf=fs*0.92;
        const showPct=hh>ls+fs*2.3+12;
        const blockH=ls+6+fs+(showPct?pf+3:0),top=cy2-blockH/2;
        try{ctx.drawImage(img,cx2-ls/2,top,ls,ls);}catch(_){}
        ctx.textBaseline='top';
        ctx.fillStyle='rgba(255,255,255,.98)';ctx.font=`720 ${fs}px ${TILE_FONT}`;
        fillTileText(sym,cx2,top+ls+6);
        if(showPct){ctx.fillStyle='rgba(255,255,255,.92)';ctx.font=`650 ${pf}px ${TILE_NUM_FONT}`;ctx.fillText(fmtPct(pct),cx2,top+ls+6+fs+3);}
      }else{
        const showPct=hh>fs*2.2+8;
        ctx.textBaseline='middle';
        ctx.fillStyle='rgba(255,255,255,.98)';ctx.font=`720 ${fs}px ${TILE_FONT}`;
        fillTileText(sym,cx2,cy2-(showPct?fs*0.5:0));
        if(showPct){ctx.fillStyle='rgba(255,255,255,.92)';ctx.font=`650 ${fs*0.80}px ${TILE_NUM_FONT}`;ctx.fillText(fmtPct(pct),cx2,cy2+fs*0.62);}
      }}
    else if(m>13){ctx.fillStyle='rgba(255,255,255,.9)';ctx.textAlign='center';ctx.textBaseline='middle';
      ctx.font=`720 ${Math.max(8,m*0.46)}px ${TILE_FONT}`;fillTileText(c.symbol.toUpperCase().slice(0,4),x+w/2,y+hh/2);}
    if(c._div){
      const col=divColor(c._div.kind), soft=divColor(c._div.kind,.18);
      ctx.fillStyle=soft;roundRect(x+1,y+1,w-2,Math.max(5,Math.min(10,hh*.12)),Math.min(rad,6));ctx.fill();
      ctx.strokeStyle=col;ctx.lineWidth=m>38?3:2;roundRect(x+1.5,y+1.5,w-3,hh-3,rad);ctx.stroke();
      ctx.fillStyle=col;roundRect(x+4,y+4,Math.max(4,Math.min(6,w*.08)),Math.max(16,Math.min(28,hh*.42)),3);ctx.fill();
      if(m>34)drawBadge(x+8,y+6,c._div.kind==='accum'?'ACC':'EXH',col);
      else if(m>22){ctx.fillStyle=col;ctx.font=`900 ${Math.min(m*0.45,15)}px ui-monospace,'IBM Plex Mono',Menlo,Consolas,monospace`;ctx.textAlign='left';ctx.textBaseline='top';ctx.fillText(c._div.kind==='accum'?'A':'E',x+5,y+4);}
    }
    if(c._anom){
      const pulse=0.42+0.42*(Math.sin(now/320)+1)/2;
      ctx.strokeStyle=`rgba(255,255,255,${pulse})`;ctx.lineWidth=m>36?3:2;roundRect(x+2,y+2,w-4,hh-4,rad);ctx.stroke();
      ctx.strokeStyle=`rgba(232,176,75,${0.35+pulse*0.45})`;ctx.lineWidth=1.5;roundRect(x+5,y+5,w-10,hh-10,Math.max(2,rad-2));ctx.stroke();
      if(m>34)drawBadge(x+w-Math.min(37,w*.45)-5,y+6,'2σ',`rgba(255,255,255,${0.88+pulse*.12})`);
      else if(m>22){ctx.fillStyle=`rgba(255,255,255,${0.72+pulse*.28})`;ctx.font=`900 ${Math.min(m*0.42,14)}px ui-monospace,'IBM Plex Mono',Menlo,Consolas,monospace`;ctx.textAlign='right';ctx.textBaseline='top';ctx.fillText('!',x+w-5,y+4);}
    }
  }
  raf=requestAnimationFrame(draw);
}

function tileAt(px,py){for(const [id,t] of tiles){if(t.dead)continue;if(px>=t.x&&px<=t.x+t.w&&py>=t.y&&py<=t.y+t.h)return t;}return null;}
let pdn=null;
function lxy(e){const r=cv.getBoundingClientRect();return[e.clientX-r.left,e.clientY-r.top];}
cv.addEventListener('pointerdown',e=>{const[x,y]=lxy(e);pdn={x,y,t:Date.now()};});
cv.addEventListener('pointerup',e=>{if(!pdn)return;const[x,y]=lxy(e);
  if(Math.hypot(x-pdn.x,y-pdn.y)<8&&Date.now()-pdn.t<300){const t=tileAt(x,y);if(t)openSheet(t.coin);}pdn=null;});

const sheet=document.getElementById('sheet'),scrim=document.getElementById('scrim');
async function openSheet(c){
  const pct=c[TF[state.tf]],ss=socialScore(c),inSel=state.selected.has(c.id);
  const soc=socialOf(c),hasSoc=!!(soc&&soc.galaxy_score!=null);
  const axis=state._socialMode==='galaxy'?'social':'activity';
  const axisObj=state._socialMode==='galaxy'?'social signal':'activity';
  const dv=c._div,an=c._anom;
  const divTxt=dv?(dv.kind==='accum'?`Accumulation - ${axisObj} is outrunning price`:`Exhaustion - price is outrunning ${axisObj}`):'Aligned - no notable divergence';
  const divCol=dv?(dv.kind==='accum'?'hsl(193,72%,64%)':'var(--accent)'):'var(--ink-dim)';
  const divArrow=dv?(dv.kind==='accum'?'↗':'↘'):'≈';
  const anTxt=an?[an.price?'price >2σ':null,an.vol?(state._socialMode==='galaxy'?'social >2σ':'volume >2σ'):null].filter(Boolean).join(' · '):'nothing unusual vs peers';
  const sigKind=an?'anom':(dv?dv.kind:'calm');
  const sigTitle=an?'Active anomaly':(dv?(dv.kind==='accum'?'Possible accumulation':'Possible exhaustion'):'Calm signal');
  const sigBody=[an?anTxt:null,dv?divTxt:null].filter(Boolean).join(' · ')||'No statistical break in the active view.';
  const socTop=hasSoc?'Social (LunarCrush)':'Activity (proxy)';
  const socSrc=hasSoc?'matched by ticker':'volume / cap';
  const socBody=hasSoc
    ?`Galaxy Score ${Number(soc.galaxy_score)||0}/100 · sentiment ${soc.sentiment!=null?(Number(soc.sentiment)||0)+'%':'—'}${soc.social_dominance!=null?' · dominance '+(+soc.social_dominance).toFixed(1)+'%':''}. Provider match by symbol; treat it as an indicative signal.`
    :'Index derived from volume / market cap turnover. No provider social signal is available for this asset in the snapshot.';
  const tfHtml=Object.keys(TF).map(k=>`<div class="cell"><div class="k">${k.toUpperCase()}</div><div class="v ${perfClass(c[TF[k]])}">${fmtPct(c[TF[k]])}</div></div>`).join('');
  sheet.innerHTML=`<div class="grab"></div>
  <div class="s-head"><img class="s-logo" src="${esc(logoSrc(c))}">
    <div class="s-name"><h2>${esc(c.name)} <span class="rank">#${c.market_cap_rank??'—'}</span></h2><div class="sym">${esc(c.symbol)}</div></div>
    <div class="star ${inSel?'on':''}" id="starBtn"><svg viewBox="0 0 24 24"><path d="M12 3l2.6 5.6 6 .8-4.4 4.2 1.1 6L12 17l-5.3 2.6 1.1-6L3.4 9.4l6-.8z"/></svg></div></div>
  <div class="s-price">${fmtPrice(c.current_price)}</div>
  <div class="s-prch ${perfClass(pct)}">${fmtPct(pct)} · ${state.tf.toUpperCase()}</div>
  <canvas class="spark" id="spark"></canvas>
  <div class="tf-row">${tfHtml}</div>
  <div class="grid4">
    <div class="cell"><div class="k">Market cap</div><div class="v">${fmtBig(c.market_cap)}</div></div>
    <div class="cell"><div class="k">Volume 24h</div><div class="v">${fmtBig(c.total_volume)}</div></div>
    <div class="cell"><div class="k">ATH</div><div class="v">${fmtPrice(c.ath)}</div></div>
    <div class="cell"><div class="k">Circ. supply</div><div class="v">${c.circulating_supply?(c.circulating_supply/1e6).toFixed(1)+'M':'—'}</div></div>
  </div>
  <div class="signal-hero ${sigKind}"><div class="top"><span>Signal Orbit</span><b>${sigTitle}</b></div>
    <p>${sigBody}</p></div>
  <div class="social"><div class="top"><span>${socTop}</span><span class="src">${socSrc}</span></div>
    <div class="gauge"><i id="gaugeFill"></i></div>
    <small>${socBody}</small></div>
  <div class="sig"><div class="top"><span>Price / ${axis} divergence</span><span class="zsc">price z ${(c._pz||0).toFixed(1)} · ${axis} z ${(c._tz||0).toFixed(1)}</span></div>
    <div class="sigline" id="divLine"><b>${divArrow}</b> ${divTxt}</div></div>
  <div class="sig"><div class="top"><span>Anomaly scanner</span><span class="zsc">cross-sectional</span></div>
    <div class="sigline" id="anomLine">${an?'⚡ ':''}${anTxt}</div></div>
  <div class="s-links"><a href="https://www.coingecko.com/en/coins/${encodeURIComponent(c.id)}" target="_blank" rel="noopener">CoinGecko ↗</a>
    <a href="https://www.coindesk.com/price/${encodeURIComponent(c.id)}" target="_blank" rel="noopener">CoinDesk ↗</a></div>`;
  // dynamic styling via CSSOM (no inline style attributes -> CSP style-src 'self')
  sheet.querySelector('#gaugeFill').style.width=(ss*100).toFixed(0)+'%';
  sheet.querySelector('#divLine').style.color=divCol;
  sheet.querySelector('#anomLine').style.color=an?'#fff':'var(--ink-dim)';
  scrim.classList.add('show');sheet.classList.add('show');
  document.getElementById('starBtn').onclick=()=>{toggleSel(c.id);document.getElementById('starBtn').classList.toggle('on',state.selected.has(c.id));};
  drawSpark(c);
}
function closeSheet(){scrim.classList.remove('show');sheet.classList.remove('show');}
scrim.addEventListener('click',closeSheet);
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeSheet();picker.classList.remove('show');search.classList.remove('show');}});
function drawSpark(c){const cnv=document.getElementById('spark');if(!cnv)return;
  const sp=c._spark||(c.sparkline_in_7d&&c.sparkline_in_7d.price);if(!sp||sp.length<2)return;
  const dpr=Math.min(window.devicePixelRatio||1,2),w=cnv.clientWidth,h=64;cnv.width=w*dpr;cnv.height=h*dpr;
  const x=cnv.getContext('2d');x.setTransform(dpr,0,0,dpr,0,0);
  const mn=Math.min(...sp),mx=Math.max(...sp),rg=mx-mn||1,up=sp[sp.length-1]>=sp[0];
  const col=up?'hsl(145,58%,55%)':'hsl(5,72%,62%)';
  x.beginPath();sp.forEach((p,i)=>{const px=i/(sp.length-1)*w,py=h-6-((p-mn)/rg)*(h-12);i?x.lineTo(px,py):x.moveTo(px,py);});
  x.lineWidth=1.6;x.strokeStyle=col;x.stroke();x.lineTo(w,h);x.lineTo(0,h);x.closePath();
  const g=x.createLinearGradient(0,0,0,h);g.addColorStop(0,up?'rgba(46,200,140,.18)':'rgba(235,80,90,.18)');g.addColorStop(1,'rgba(0,0,0,0)');x.fillStyle=g;x.fill();}

function toggleSel(id){const ok=toggleFav(id); if(ok){layout();renderStrip();} return ok;}

const seg=document.getElementById('seg'),pill=seg.querySelector('.pill');
function movePill(){const on=seg.querySelector('button.on');if(!on)return;pill.style.width=on.offsetWidth+'px';pill.style.transform=`translateX(${on.offsetLeft-3}px)`;}
seg.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{seg.querySelectorAll('button').forEach(x=>x.classList.remove('on'));b.classList.add('on');state.tf=b.dataset.tf;movePill();layout();renderStrip();}));
const chips=document.getElementById('chips');
chips.querySelectorAll('.chip[data-f]').forEach(c=>c.addEventListener('click',()=>{chips.querySelectorAll('.chip[data-f]').forEach(x=>x.classList.remove('on'));c.classList.add('on');state.filter=c.dataset.f;layout();renderStrip();}));
const sizeBtn=document.getElementById('sizeBtn');
const SIZE_MODES=['perf','market_cap','total_volume'],SIZE_LABEL={perf:'△ perf',market_cap:'⬛ cap',total_volume:'▮ vol'};
sizeBtn.addEventListener('click',()=>{const i=SIZE_MODES.indexOf(state.metric);
  state.metric=SIZE_MODES[(i+1)%SIZE_MODES.length];sizeBtn.textContent=SIZE_LABEL[state.metric];
  sizeBtn.classList.toggle('perf',state.metric==='perf');sizeBtn.classList.toggle('vol',state.metric==='total_volume');layout();});

const picker=document.getElementById('picker'),pickList=document.getElementById('pickList'),pickInput=document.getElementById('pickInput');
const favTog=document.getElementById('favTog'),pickPager=document.getElementById('pickPager');
const PAGE_SIZE=100;
state._page=0; state._favOnly=false;
function openPicker(){
  picker.classList.add('show');pickInput.value='';state._page=0;
  if(!state.selected.size)state._favOnly=false;
  favTog.classList.toggle('on',state._favOnly);
  renderPick('');
}
document.getElementById('pickBtn').addEventListener('click',openPicker);
document.getElementById('emptyPick').addEventListener('click',openPicker);
document.getElementById('pickDone').addEventListener('click',()=>{picker.classList.remove('show');layout();});
pickInput.addEventListener('input',()=>{state._page=0;renderPick(pickInput.value);});
favTog.addEventListener('click',()=>{state._favOnly=!state._favOnly;state._page=0;favTog.classList.toggle('on',state._favOnly);renderPick(pickInput.value);});

function renderPager(pages){
  if(pages<=1){pickPager.innerHTML='';return;}
  let h='<button class="pg nav" data-pg="prev">‹</button>';
  for(let i=0;i<pages;i++)h+=`<button class="pg ${i===state._page?'on':''}" data-pg="${i}">${i+1}</button>`;
  h+='<button class="pg nav" data-pg="next">›</button>';
  pickPager.innerHTML=h;
  pickPager.querySelectorAll('.pg').forEach(b=>b.addEventListener('click',()=>{
    const v=b.dataset.pg;
    if(v==='prev')state._page=Math.max(0,state._page-1);
    else if(v==='next')state._page=Math.min(pages-1,state._page+1);
    else state._page=+v;
    renderPick(pickInput.value);
    pickList.scrollTop=0;
  }));
}

function renderPick(q){
  q=q.trim().toLowerCase();
  const favOnly=state._favOnly;
  let base=favOnly?[...state.selected].map(id=>state.byId.get(id)).filter(Boolean):state.universe;
  let list,paged=false,pages=1;
  if(q){
    list=base.filter(c=>c.name.toLowerCase().includes(q)||c.symbol.toLowerCase().includes(q)).slice(0,200);
  }else if(favOnly){
    list=[...base].sort((a,b)=>(a.market_cap_rank||9999)-(b.market_cap_rank||9999));
  }else{
    // universe is already market-cap-ranked by the builder -> page directly
    pages=Math.max(1,Math.ceil(base.length/PAGE_SIZE));
    state._page=Math.min(state._page,pages-1);
    list=base.slice(state._page*PAGE_SIZE,state._page*PAGE_SIZE+PAGE_SIZE);
    paged=true;
  }
  renderPager(paged?pages:1);
  document.getElementById('pickCount').textContent=state.selected.size+' selected';
  if(!list.length){
    pickList.innerHTML=`<div class="pick-empty">${favOnly?'no favorites selected - turn off favorites to browse the top '+state.universe.length:'nothing found'}</div>`;
    return;
  }
  const rangeNote=paged?`<div class="pick-note">rank ${state._page*PAGE_SIZE+1}-${state._page*PAGE_SIZE+list.length} of ${base.length}</div>`:'';
  pickList.innerHTML=rangeNote+list.map(c=>{const sel=state.selected.has(c.id),pct=c[TF[state.tf]];
    return `<div class="row ${sel?'sel':''}" data-id="${esc(c.id)}"><div class="tick"><svg viewBox="0 0 24 24"><path d="M5 12l5 5 9-10"/></svg></div>
      <img src="${esc(logoSrc(c))}"><div class="nm"><b>${esc(c.name)}</b><span>${esc(c.symbol)} · #${c.market_cap_rank??'—'}</span></div>
      <div class="pr">${fmtPrice(c.current_price)}<small class="${perfClass(pct)}">${fmtPct(pct)}</small></div></div>`;}).join('');
  pickList.querySelectorAll('.row').forEach(r=>r.addEventListener('click',()=>{const id=r.dataset.id;
    const wasSel=state.selected.has(id);
    const ok=toggleFav(id);
    if(!ok)return;                                   // cap reached: no change
    r.classList.toggle('sel',!wasSel);
    if(state._favOnly&&wasSel)renderPick(pickInput.value);
    document.getElementById('pickCount').textContent=state.selected.size+' selected';}));
}

const search=document.getElementById('search'),searchInput=document.getElementById('searchInput'),searchList=document.getElementById('searchList');
document.getElementById('searchBtn').addEventListener('click',()=>{
  if(!state.selected.size){openPicker();return;}
  search.classList.add('show');searchInput.value='';renderSearch('');setTimeout(()=>searchInput.focus(),200);
});
document.getElementById('searchDone').addEventListener('click',()=>search.classList.remove('show'));
picker.addEventListener('click',e=>{if(e.target===picker){picker.classList.remove('show');layout();}});
search.addEventListener('click',e=>{if(e.target===search)search.classList.remove('show');});
searchInput.addEventListener('input',()=>renderSearch(searchInput.value));
function renderSearch(q){q=q.trim().toLowerCase();
  let list=[...state.selected].map(id=>state.byId.get(id)).filter(Boolean);
  if(q)list=list.filter(c=>c.name.toLowerCase().includes(q)||c.symbol.toLowerCase().includes(q));
  searchList.innerHTML=list.map(c=>{const pct=c[TF[state.tf]];
    return `<div class="row" data-id="${esc(c.id)}"><img src="${esc(logoSrc(c))}">
      <div class="nm"><b>${esc(c.name)}</b><span>${esc(c.symbol)}</span></div>
      <div class="pr">${fmtPrice(c.current_price)}<small class="${perfClass(pct)}">${fmtPct(pct)}</small></div></div>`;}).join('')
    ||`<div class="pick-empty">nothing in your list</div>`;
  searchList.querySelectorAll('.row').forEach(r=>r.addEventListener('click',()=>{const c=state.byId.get(r.dataset.id);
    search.classList.remove('show');const t=tiles.get(c.id);if(t)t.pulse=1;setTimeout(()=>openSheet(c),250);}));}

function renderStrip(){
  const g=state.global,r=state.regime;
  const cap=g&&g.total_market_cap?fmtBig(g.total_market_cap.usd):'—';
  const capChg=g?(g.market_cap_change_percentage_24h_usd||0):0;
  const btcD=g&&g.market_cap_percentage?g.market_cap_percentage.btc:null;
  const ethD=g&&g.market_cap_percentage?g.market_cap_percentage.eth:null;
  const rc=r.label==='RISK-ON'?'on':r.label==='RISK-OFF'?'off':'neu';
  const m=state.macroLive;
  let macroHtml;
  if(m){
    const arr=v=>v==null?'':` <i class="${v>=0?'up':'dn'}">${v>=0?'▲':'▼'}${Math.abs(v).toFixed(2)}</i>`;
    macroHtml=
      (m.usd?`<span>USD <b>${(+m.usd.value).toFixed(1)}</b>${arr(m.usd.change)}</span>`:'')+
      (m.us10y?`<span>10Y <b>${(+m.us10y.value).toFixed(2)}%</b>${arr(m.us10y.change)}</span>`:'');
  }else{
    macroHtml=
      `<span class="px">DXY <b>${state.macro.dxy.toFixed(1)}</b><sup>ᵖ</sup></span>`+
      `<span class="px">10Y <b>${state.macro.us10y.toFixed(2)}%</b><sup>ᵖ</sup></span>`;
  }
  document.getElementById('macro').innerHTML=
    `<span class="regime ${rc}">${r.label}</span>`+
    `<span>Cap <b>${cap}</b> <i class="${capChg>=0?'up':'dn'}">${fmtPct(capChg)}</i></span>`+
    `<span>BTC.D <b>${btcD!=null?btcD.toFixed(1)+'%':'—'}</b></span>`+
    `<span>ETH.D <b>${ethD!=null?ethD.toFixed(1)+'%':'—'}</b></span>`+
    macroHtml;
  const sel=displaySource();
  const avg=sel.length?sel.reduce((s,c)=>s+(c[TF[state.tf]]||0),0)/sel.length:null;
  const avgCls=avg==null?'perf-flat':(avg>=0?'up':'dn');
  const fresh=snapshotFreshness();
  const dataAge=state.demo?'demo':fmtAge(fresh.age);
  const divLabel=state.divCount+' div';
  const anomLabel=state.anomCount+' anom';
  const divChip=chips.querySelector('.chip[data-f="div"]');if(divChip)divChip.textContent='Divergences '+state.divCount;
  const anomChipBtn=chips.querySelector('.chip[data-f="anom"]');if(anomChipBtn)anomChipBtn.textContent='Anomalies '+state.anomCount;
  document.getElementById('subline').innerHTML=
    `<span><b>${state.selected.size}</b> watched</span>`+
    `<span class="freshness ${fresh.cls}">data <b>${dataAge}</b></span>`+
    `<span>${esc(sourceSummary())}</span>`+
    `<span class="signal-pill div ${state.filter==='div'?'on':''}" id="divChip">${divLabel} <b>${state.accumCount} acc</b> <b>${state.exhaustCount} exh</b></span>`+
    `<span class="signal-pill anom ${state.filter==='anom'?'on':''}" id="anomChip">${anomLabel}</span>`+
    `<span>avg ${state.tf.toUpperCase()} <b class="${avgCls}">${fmtPct(avg)}</b></span>`+
    `<span class="signal-tip">cross-sectional signals</span>`;
  const dc=document.getElementById('divChip');
  if(dc)dc.onclick=()=>{state.filter=state.filter==='div'?'all':'div';
    chips.querySelectorAll('.chip[data-f]').forEach(x=>x.classList.toggle('on',x.dataset.f===state.filter));
    layout();renderStrip();};
  const ac=document.getElementById('anomChip');
  if(ac)ac.onclick=()=>{state.filter=state.filter==='anom'?'all':'anom';
    chips.querySelectorAll('.chip[data-f]').forEach(x=>x.classList.toggle('on',x.dataset.f===state.filter));
    layout();renderStrip();};
}

async function boot(){
  resize();await loadData(true);
  state.selected=new Set(loadFavs());     // persisted choice, capped & validated
  state.view='fav';
  updateFavUI();
  document.getElementById('viewSeg').querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.dataset.v==='fav'));
  document.getElementById('status').style.display='none';
  layout();renderStrip();movePill();draw();
  updateUpdated();
}
document.querySelectorAll('#viewSeg button').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.v)));
boot();
scheduleRefresh();

function D(id,sym,name,price,mc,vol,c1,c24,c7,c30,rank){return{id,symbol:sym,name,current_price:price,market_cap:mc,total_volume:vol,market_cap_rank:rank,
  image:'',ath:price*1.8,circulating_supply:mc/price,
  price_change_percentage_1h_in_currency:c1,price_change_percentage_24h_in_currency:c24,price_change_percentage_7d_in_currency:c7,price_change_percentage_30d_in_currency:c30};}
const DEMO_GLOBAL={total_market_cap:{usd:3.34e12},total_volume:{usd:1.4e11},market_cap_percentage:{btc:54.2,eth:11.8},market_cap_change_percentage_24h_usd:1.6};
const DEMO=[
  D('bitcoin','btc','Bitcoin',97400,1.92e12,38e9,0.3,2.4,-1.2,8.6,1),D('ethereum','eth','Ethereum',3420,4.1e11,18e9,0.6,3.8,2.1,-4.3,2),
  D('tether','usdt','Tether',1,1.4e11,62e9,0,0.01,-0.02,0.01,3),D('solana','sol','Solana',198,9.3e10,4.2e9,-0.8,6.7,9.4,22.1,4),
  D('binancecoin','bnb','BNB',612,8.8e10,1.9e9,0.2,-1.1,3.3,5.5,5),D('ripple','xrp','XRP',2.31,1.3e11,6.1e9,1.1,12.4,-3.8,41.2,6),
  D('usd-coin','usdc','USDC',1,3.8e10,9e9,0,0,0,0,7),D('cardano','ada','Cardano',0.92,3.2e10,1.1e9,-0.4,-4.2,-7.1,12.8,8),
  D('dogecoin','doge','Dogecoin',0.38,5.5e10,3.4e9,2.1,15.6,-12.3,28.4,9),D('avalanche-2','avax','Avalanche',42,1.6e10,720e6,-1.2,5.1,4.4,-9.2,10),
  D('tron','trx','TRON',0.24,2.1e10,880e6,0.1,1.2,2.8,6.1,11),D('chainlink','link','Chainlink',23.4,1.4e10,650e6,0.9,7.8,11.2,3.4,12),
  D('polkadot','dot','Polkadot',7.8,1.1e10,420e6,-0.6,-2.1,-5.4,-1.2,13),D('the-open-network','ton','Toncoin',5.6,1.4e10,310e6,0.4,3.3,-1.8,14.7,14),
  D('shiba-inu','shib','Shiba Inu',0.000026,1.5e10,890e6,1.8,9.2,-14.1,19.3,15),D('matic-network','matic','Polygon',0.58,5.8e9,340e6,-0.3,-6.7,-9.8,4.2,16),
  D('litecoin','ltc','Litecoin',103,7.7e9,510e6,0.2,2.1,1.4,-3.1,17),D('uniswap','uni','Uniswap',13.2,7.9e9,290e6,1.4,8.9,6.2,-2.8,18),
  D('bitcoin-cash','bch','Bitcoin Cash',478,9.4e9,380e6,-0.5,3.6,-2.2,7.9,19),D('internet-computer','icp','Internet Computer',11.4,5.3e9,160e6,0.7,-3.4,-8.1,2.3,20),
  D('aptos','apt','Aptos',9.1,5.1e9,210e6,-1.1,6.4,13.7,-6.4,21),D('near','near','NEAR Protocol',5.3,6.1e9,330e6,0.5,4.8,7.1,9.8,22),
  D('pepe','pepe','Pepe',0.000018,7.4e9,1.2e9,3.2,21.4,-18.9,52.1,23),D('render-token','render','Render',7.6,3.9e9,140e6,-0.8,-5.1,-11.2,1.7,24),
  D('stellar','xlm','Stellar',0.41,1.2e10,420e6,0.6,4.1,-2.9,18.2,25),D('hedera-hashgraph','hbar','Hedera',0.27,1e10,310e6,-0.4,6.8,9.1,33.4,26),
  D('cosmos','atom','Cosmos',8.4,3.3e9,180e6,-0.7,-3.1,-6.2,-2.1,27),D('filecoin','fil','Filecoin',5.9,3.6e9,220e6,0.3,2.4,-4.8,5.6,28),
  D('crypto-com-chain','cro','Cronos',0.16,4.3e9,90e6,0.2,1.8,3.2,11.4,29),D('mantle','mnt','Mantle',1.1,3.7e9,120e6,-0.5,7.2,14.1,-3.3,30),
  D('arbitrum','arb','Arbitrum',0.92,3.5e9,260e6,1.2,9.4,8.7,-1.9,31),D('vechain','vet','VeChain',0.045,3.6e9,140e6,-0.3,-2.8,-5.1,6.7,32),
  D('optimism','op','Optimism',2.4,3.1e9,210e6,0.8,6.1,10.2,-4.4,33),D('injective-protocol','inj','Injective',28,2.8e9,170e6,-1.4,-6.7,-9.8,2.1,34),
  D('immutable-x','imx','Immutable',1.7,2.9e9,90e6,1.1,8.4,12.6,7.3,35),D('the-graph','grt','The Graph',0.28,2.7e9,110e6,0.4,3.9,-3.4,4.8,36),
  D('lido-dao','ldo','Lido DAO',2.1,1.9e9,130e6,-0.6,-4.1,-7.7,1.2,37),D('grass','grass','Grass',0.48,1.2e9,80e6,2.4,11.8,-15.2,24.6,38),
  D('sui','sui','Sui',3.8,1.1e10,560e6,1.6,9.7,16.4,28.9,39),D('aave','aave','Aave',312,4.7e9,290e6,0.9,5.2,7.8,-2.4,40)
];
