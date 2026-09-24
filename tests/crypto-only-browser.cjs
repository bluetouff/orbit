// Isolated migration fixtures. Real-data visual QA lives in experience-browser.cjs.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const origin=process.env.ORBIT_PREVIEW_URL||'http://127.0.0.1:8767';
(async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const context=await browser.newContext({locale:'fr-FR'}),page=await context.newPage(),external=[],errors=[];
    page.on('request',r=>{if(new URL(r.url()).origin!==origin)external.push(r.url());});
    page.on('pageerror',e=>errors.push(e.message));
    const stamp=new Date().toISOString(),crypto={id:'bitcoin',name:'Bitcoin',symbol:'btc',asset_type:'crypto',current_price:1,market_cap:1000,total_volume:50,last_updated:stamp,has_logo:false};
    const fixture={snapshot:stamp,status:{coingecko_markets:{ok:true,fetched_at:stamp},kraken_xstocks:{ok:true,fetched_at:stamp}},coins:[crypto,
      {...crypto,id:'apple-xstock',name:'Apple xStock',symbol:'aaplx',asset_type:'xstock'},
      {...crypto,id:'kraken-aaoix',name:'AAOIx',symbol:'aaoix',price_source:'kraken'}]};
    await page.route('**/data.json',r=>r.fulfill({json:fixture}));
    await context.addInitScript(()=>{localStorage.setItem('orbit.favs.v1',JSON.stringify(['bitcoin','apple-xstock','kraken-aaoix','unavailable-crypto']));});
    await page.goto(origin+'/web/');await page.waitForFunction(()=>state.snapshot);
    assert.deepEqual(await page.evaluate(()=>state.snapshot.coins.map(c=>c.id)),['bitcoin']);
    assert.deepEqual(await page.evaluate(()=>[...state.selected]),['bitcoin','unavailable-crypto']);
    assert.deepEqual(await page.evaluate(()=>JSON.parse(localStorage.getItem('orbit.favs.v1'))),['bitcoin','unavailable-crypto']);
    assert.equal(await page.locator('[data-view="xstocks"],#xstockQuotes,[data-catalog]').count(),0);
    assert.doesNotMatch(await page.locator('#sourceStatus').textContent(),/kraken|xstocks/i);
    assert.equal(await page.locator('#watchCount').textContent(),'2');
    await page.locator('#manageBtn').click();await page.locator('#manageSearch').fill('Apple');
    assert.equal(await page.locator('#manageDialog .coin-choice').count(),0);
    await page.locator('#manageDialog [data-close]').first().click();
    for(const lang of ['fr','en']){
      await page.locator(`[data-lang="${lang}"]`).click();
      assert.match(await page.locator('#methodDialog .prose p').first().textContent(),lang==='fr'?/Les actifs crypto/:/Crypto assets/);
      assert.match(await page.locator('#homeFaq details').nth(1).textContent(),lang==='fr'?/La référence inclut les actifs crypto/:/reference includes crypto assets/);
      for(const width of [1440,390,320]){
        await page.setViewportSize({width,height:844});
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
        await page.locator('[data-view="market"]').click();
        assert.equal(await page.locator('.tile-hit').count(),1);
        await page.locator('.tile-hit').click();
        assert.doesNotMatch(await page.locator('#assetDialog').textContent(),/Kraken|xStocks/);
        await page.keyboard.press('Escape');
      }
    }
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.deepEqual(await context.cookies(),[]);
    await context.close();
    console.log('PASS: crypto-only UI, legacy feed and favorite migration, FR/EN, mobile, no external requests or cookies.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
