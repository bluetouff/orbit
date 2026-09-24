const assert = require('node:assert/strict');
const {test} = require('node:test');
const C = require('../web/core.js');

// Synthetic boundary fixtures only. Never served as application data.
const stamp = '2026-01-01T00:00:00Z', now = Date.parse(stamp);
function raw(count=40) {
  return {snapshot:stamp,coins:Array.from({length:count},(_,i)=>({
    id:'asset-'+i,symbol:'a'+i,name:'Test asset '+i,current_price:1,market_cap:1000,total_volume:20+i,
    [C.TF['24h']]:i===0?45:i%7-3,[C.TF['1h']]:i%4,[C.TF['7d']]:i%9,[C.TF['30d']]:i%11,
  }))};
}
test('missing values and booleans never become financial zeroes',()=>{
  for(const v of [null,undefined,true,false,'',' ',[],{},NaN,Infinity])assert.equal(C.num(v),null);
  assert.equal(C.num(0),0);assert.equal(C.num('1.25'),1.25);
  const r=raw();r.coins[0][C.TF['24h']]=null;
  const s=C.normalizeSnapshot(r);assert.equal(s.coins[0][C.TF['24h']],null);assert.equal(s.global.cap,null);
});
test('snapshot validation rejects traversal, duplicate ids and missing required values',()=>{
  const r=raw(1);r.coins.push({...r.coins[0]}, {...r.coins[0],id:'../private'}, {...r.coins[0],id:'broken',market_cap:null});
  assert.equal(C.normalizeSnapshot(r).coins.length,1);
  assert.throws(()=>C.normalizeSnapshot({coins:[]}));
});
test('reference and signal scores are independent of any watchlist or visible filter',()=>{
  const s=C.normalizeSnapshot(raw()),a=C.analyze(s,'24h',now),b=C.analyze(s,'24h',now);
  const watchlist=s.coins.slice(0,2).map(c=>a.byId.get(c.id));
  assert.deepEqual(watchlist,b.byId.size===40?s.coins.slice(0,2).map(c=>b.byId.get(c.id)):[]);
  assert.equal(a.price.n,40);assert.ok(a.byId.get('asset-0').events.some(e=>e.kind==='price'));
  assert.deepEqual(C.analyze({...s,coins:[...s.coins].reverse()},'24h',now).byId.get('asset-0').events.map(e=>e.kind),a.byId.get('asset-0').events.map(e=>e.kind));
});
test('missing returns and insufficient coverage suppress signals',()=>{
  const r=raw(20);r.coins[0][C.TF['24h']]=null;const a=C.analyze(C.normalizeSnapshot(r),'24h',now);
  assert.equal(a.price.n,19);assert.equal(a.byId.get('asset-0').reason,'Return unavailable for this period');
  assert.ok([...a.byId.values()].every(r=>!r.available&&r.events.length===0));
});
test('stale, unknown and future collection dates suppress signals',()=>{
  const s=C.normalizeSnapshot(raw());
  assert.ok(C.analyze(s,'24h',now+180000).current);
  for(const [snapshot,at] of [[s,now+180001],[{...s,snapshot:null},now],[s,now-60001]]){
    const a=C.analyze(snapshot,'24h',at);assert.equal(a.current,false);assert.ok([...a.byId.values()].every(r=>!r.events.length));
  }
  assert.equal(C.time('2026-01-01'),null);assert.equal(C.time('2026-01-01T00:00:00'),null);
});
test('stale asset observations are excluded even from a freshly built snapshot',()=>{
  const r=raw();r.coins[0].last_updated='2025-12-31T23:50:00Z';const a=C.analyze(C.normalizeSnapshot(r),'24h',now);
  assert.equal(a.price.n,39);assert.equal(a.byId.get('asset-0').reason,'Asset price is stale');
});
test('24h activity is never compared with returns for another period',()=>{
  const s=C.normalizeSnapshot(raw());
  assert.ok(C.analyze(s,'24h',now).byId.get('asset-0').divergence!==null);
  for(const tf of ['1h','7d','30d'])for(const r of C.analyze(s,tf,now).byId.values()){
    assert.equal(r.activityZ,null);assert.equal(r.divergence,null);assert.ok(r.events.every(e=>e.kind==='price'));
  }
});
test('constant distributions and unusable ratios cannot create NaN signals',()=>{
  const r=raw();for(const c of r.coins){c[C.TF['24h']]=0;c.total_volume=0;}
  for(const a of C.analyze(C.normalizeSnapshot(r),'24h',now).byId.values())assert.deepEqual(a.events,[]);
  r.coins[0].market_cap=1e-200;r.coins[0].total_volume=1e300;
  assert.equal(C.analyze(C.normalizeSnapshot(r),'24h',now).activity.n,39);
});
test('social availability cannot change market signal calculations',()=>{
  const s=C.normalizeSnapshot(raw()),other=structuredClone(s);other.status.lunarcrush={ok:true,fetched_at:stamp};
  for(const c of other.coins)c.galaxy_score=99;
  assert.deepEqual(C.analyze(s,'24h',now),C.analyze(other,'24h',now));
});
test('failed source attempts do not masquerade as last successful retrievals',()=>{
  const s=C.normalizeSnapshot(raw());s.status.fred={ok:false,fetched_at:stamp,last_success_at:'2025-12-31T20:00:00Z'};
  assert.equal(C.sourceState(s,'fred',now).stamp,'2025-12-31T20:00:00Z');assert.equal(C.sourceState(s,'fred',now).usable,false);
  delete s.status.fred.last_success_at;assert.equal(C.sourceState(s,'fred',now).stamp,null);
  s.status.coingecko_markets={ok:false,attempted_at:stamp};
  const failed=C.sourceState(s,'coingecko_markets',now);
  assert.equal(failed.kind,'unavailable');assert.equal(failed.age,null);
  assert.equal(failed.stamp,null); // A new JSON file is not a collection success.
});
test('import validates the complete file before changing a watchlist',()=>{
  const good=JSON.stringify({version:1,coins:['bitcoin','bitcoin','ethereum'],settings:{tf:'7d',metric:'total_volume'}});
  assert.deepEqual(C.importWatchlist(good).coins,['bitcoin','ethereum']);
  for(const value of ['null','{}','{bad',JSON.stringify({version:1,coins:['../../secret']}),JSON.stringify({version:1,coins:[1]}),JSON.stringify({version:1,coins:Array(51).fill('bitcoin')}),' '.repeat(16385)])assert.throws(()=>C.importWatchlist(value));
  assert.equal(C.importWatchlist('{"version":1,"coins":[],"settings":{"__proto__":{"polluted":true},"tf":"bad"}}').settings.tf,'24h');
  assert.equal({}.polluted,undefined);
});
test('merge is bounded, deterministic and preserves missing ids',()=>{
  assert.deepEqual(C.mergeWatchlist(['bitcoin'],['unknown','bitcoin']),['bitcoin','unknown']);
  assert.deepEqual(C.mergeWatchlist(['bitcoin'],['ethereum'],true),['ethereum']);
  assert.throws(()=>C.mergeWatchlist(Array.from({length:50},(_,i)=>'a'+i),['extra']));
});
test('settings are strictly allowlisted',()=>{
  assert.deepEqual(C.settings({tf:'__proto__',metric:'anything',filter:'anything',signalsOpen:'false',secret:'x'}),C.DEFAULTS);
});
test('treemap stays bounded without overlaps at 1, 6, 50 and 100 assets',()=>{
  for(const [w,h]of [[320,460],[1400,750],[3840,1900]])for(const n of [1,6,50,100]){
    const items=Array.from({length:n},(_,i)=>({id:i,value:.12+(i%13)/13})),r=C.squarify(items,{x:0,y:0,w,h});
    assert.equal(r.length,n);assert.ok(Math.abs(r.reduce((s,r)=>s+r.w*r.h,0)-w*h)<.01);
    for(const a of r){assert.ok(a.x>=-.001&&a.y>=-.001&&a.x+a.w<=w+.001&&a.y+a.h<=h+.001);for(const b of r)if(a!==b)assert.ok(Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x)<.001||Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y)<.001);}
  }
});
test('layout ignores invalid weights and handles extreme finite weights',()=>{
  assert.deepEqual(C.squarify([{value:0},{value:NaN}],{x:0,y:0,w:100,h:100}),[]);
  for(const r of C.squarify([{value:1e300},{value:1e-100}],{x:0,y:0,w:3840,h:2160}))for(const k of ['x','y','w','h'])assert.ok(Number.isFinite(r[k]));
});
test('logos and returns scale with tile size without a desktop size cap',()=>{
  const small=C.tileContent(200,200),big=C.tileContent(800,800),wide=C.tileContent(1000,120);
  assert.ok(big.font>small.font*3);assert.ok(big.logo>small.logo*3);
  for(const [w,h]of [[30,30],[1000,120],[800,800],[80,500]]){
    const a=C.tileContent(w,h);assert.ok(a.logo+a.gap+a.font<=h+1);assert.ok(a.logo<=w);
  }
  assert.ok(wide.logo<120);
});

