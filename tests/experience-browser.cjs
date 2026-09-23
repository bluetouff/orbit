// Local preview only. Real public data for visual checks; isolated fixtures for failure states.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path');
const C=require('../web/core.js');
const origin=process.env.ORBIT_PREVIEW_URL||'http://127.0.0.1:8767';
async function main(){
  const screenshots=await fs.mkdtemp(path.join(os.tmpdir(),'orbit2-experience-'));
  const browser=await chromium.launch({headless:true});
  try{
    const context=await browser.newContext({locale:'fr-FR',viewport:{width:1440,height:950}}),page=await context.newPage(),errors=[],external=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
    page.on('request',r=>{if(new URL(r.url()).origin!==origin)external.push(r.url());});
    await page.goto(origin+'/web/');await page.waitForFunction(()=>state.snapshot&&[...logos.values()].filter(l=>l.ok).length>=6);
    assert.equal(await page.locator('html').getAttribute('lang'),'fr');
    assert.match(await page.locator('#buildWatchlist').textContent(),/Choisir mes cryptos/);
    assert.match(await page.locator('.home-copy').textContent(),/Vos cryptos/);
    assert.match(await page.locator('#mapSummary').textContent(),/^6 cryptos/);
    assert.doesNotMatch(await page.locator('#mapSummary').textContent(),/indisponibles/);
    assert.equal(await page.locator('.support-link').getAttribute('href'),'https://l0g.fr/soutenir/');
    assert.equal(await page.evaluate(()=>state.selected.size),0);
    await page.screenshot({path:path.join(screenshots,'home-fr.png')});
    for(const lang of ['en','fr']){
      await page.locator(`[data-lang="${lang}"]`).click();
      for(const width of [2560,1440,768,390,320]){
        await page.setViewportSize({width,height:width>780?950:844});await page.waitForTimeout(100);
        const fits=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth||document.getElementById('shell').scrollWidth>innerWidth,support:document.querySelector('.support-link').getBoundingClientRect().right<=innerWidth}));
        assert.equal(fits.overflow,false,`Home overflow ${lang} ${width}`);assert.equal(fits.support,true);
        await page.screenshot({path:path.join(screenshots,`home-${lang}-${width}.png`)});
      }
    }
    await page.locator('#homeFaq summary').first().click();
    assert.match(await page.locator('#homeFaq details[open]').textContent(),/1,2/);
    await page.locator('#buildWatchlist').click();await page.locator('#welcomeSearch').fill('Bitcoin');
    await page.getByRole('button',{name:'Ajouter Bitcoin',exact:true}).click();await page.locator('#finishWelcome').click();
    await page.reload();await page.waitForSelector('.tile-hit');
    assert.equal(await page.locator('html').getAttribute('lang'),'fr');assert.equal(await page.locator('#homeIntro').isVisible(),false);
    await page.locator('#homeLink').click();assert.equal(await page.locator('#homeIntro').isVisible(),true);assert.equal(await page.locator('#watchCount').textContent(),'1');
    await page.locator('#buildWatchlist').click();
    for(const lang of ['fr','en']){
      await page.locator(`[data-lang="${lang}"]`).click();
      for(const [width,height]of [[1440,950],[1366,768],[390,844],[320,568]]){
        await page.setViewportSize({width,height});await page.locator('.tile-hit').first().click();
        const bounds=await page.locator('#assetDialog').evaluate(d=>({overflow:d.scrollWidth>d.clientWidth,scroll:d.scrollTop,last:d.querySelector('[data-reading="divergence"]').getBoundingClientRect().bottom,bottom:d.getBoundingClientRect().bottom,viewport:innerHeight}));
        assert.equal(bounds.overflow,false);assert.equal(bounds.scroll,0);assert.ok(bounds.last<=Math.min(bounds.bottom,bounds.viewport),JSON.stringify({lang,width,height,bounds}));
        assert.equal(await page.locator('#assetPane-market').isVisible(),false);
        await page.screenshot({path:path.join(screenshots,`signals-${lang}-${width}.png`)});
        await page.locator('#assetTab-signals').focus();await page.keyboard.press('ArrowRight');
        assert.equal(await page.locator('#assetTab-market').getAttribute('aria-selected'),'true');
        await page.evaluate(()=>renderAsset());assert.equal(await page.locator('#assetTab-market').getAttribute('aria-selected'),'true');
        assert.equal(await page.evaluate(()=>document.activeElement.id),'assetTab-market');
        await page.keyboard.press('Home');assert.equal(await page.locator('#assetTab-signals').getAttribute('aria-selected'),'true');
        await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>document.activeElement.className),'tile-hit');
      }
    }
    await page.locator('[data-lang="fr"]').click();await page.goto(origin+'/web/legal/');
    assert.equal(await page.locator('html').getAttribute('lang'),'fr');assert.match(await page.locator('h1').textContent(),/cadre clair/);
    assert.equal(await page.locator('code').filter({hasText:'orbit.locale.v1'}).count(),1);
    await page.locator('[data-lang="en"]').click();assert.match(await page.locator('h1').textContent(),/Clear terms/);
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);await context.close();

    const fixtures=await browser.newContext({viewport:{width:390,height:844}}),testPage=await fixtures.newPage();
    const stamp=new Date().toISOString(),fixture={snapshot:stamp,coins:Array.from({length:30},(_,i)=>({id:'test-'+i,name:'Test '+i,symbol:'t'+i,current_price:1,market_cap:1000,total_volume:i===0?50000:20+i,[C.TF['24h']]:i===0?-60:i%7-3,[C.TF['7d']]:i%9,has_logo:false}))};
    await testPage.route('**/data.json',r=>r.fulfill({json:fixture}));
    await testPage.goto(origin+'/web/');await testPage.waitForFunction(()=>state.snapshot);
    await testPage.evaluate(()=>openAsset('test-0'));
    const actual=await testPage.evaluate(()=>['price','activity','divergence'].map(kind=>{const r=signalReading(byId('test-0'),kind);return {kind,value:r.value,active:r.active};}));
    const result=C.analyze(C.normalizeSnapshot(fixture),'24h').byId.get('test-0');
    assert.deepEqual(actual.map(r=>r.value),[result.priceZ,result.activityZ,result.priceZ-result.activityZ]);
    assert.ok(actual.every(r=>r.active));
    await testPage.screenshot({path:path.join(screenshots,'synthetic-alert-test.png')});
    await testPage.evaluate(()=>{changeSetting('tf','7d');renderAsset();});
    assert.equal(await testPage.locator('.signal-reading .is-unavailable').count(),2);
    assert.match(await testPage.locator('[data-reading="divergence"]').textContent(),/24H only/);
    await testPage.evaluate(()=>{state.snapshot.snapshot='2020-01-01T00:00:00Z';render();renderAsset();});
    assert.equal(await testPage.locator('.gauge-marker').count(),0);
    assert.equal(await testPage.locator('.signal-reading .is-unavailable').count(),3);
    assert.match(await testPage.locator('#assetPane-signals').textContent(),/Signals unavailable/);
    await fixtures.close();
    console.log(JSON.stringify({result:'PASS',screenshots,checks:['new visitor FR/EN','home without preselected favorites','FAQ','support links','locale persistence','home return preserves favorites','signals above fold','keyboard tabs and refresh','stale suppression','7D suppresses activity','signed scores unchanged','legal translations','no third-party requests']},null,2));
  }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exit(1);});
