// Synthetic failure/recovery fixtures only; no provider requests or production data.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path');
const origin=process.env.ORBIT_PREVIEW_URL||'http://127.0.0.1:8767';
(async()=>{
  const browser=await chromium.launch({headless:true});
  const screenshots=await fs.mkdtemp(path.join(os.tmpdir(),'orbit-outage-'));
  try{
    const context=await browser.newContext({locale:'fr-FR'}),page=await context.newPage(),errors=[],external=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(new URL(r.url()).origin!==origin)external.push(r.url());});
    const now=new Date().toISOString(),old=new Date(Date.now()-4*3600000).toISOString();
    const coin={id:'bitcoin',symbol:'btc',name:'Bitcoin',current_price:12345,market_cap:100000,total_volume:1000,price_change_percentage_24h_in_currency:-47.89,last_updated:old,has_logo:false};
    let data={snapshot:now,status:{coingecko_markets:{ok:false,http_status:403,last_success_at:old,retry_at:new Date(Date.now()+900000).toISOString()}},coins:[coin]};
    await page.route('**/data.json',r=>r.fulfill({json:data}));
    await context.addInitScript(()=>localStorage.setItem('orbit.favs.v1','["bitcoin"]'));
    await page.goto(origin+'/web/');await page.waitForFunction(()=>state.snapshot);
    for(const lang of ['fr','en']){
      await page.locator(`[data-lang="${lang}"]`).click();
      assert.match(await page.locator('#sourceStatus').textContent(),/HTTP 403/);
      assert.match(await page.locator('#sourceStatus').textContent(),lang==='fr'?/Accès refusé/:/access refused/);
      for(const width of [1440,390,320]){
        await page.setViewportSize({width,height:844});
        await page.waitForFunction(()=>document.querySelector('.tile-hit')?.dataset.current==='false');
        const tile=page.locator('.tile-hit');assert.doesNotMatch(await tile.getAttribute('aria-label'),/47[.,](?:89|9)/);
        const color=await page.evaluate(()=>{const r=rects[0],scale=Math.min(devicePixelRatio||1,2);return [...ctx.getImageData((r.x+12)*scale,(r.y+12)*scale,1,1).data];});
        assert.deepEqual(color,[36,40,44,255]);
        await tile.click();assert.doesNotMatch(await page.locator('.asset-quote').textContent(),/12345|12.345|47[.,](?:89|9)/);
        await page.locator('#assetTab-market').click();
        assert.equal(await page.locator('#assetPane-market .spark').count(),0);
        assert.equal(await page.locator('#assetDialog').evaluate(d=>d.scrollWidth>d.clientWidth),false);
        await page.keyboard.press('Escape');
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
        await page.screenshot({path:path.join(screenshots,`outage-${lang}-${width}.png`)});
      }
    }
    // Individual stale quotes stay unavailable even after the feed recovers.
    data={...data,snapshot:new Date().toISOString(),status:{coingecko_markets:{ok:true,fetched_at:now}}};
    await page.evaluate(()=>refresh());assert.equal(await page.locator('.tile-hit').getAttribute('data-current'),'false');
    data.coins=[{...coin,last_updated:now}];data.snapshot=new Date().toISOString();
    await page.evaluate(()=>refresh());await page.waitForFunction(()=>document.querySelector('.tile-hit')?.dataset.current==='true');
    assert.match(await page.locator('.tile-hit').getAttribute('aria-label'),/47[.,](?:89|9)/);
    assert.doesNotMatch(await page.locator('#sourceStatus').textContent(),/HTTP 403/);
    // The supported five-minute schedule stays usable between collections.
    const fiveMinutesAgo=new Date(Date.now()-300000).toISOString();
    data.status.coingecko_markets={ok:true,fetched_at:fiveMinutesAgo,policy:'demo-250-v1'};
    data.coins=[{...coin,last_updated:fiveMinutesAgo}];
    await page.evaluate(()=>refresh());
    assert.equal(await page.locator('.tile-hit').getAttribute('data-current'),'true');
    for(const lang of ['fr','en']){
      await page.locator(`[data-lang="${lang}"]`).click();
      assert.match(await page.locator('#sourceStatus').textContent(),/5 min/);
      for(const width of [1440,390,320]){
        await page.setViewportSize({width,height:844});
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
        await page.screenshot({path:path.join(screenshots,`demo-${lang}-${width}.png`)});
      }
    }
    data.status.coingecko_markets.fetched_at=new Date().toISOString();
    data.coins[0].last_updated=new Date(Date.now()-601000).toISOString();
    await page.evaluate(()=>refresh());
    await page.waitForFunction(()=>document.querySelector('.tile-hit')?.dataset.current==='false');
    assert.equal(await page.locator('.tile-hit').getAttribute('data-current'),'false');
    data.coins[0].last_updated=null;
    await page.evaluate(()=>refresh());
    assert.equal(await page.locator('.tile-hit').getAttribute('data-current'),'false');
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.deepEqual(await context.cookies(),[]);
    console.log(JSON.stringify({result:'PASS',checks:['failed source','stale quote','neutral tiles','no obsolete prices','HTTP cause FR/EN','fresh recovery','320px layout','Demo five-minute cadence','Demo old/undated price rejection'],screenshots}));
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