test('market median and breadth count every usable return, including unchanged assets',()=>{
  const r=raw(20);r.coins.forEach((c,i)=>{c[C.TF['24h']]=i-9;c.last_updated=stamp;});
  const a=C.analyze(C.normalizeSnapshot(r),'24h',now);
  assert.deepEqual(a.market,{available:true,n:20,total:20,dated:20,median:0.5,up:10,down:9,flat:1});
  assert.equal(a.byId.get('asset-0').medianGap,-9.5);
  r.coins.push({...r.coins[0],id:'twenty-first',[C.TF['24h']]:11});
  assert.equal(C.analyze(C.normalizeSnapshot(r),'24h',now).market.median,1);
});
test('market context is unavailable, not neutral, when stale or coverage is insufficient',()=>{
  for(const [r,at]of [[raw(19),now],[raw(),now+180001]]){
    const a=C.analyze(C.normalizeSnapshot(r),'24h',at);
    assert.equal(a.market.available,false);
    for(const key of ['median','up','down','flat'])assert.equal(a.market[key],null);
    assert.ok([...a.byId.values()].every(r=>r.medianGap===null));
  }
});
test('invalid supplied dates cannot fall back to collection-only eligibility',()=>{
  const r=raw();r.coins[0].last_updated='not-a-date';r.coins[1].last_updated='';r.coins[2].last_updated=stamp;
  const a=C.analyze(C.normalizeSnapshot(r),'24h',now);
  assert.equal(a.price.n,38);assert.equal(a.market.dated,1);
  assert.equal(a.byId.get('asset-0').reason,'Asset observation time is invalid');
  assert.equal(a.byId.get('asset-1').available,false);
  assert.equal(a.byId.get('asset-3').observation,'unknown');
});
function bitcoinFixture(assetReturn=10,btcReturn=5){
  const r=raw();r.coins[0].id='ethereum';r.coins[1].id='bitcoin';
  for(const c of r.coins)c.last_updated=stamp;
  r.coins[0][C.TF['24h']]=assetReturn;r.coins[1][C.TF['24h']]=btcReturn;
  return r;
}
test('BTC-relative performance is a wealth ratio, not a percentage-point subtraction',()=>{
  for(const [asset,btc,expected] of [[10,5,100/21],[-20,-10,-100/9],[5,5,0],[-100,5,-100]]){
    const a=C.analyze(C.normalizeSnapshot(bitcoinFixture(asset,btc)),'24h',now);
    const result=a.byId.get('ethereum').relativeBTC;
    assert.ok(Math.abs(result.value-expected)<1e-10);assert.equal(result.dated,true);assert.equal(result.reason,null);
    assert.equal(a.byId.get('bitcoin').relativeBTC.value,0);
  }
});
test('BTC comparison does not fabricate a benchmark from a symbol or missing return',()=>{
  for(const mutate of [r=>{r.coins[1].id='other';r.coins[1].symbol='btc';},r=>{r.coins[1][C.TF['24h']]=null;},r=>{r.coins[1][C.TF['24h']]=-100;},r=>{r.coins[0][C.TF['24h']]=null;}]){
    const r=bitcoinFixture();mutate(r);
    const result=C.analyze(C.normalizeSnapshot(r),'24h',now).byId.get('ethereum').relativeBTC;
    assert.equal(result.value,null);assert.ok(result.reason);
  }
});
test('BTC comparison fails closed for stale, invalid, future or misaligned observations',()=>{
  for(const [index,date,at]of [[0,'2025-12-31T23:50:00Z',now],[1,'broken',now],[1,'2026-01-01T00:01:01Z',now],[1,'2025-12-31T23:58:59Z',now],[1,stamp,now+180001]]){
    const r=bitcoinFixture();r.coins[index].last_updated=date;
    const result=C.analyze(C.normalizeSnapshot(r),'24h',at).byId.get('ethereum').relativeBTC;
    assert.equal(result.value,null);assert.ok(result.reason);
  }
  const r=bitcoinFixture();r.coins[1].last_updated='2025-12-31T23:59:00Z';
  assert.notEqual(C.analyze(C.normalizeSnapshot(r),'24h',now).byId.get('ethereum').relativeBTC.value,null);
});
test('legacy collection-only inputs are explicitly distinguished from dated observations',()=>{
  const r=bitcoinFixture();delete r.coins[1].last_updated;
  const a=C.analyze(C.normalizeSnapshot(r),'24h',now);
  assert.equal(a.market.dated,39);assert.equal(a.byId.get('ethereum').relativeBTC.dated,false);
  assert.notEqual(a.byId.get('ethereum').relativeBTC.value,null);
});
test('BTC comparison uses the selected horizon and is independent of anomaly coverage',()=>{
  const r=bitcoinFixture();r.coins=r.coins.slice(0,2);r.coins[0][C.TF['7d']]=20;r.coins[1][C.TF['7d']]=10;
  const a=C.analyze(C.normalizeSnapshot(r),'7d',now),result=a.byId.get('ethereum');
  assert.ok(Math.abs(result.relativeBTC.value-100/11)<1e-10);
  assert.equal(result.available,false);assert.equal(result.medianGap,null);assert.equal(result.activityZ,null);
  assert.deepEqual(result.events,[]);
});
test('market context and relative comparisons do not mutate inputs or depend on their order',()=>{
  const s=C.normalizeSnapshot(bitcoinFixture()),before=structuredClone(s),a=C.analyze(s,'24h',now);
  assert.deepEqual(s,before);
  const b=C.analyze({...s,coins:[...s.coins].reverse()},'24h',now);
  assert.deepEqual(a.market,b.market);assert.deepEqual(a.byId.get('ethereum').relativeBTC,b.byId.get('ethereum').relativeBTC);
});

