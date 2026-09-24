(function(root, factory) {
  const core = factory();
  if (typeof module === 'object' && module.exports) module.exports = core;
  else root.OrbitCore = core;
})(globalThis, function() {
  'use strict';
  const TF = { '1h':'price_change_percentage_1h_in_currency', '24h':'price_change_percentage_24h_in_currency',
    '7d':'price_change_percentage_7d_in_currency', '30d':'price_change_percentage_30d_in_currency' };
  const ID = /^[a-z0-9][a-z0-9._-]{0,79}$/i;
  const MAX_FAV = 50, MIN_PEERS = 20;
  const DEFAULTS = Object.freeze({tf:'24h',metric:'perf',filter:'all',signalsOpen:true});
  const text = (v, max = 96) => String(v == null ? '' : v).replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0,max);
  function num(v, lo = -Infinity, hi = Infinity) {
    if (!['number','string'].includes(typeof v) || (typeof v === 'string' && !v.trim())) return null;
    const n = Number(v);
    return Number.isFinite(n) && n >= lo && n <= hi ? n : null;
  }
  function time(v) { const n = typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(v) ? Date.parse(v) : NaN; return Number.isFinite(n) ? n : null; }
  const isXstock = c => c?.asset_type==='xstock'||/(?:^kraken-|xstocks?$)/i.test(c?.id||'')||/\bxstocks?\b/i.test(c?.name||'');
  const assetSource = () => 'coingecko_markets';
  function normalizeSnapshot(d) {
    if (!d || !Array.isArray(d.coins)) throw new Error('Invalid snapshot');
    const ids = new Set(), coins = [];
    for (const c of d.coins.slice(0,1250)) {
      if (!c || typeof c !== 'object') continue;
      const id=text(c.id,80), symbol=text(c.symbol,20), name=text(c.name);
      if (!ID.test(id) || !/^[a-z0-9][a-z0-9._-]{0,19}$/i.test(symbol) || !name || ids.has(id)) continue;
      if(c.asset_type!=null&&c.asset_type!=='crypto') continue;
      if(isXstock(c)||c.price_source==='kraken') continue;
      const o={id,symbol,name,has_logo:c.has_logo!==false,asset_type:'crypto'};
      for (const k of ['current_price','market_cap','total_volume','ath','circulating_supply']) o[k]=num(c[k],0);
      if (o.current_price===null||['market_cap','total_volume'].some(k=>o[k]===null)) continue;
      o.price_source='coingecko';
      o.market_cap_rank=num(c.market_cap_rank,1,1000000);
      for (const k of Object.values(TF)) o[k]=num(c[k],-100,100000);
      for (const k of ['galaxy_score','sentiment','social_dominance']) o[k]=num(c[k],0,100);
      o.social_source=text(c.social_source,40);
      o.last_updated=time(c.last_updated)!==null?text(c.last_updated,40):null;
      o.observationInvalid=c.last_updated!=null&&o.last_updated===null;
      o.spark=Array.isArray(c.spark)?c.spark.slice(0,240).map(v=>num(v,0)).filter(v=>v!==null):[];
      ids.add(id);coins.push(o);
    }
    if (!coins.length) throw new Error('No valid market data');
    const status={};
    for (const key of ['coingecko_markets','coingecko_global','lunarcrush','fred']) {
      const s=d.status?.[key];
      if (!s || typeof s!=='object') continue;
      status[key]={ok:s.ok===true,enabled:s.enabled!==false,reused:s.reused===true,
        fetched_at:time(s.fetched_at)!==null?s.fetched_at:null,
        last_success_at:time(s.last_success_at)!==null?s.last_success_at:null,
        retry_at:time(s.retry_at)!==null?s.retry_at:null,
        ttl:num(s.ttl,1,86400),error:text(s.error,60)};
    }
    const macro={};
    for (const key of ['usd','us10y']) {
      const m=d.macro?.[key],value=num(m?.value,-100000,100000);
      if (value!==null) macro[key]={value,change:num(m.change),date:/^\d{4}-\d{2}-\d{2}$/.test(m.date)?m.date:null};
    }
    const g=d.global;
    return {coins,status,macro,snapshot:time(d.snapshot)!==null?d.snapshot:null,
      global:{cap:num(g?.total_market_cap?.usd,0),change:num(g?.market_cap_change_percentage_24h_usd,-100,100),
        btc:num(g?.market_cap_percentage?.btc,0,100)}};
  }
  function sourceState(snapshot,key,now=Date.now()) {
    const s=snapshot?.status?.[key];
    const stamp=s?.last_success_at || (s?.ok===false?null:s?.fetched_at) || (key==='coingecko_markets'&&!s?snapshot?.snapshot:null);
    const ms=time(stamp), age=ms===null?null:now-ms;
    // Crypto retains its strict three-minute freshness boundary.
    const ttl={coingecko_markets:180,coingecko_global:600,lunarcrush:1800,fred:7200}[key];
    let kind='current';
    if (s?.enabled===false) kind='disabled';
    else if (s?.ok===false) kind='unavailable';
    else if (age===null) kind='unknown';
    else if (age < -60000 || age > ttl*1000) kind='stale';
    return {kind,age,stamp,usable:kind==='current',reused:!!s?.reused};
  }
  function stats(values) {
    const n=values.length;
    const mean=n?values.reduce((a,b)=>a+b,0)/n:null;
    const sd=n?Math.sqrt(values.reduce((a,b)=>a+(b-mean)**2,0)/n):null;
    return {n,mean,sd};
  }
  function observation(c,now) {
    if(c.observationInvalid) return 'invalid';
    if(!c.last_updated) return 'unknown';
    const stamp=time(c.last_updated);
    if(stamp===null) return 'invalid';
    return now-stamp>=-60000&&now-stamp<=180000?'current':'stale';
  }
  function quoteState(snapshot,c,now=Date.now()) {
    const source=sourceState(snapshot,assetSource(c),now),observed=observation(c,now);
    const stamp=time(c.last_updated),age=stamp===null?null:now-stamp;
    return {source,observed,kind:observed,age,usable:source.usable&&['current','unknown'].includes(observed)};
  }
  function relativeBitcoin(c,btc,key,current,now) {
    const result={value:null,reason:null,dated:false};
    if(!current) result.reason='Market data is not current';
    else if(!btc) result.reason='Bitcoin is absent from the snapshot';
    else if([c,btc].some(coin=>!['current','unknown'].includes(observation(coin,now)))) result.reason='Asset or Bitcoin observation is invalid or stale';
    else if(!Number.isFinite(c[key])||!Number.isFinite(btc[key])||btc[key]<=-100) result.reason='Comparable returns unavailable';
    else {
      result.dated=[c,btc].every(coin=>observation(coin,now)==='current');
      if(result.dated&&Math.abs(time(c.last_updated)-time(btc.last_updated))>60000) result.reason='Observation times differ by more than one minute';
      else {
        // Relative wealth ratio, not the percentage-point difference of returns.
        const value=100*((100+c[key])/(100+btc[key])-1);
        if(Number.isFinite(value)) result.value=value;
        else result.reason='Comparable returns unavailable';
      }
    }
    return result;
  }
  function analyze(snapshot,tf='24h',now=Date.now()) {
    if(!Object.hasOwn(TF,tf)) tf='24h';
    const coins=snapshot?.coins || [],key=TF[tf]||TF['24h'];
    const current=sourceState(snapshot,'coingecko_markets',now).usable;
    const observed=c=>['current','unknown'].includes(observation(c,now));
    const crypto=coins.filter(c=>!isXstock(c));
    const peers=crypto.filter(c=>observed(c)&&Number.isFinite(c[key]));
    const price=stats(peers.map(c=>c[key]));
    const sorted=peers.map(c=>c[key]).sort((a,b)=>a-b),middle=Math.floor(sorted.length/2);
    const market={available:current&&peers.length>=MIN_PEERS,n:peers.length,total:crypto.length,
      dated:peers.filter(c=>observation(c,now)==='current').length,median:null,up:null,down:null,flat:null};
    if(market.available) {
      market.median=sorted.length%2?sorted[middle]:(sorted[middle-1]+sorted[middle])/2;
      market.up=sorted.filter(v=>v>0).length;market.down=sorted.filter(v=>v<0).length;market.flat=sorted.length-market.up-market.down;
    }
    const btc=coins.find(c=>c.id==='bitcoin');
    const turnover=c=>{const value=c.market_cap>0&&Number.isFinite(c.total_volume)?Math.log10(1+c.total_volume/c.market_cap*1000):NaN;return Number.isFinite(value)?value:null;};
    const activityPeers=peers.filter(c=>turnover(c)!==null);
    const activity=stats(activityPeers.map(turnover));
    const byId=new Map();
    for(const c of coins) {
      const result={events:[],priceZ:null,activityZ:null,divergence:null,score:0,available:false,reason:null,
        observation:observation(c,now),relativeBTC:isXstock(c)?{value:null,reason:'xStocks are outside the crypto reference',dated:false}:relativeBitcoin(c,btc,key,current,now),medianGap:null};
      byId.set(c.id,result);
      if(isXstock(c)) {result.reason='xStocks are outside the crypto reference';continue;}
      if(!current) {result.reason='Market data is not current';continue;}
      if(!observed(c)) {result.reason=result.observation==='invalid'?'Asset observation time is invalid':'Asset price is stale';continue;}
      if(!Number.isFinite(c[key])) {result.reason='Return unavailable for this period';continue;}
      if(price.n<MIN_PEERS) {result.reason='Insufficient reference coverage';continue;}
      result.available=true;
      result.medianGap=c[key]-market.median;
      result.priceZ=price.sd>0?(c[key]-price.mean)/price.sd:0;
      if(Math.abs(result.priceZ)>2) result.events.push({kind:'price',label:result.priceZ>0?'Unusual rise':'Unusual decline',score:Math.abs(result.priceZ)});
      // Turnover is a 24h observation. Never compare it with a 1h/7d/30d return.
      const a=turnover(c);
      if(tf==='24h'&&a!==null&&activity.n>=MIN_PEERS&&activity.sd>0&&price.sd>0) {
        result.activityZ=(a-activity.mean)/activity.sd;
        if(result.activityZ>2) result.events.push({kind:'activity',label:'Unusual turnover',score:result.activityZ});
        const spread=result.priceZ-result.activityZ;
        if(Math.abs(spread)>1.2) {
          result.divergence=spread;
          result.events.push({kind:'divergence',label:spread>0?'Price stronger than activity':'Activity stronger than price',score:Math.abs(spread)});
        }
      }
      result.score=Math.max(0,...result.events.map(e=>e.score));
    }
    return {byId,price,activity,market,tf,referenceCount:crypto.length,current,minPeers:MIN_PEERS};
  }
  function settings(value) {
    const s={...DEFAULTS};
    if(!value||typeof value!=='object') return s;
    if(Object.hasOwn(TF,value.tf)) s.tf=value.tf;
    if(['perf','market_cap','total_volume'].includes(value.metric)) s.metric=value.metric;
    if(['all','divergence','anomaly','gainers','losers'].includes(value.filter)) s.filter=value.filter;
    if(typeof value.signalsOpen==='boolean') s.signalsOpen=value.signalsOpen;
    return s;
  }
  function importWatchlist(raw) {
    if(typeof raw!=='string'||raw.length>16384) throw new Error('File exceeds 16 KB');
    let d; try {d=JSON.parse(raw);}catch {throw new Error('Invalid JSON file');}
    if(!d||d.version!==1||!Array.isArray(d.coins)||d.coins.length>MAX_FAV) throw new Error('Expected an Orbit2 watchlist with up to 50 assets');
    if(d.coins.some(id=>typeof id!=='string'||!ID.test(id))) throw new Error('Invalid asset identifier');
    const coins=[...new Set(d.coins)].filter(id=>!isXstock({id}));
    return {coins,settings:settings(d.settings)};
  }
  function mergeWatchlist(current,incoming,replace=false) {
    const result=[...new Set(replace?incoming:[...current,...incoming])].filter(id=>!isXstock({id}));
    if(result.length>MAX_FAV) throw new Error('This selection exceeds 50 assets');
    return result;
  }
  function squarify(items,rect) {
    items=items.filter(i=>Number.isFinite(i.value)&&i.value>0);
    const scale=Math.max(0,...items.map(i=>i.value));
    items=items.map(i=>({...i,value:Math.max(i.value/scale,1e-9)}));
    const total=items.reduce((s,i)=>s+i.value,0),out=[];
    if(total<=0||rect.w<=0||rect.h<=0) return out;
    let rem=items.map(i=>({...i,area:i.value*rect.w*rect.h/total}));
    let {x,y,w,h}=rect;
    const worst=(row,side)=>{const s=row.reduce((a,r)=>a+r.area,0);return Math.max(side*side*Math.max(...row.map(r=>r.area))/(s*s),s*s/(side*side*Math.min(...row.map(r=>r.area))));};
    while(rem.length) {
      const side=Math.min(w,h),row=[];
      while(rem.length) {const test=row.concat(rem[0]);if(!row.length||worst(test,side)<=worst(row,side))row.push(rem.shift());else break;}
      const s=row.reduce((a,r)=>a+r.area,0);
      if(w<=h) {const rh=s/w;let ox=x;for(const it of row){const iw=it.area/rh;out.push({...it,x:ox,y,w:iw,h:rh});ox+=iw;}y+=rh;h=Math.max(0,h-rh);}
      else {const rw=s/h;let oy=y;for(const it of row){const ih=it.area/rw;out.push({...it,x,y:oy,w:rw,h:ih});oy+=ih;}x+=rw;w=Math.max(0,w-rw);}
    }
    return out;
  }
  function tileContent(w,h,hasLogo=true) {
    const pad=Math.min(20,Math.max(4,Math.min(w,h)*.055));
    const iw=Math.max(0,w-pad*2),ih=Math.max(0,h-pad*2);
    const font=Math.max(0,Math.min(iw/6.5,ih*.2));
    const gap=Math.min(iw,ih)*.045;
    const logo=hasLogo?Math.max(0,Math.min(iw*.53,ih-font-gap,ih*.58)):0;
    return {pad,font:hasLogo?font:Math.min(iw/6.5,ih*.45),logo,gap};
  }
  return {TF,ID,MAX_FAV,MIN_PEERS,DEFAULTS,text,num,time,isXstock,assetSource,quoteState,normalizeSnapshot,sourceState,stats,analyze,settings,importWatchlist,mergeWatchlist,squarify,tileContent};
});
