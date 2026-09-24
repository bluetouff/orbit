// Local real-data preview for visuals; isolated synthetic fixtures for failure and XSS cases.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path');
const origin=process.env.ORBIT_PREVIEW_URL||'http://127.0.0.1:8767';
async function main(){
  const screenshots=await fs.mkdtemp(path.join(os.tmpdir(),'orbit2-xstocks-'));
  const browser=await chromium.launch({headless:true});
  try{
    const context=await browser.newContext({locale:'fr-FR',viewport:{width:1440,height:950}});
    const page=await context.newPage(),errors=[],external=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
    page.on('request',r=>{if(new URL(r.url()).origin!==origin)external.push(r.url());});
    await page.goto(origin+'/web/');await page.waitForFunction(()=>state.snapshot?.coins.some(C.isXstock));
    await page.locator('#buildWatchlist').click();
    await page.locator('#welcomeCatalog [data-catalog="xstock"]').click();
    await page.locator('#welcomeSearch').fill('Apple');
    assert.equal(await page.locator('#welcomeResults [data-coin="apple-xstock"] .coin-values > span').textContent(),await page.evaluate(()=>price(byId('apple-xstock').current_price,true)));
    await page.getByRole('button',{name:'Ajouter Apple xStock',exact:true}).click();
    await page.locator('#welcomeCatalog [data-catalog="crypto"]').click();
    await page.locator('#welcomeSearch').fill('Bitcoin');
    await page.getByRole('button',{name:'Ajouter Bitcoin',exact:true}).click();
    await page.locator('#finishWelcome').click();
    assert.equal(await page.locator('#watchCount').textContent(),'2');
    assert.equal(await page.evaluate(()=>price(337.12,true)),'337,12 $US');
    await page.reload();await page.waitForSelector('[data-quote="apple-xstock"]');
    assert.equal(await page.locator('#watchCount').textContent(),'2');
    await page.locator('[data-view="xstocks"]').click();
    assert.equal(await page.locator('#periodControl').isVisible(),false);
    assert.equal(await page.locator('#filterSelect').isVisible(),false);
    assert.equal(await page.locator('.quote-table tbody tr').count(),await page.evaluate(()=>xstockCoins().length));
    assert.match(await page.locator('#signalList').textContent(),/exclus des signaux crypto/);
    await page.screenshot({path:path.join(screenshots,'market-fr-desktop.png')});
    for(const lang of ['fr','en']){
      await page.locator(`[data-lang="${lang}"]`).click();
      for(const width of [1440,768,390,320]){
        await page.setViewportSize({width,height:900});
        await page.locator('#manageBtn').click();
        assert.equal(await page.locator('#manageCatalog [data-catalog="xstock"]').getAttribute('aria-pressed'),'true');
        await page.locator('#manageSearch').fill('');
        const fits=await page.evaluate(()=>({page:document.documentElement.scrollWidth<=innerWidth,dialog:document.getElementById('manageDialog').scrollWidth<=document.getElementById('manageDialog').clientWidth}));
        assert.deepEqual(fits,{page:true,dialog:true},`${lang} ${width} catalog`);
        await page.screenshot({path:path.join(screenshots,`catalog-${lang}-${width}.png`)});
        await page.locator('#manageSearch').fill('apple');
        assert.equal(await page.locator('#manageResults [data-coin="apple-xstock"]').getAttribute('aria-pressed'),'true');
        await page.locator('#manageDialog [data-close]').first().click();
        await page.waitForFunction(()=>!document.getElementById('manageDialog').open&&document.activeElement.id==='manageBtn');
        await page.locator('[data-quote="apple-xstock"]').focus();await page.keyboard.press('Enter');
        await page.locator('#assetDialog').waitFor({state:'visible'});
        assert.equal(await page.locator('#assetTab-signals').count(),0);
        assert.equal(await page.locator('.signal-reading').count(),0);
        assert.equal(await page.locator('#assetPane-market').count(),0);
        assert.match(await page.locator('#assetContent').textContent(),lang==='fr'?/Dernier échange/:/Last trade/);
        assert.doesNotMatch(await page.locator('#assetContent').textContent(),/LunarCrush/);
        assert.equal(await page.locator('.xstock-notice a').getAttribute('rel'),'noopener noreferrer');
        assert.equal(await page.evaluate(()=>document.getElementById('assetDialog').scrollWidth<=document.getElementById('assetDialog').clientWidth),true);
        await page.screenshot({path:path.join(screenshots,`asset-${lang}-${width}.png`)});
        await page.keyboard.press('Escape');
        await page.waitForFunction(()=>document.activeElement?.dataset.quote==='apple-xstock');
        assert.equal(await page.evaluate(()=>document.activeElement.dataset.quote),'apple-xstock');
      }
    }
    assert.deepEqual(external,[]);assert.deepEqual(errors,[]);assert.deepEqual(await context.cookies(),[]);
    await context.close();
    const fixtures=await browser.newContext({viewport:{width:390,height:844}}),p=await fixtures.newPage();
    const stamp=new Date().toISOString();
    const data={snapshot:stamp,status:{kraken_xstocks:{ok:false,last_success_at:'2020-01-01T00:00:00Z',fetched_at:stamp}},coins:[{id:'test-xstock',symbol:'testx',name:'<img src=x onerror=alert(1)>',asset_type:'xstock',price_source:'kraken',fetched_at:stamp,current_price:1,market_cap:null,total_volume:null,has_logo:false,last_updated:'2020-01-01T00:00:00Z'}]};
    await p.route('**/data.json',r=>r.fulfill({json:data}));
    await p.goto(origin+'/web/');await p.waitForFunction(()=>state.snapshot);
    await p.locator('#buildWatchlist').click();await p.locator('#welcomeCatalog [data-catalog="xstock"]').click();
    assert.match(await p.locator('#welcomeCatalogNote').textContent(),/Collection interrupted/);
    assert.equal(await p.locator('img[src="x"]').count(),0);
    await p.locator('#welcomeResults .coin-choice').click();await p.locator('#finishWelcome').click();
    await p.locator('[data-quote="test-xstock"]').click();
    assert.match(await p.locator('.quote-warning').textContent(),/Collection interrupted/);
    assert.equal(await p.locator('#assetIdentity img[src="x"]').count(),0);
    assert.match(await p.locator('#assetContent').textContent(),/not provided in this view/);
    assert.equal(await p.locator('.signal-reading').count(),0);
    // Recovery clears a collection error without inventing a newer trade.
    data.status.kraken_xstocks={ok:true,fetched_at:stamp,last_success_at:stamp,ttl:60};
    data.coins[0].last_updated=new Date(Date.now()-5*60000).toISOString();
    await p.evaluate(()=>refresh());
    assert.equal(await p.locator('.quote-warning').count(),0);
    assert.match(await p.locator('#assetContent').textContent(),/A last trade can be old/);
    assert.match(await p.locator('#sourceStatus').textContent(),/Collection current/);
    data.coins[0].last_updated=new Date(Date.now()-11*60000).toISOString();
    await p.evaluate(()=>refresh());
    assert.equal(await p.locator('.quote-warning').count(),0);
    assert.equal(await p.evaluate(()=>byId('test-xstock').last_updated),data.coins[0].last_updated);
    data.coins[0].fetched_at=new Date(Date.now()-41*60000).toISOString();
    await p.evaluate(()=>refresh());
    assert.match(await p.locator('.quote-warning').textContent(),/Collection interrupted/);
    await fixtures.close();
    console.log(JSON.stringify({result:'PASS',screenshots,checks:['real xStocks catalog','mixed favorites and persistence','FR/EN 320 to 1440px','keyboard and focus','no crypto signals on tokens','nullable metrics','stale feed','XSS text','same-origin requests','no cookies']},null,2));
  }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exit(1);});