test('legacy tokens and their source disappear without changing crypto statistics',()=>{
  const original=raw(),baseline=C.analyze(C.normalizeSnapshot(original),'24h',now);
  for(const identity of [{id:'test-xstock'}, {id:'token-a',asset_type:'xstock'},
    {id:'token-b',price_source:'kraken'}, {id:'token-c',name:'Apple xStock'}]){
    original.coins.push({...original.coins[0],...identity,[C.TF['24h']]:99000,market_cap:1,total_volume:1e20});
  }
  original.status={kraken_xstocks:{ok:true,fetched_at:stamp}};
  const normalized=C.normalizeSnapshot(original),mixed=C.analyze(normalized,'24h',now);
  assert.equal(normalized.coins.length,baseline.referenceCount);
  assert.equal(normalized.status.kraken_xstocks,undefined);
  assert.deepEqual(mixed.price,baseline.price);assert.deepEqual(mixed.activity,baseline.activity);assert.deepEqual(mixed.market,baseline.market);
  assert.deepEqual(mixed.byId.get('asset-0'),baseline.byId.get('asset-0'));
  for(const id of ['test-xstock','token-a','token-b','token-c'])assert.equal(mixed.byId.has(id),false);
});

test('retired favorite IDs are removed on import without losing unavailable cryptos',()=>{
  const ids=['bitcoin','apple-xstock','kraken-aaoix','unavailable-crypto'];
  assert.deepEqual(C.importWatchlist(JSON.stringify({version:1,coins:ids})).coins,['bitcoin','unavailable-crypto']);
  assert.deepEqual(C.mergeWatchlist(ids,['ethereum']),['bitcoin','unavailable-crypto','ethereum']);
});
