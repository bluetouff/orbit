// Deterministic, loopback-only CI coverage. Synthetic fixtures never reach production.
'use strict';
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');
const C=require('../web/core.js');

async function main(){
  const tmp=await fs.mkdtemp(path.join(os.tmpdir(),'orbit-ui-fixture-'));
  const screenshots=path.resolve('test-results');await fs.mkdir(screenshots,{recursive:true});
  await fs.writeFile(path.join(tmp,'snapshot.json'),JSON.stringify({coins:[]}));
  const server=spawn(process.env.PYTHON||'python3',['scripts/preview.py','--port','0','--snapshot',path.join(tmp,'snapshot.json'),'--logos',tmp],{stdio:['ignore','pipe','pipe']});
  const origin=await new Promise((resolve,reject)=>{
    const timeout=setTimeout(()=>reject(new Error('Preview did not start')),10000);
    server.once('error',reject);server.once('exit',code=>reject(new Error('Preview exited '+code)));
    server.stdout.on('data',body=>{const match=body.toString().match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timeout);resolve(match[0]);}});
  });
  let browser,page;
  try{
    browser=await chromium.launch({headless:true});
    const context=await browser.newContext({locale:'fr-FR',viewport:{width:1440,height:950}});
    page=await context.newPage();const errors=[],external=[];
    page.on('pageerror',error=>errors.push(error.message));
    page.on('request',request=>{if(new URL(request.url()).origin!==origin)external.push(request.url());});
    let fail=false,stale=false;
    await context.route('**/data.json',route=>{
      if(fail)return route.fulfill({status:503,body:'Unavailable'});
      const stamp=new Date(Date.now()-(stale?3600000:0)).toISOString();
      const coins=Array.from({length:120},(_,i)=>({id:i===0?'bitcoin':i===1?'tether':'test-'+i,symbol:i===0?'btc':i===1?'usdt':'t'+i,name:i===0?'Bitcoin':i===1?'Tether':'Test '+i,has_logo:false,current_price:i+1,market_cap:(121-i)*1000,market_cap_rank:i+1,total_volume:i===2?1000000:i+1,last_updated:stamp,...Object.fromEntries(Object.values(C.TF).map(k=>[k,i===2?30:i%7-3]))}));
      return route.fulfill({json:{snapshot:stamp,coins,status:{coingecko_markets:{ok:true,policy:'demo-250-v1',fetched_at:stamp}}}});
    });
    await page.goto(origin+'/web/');await page.waitForFunction(()=>state.snapshot);
    await page.locator('#buildWatchlist').click();await page.locator('#welcomeSearch').fill('Bitcoin');await page.getByRole('button',{name:'Ajouter Bitcoin',exact:true}).click();await page.locator('#finishWelcome').click();
    await page.reload();await page.waitForSelector('.tile-hit');assert.equal(await page.locator('#watchCount').textContent(),'1');
    await page.locator('[data-view="market"]').click();
    await page.locator('#filterSelect').selectOption('divergence');await page.locator('[data-tf="7d"]').click();
    await page.locator('.tile-hit').nth(99).waitFor();
    assert.equal(await page.locator('#filterSelect').inputValue(),'all');assert.equal(await page.locator('#filterSelect option[value="divergence"]').evaluate(e=>e.disabled),true);
    assert.match(await page.locator('#filterNotice').textContent(),/24H/);assert.equal(await page.locator('.tile-hit').count(),100);
    await page.locator('[data-tf="24h"]').click();assert.equal(await page.locator('#filterSelect option[value="divergence"]').evaluate(e=>e.disabled),false);
    assert.equal(await page.locator('.tile-hit[tabindex="0"]').count(),1);
    await page.locator('.tile-hit').first().focus();await page.keyboard.press('ArrowRight');await page.keyboard.press('Enter');await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(()=>document.activeElement.dataset.tile),'tether');
    await page.locator('[data-layout="list"]').click();assert.equal(await page.locator('#assetRows tr').count(),100);
    await page.locator('#assetSearch').fill('Bitcoin');assert.equal(await page.locator('#assetRows tr').count(),1);
    await page.locator('[data-list-asset="bitcoin"]').click();await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>document.activeElement.dataset.listAsset),'bitcoin');
    await page.locator('#assetSearch').fill('<img src=x onerror=alert(1)>');assert.equal(await page.locator('#assetRows tr').count(),0);assert.equal(await page.locator('#listEmpty').isVisible(),true);
    await page.locator('#assetSearch').fill('');await page.locator('#sortSelect').selectOption('performance');
    assert.equal(await page.locator('#assetRows button').first().getAttribute('data-list-asset'),'test-2');
    await page.locator('#referenceSelect').selectOption('screened');
    assert.equal(await page.evaluate(()=>state.analysis.byId.get('tether').available),false);
    assert.equal(await page.locator('[data-list-asset="tether"]').count(),1);
    await page.locator('.reference-details summary').click();assert.match(await page.locator('#referenceNote').textContent(),/2026-10-03/);
    await page.locator('.reference-details summary').click();
    for(const lang of ['fr','en']){
      await page.locator(`[data-lang="${lang}"]`).click();
      for(const width of [1440,768,390,320]){
        await page.setViewportSize({width,height:950});
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${lang} ${width}`);
        assert.equal(await page.locator('#assetList').evaluate(e=>e.scrollWidth>e.clientWidth),false,`list overflow ${lang} ${width}`);
        assert.equal(await page.evaluate(()=>document.querySelector('#assetList').getBoundingClientRect().bottom<=document.querySelector('.map-section').getBoundingClientRect().bottom),true,`list overlaps following section ${lang} ${width}`);
        await page.screenshot({path:path.join(screenshots,`list-${lang}-${width}.png`)});
      }
    }
    await page.locator('#settingsBtn').click();
    const downloadPromise=page.waitForEvent('download');await page.locator('#exportBtn').click();
    const download=await downloadPromise,exported=JSON.parse(await fs.readFile(await download.path(),'utf8'));
    assert.equal(exported.settings.layout,'list');assert.equal(exported.settings.reference,'screened');
    await page.locator('#importFile').setInputFiles({name:'bad.json',mimeType:'application/json',buffer:Buffer.from('{"version":1,"coins":["../private"]}')});
    await page.waitForFunction(()=>document.getElementById('toast').textContent.includes('Invalid asset'));assert.equal(await page.locator('#watchCount').textContent(),'1');
    await page.locator('#importFile').setInputFiles({name:'valid.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({version:1,coins:['tether'],settings:{layout:'list',reference:'screened',tf:'7d',filter:'divergence'}}))});
    await page.locator('#confirmImport').click();assert.equal(await page.locator('#watchCount').textContent(),'2');assert.equal(await page.locator('#filterSelect').inputValue(),'all');
    await page.reload();await page.waitForFunction(()=>state.snapshot);assert.equal(await page.locator('#assetList').isVisible(),true);assert.equal(await page.locator('#referenceSelect').inputValue(),'screened');
    fail=true;await page.evaluate(()=>refresh());assert.match(await page.locator('#connectionStatus').textContent(),/interrupted/);
    fail=false;stale=true;
    // Reload clears the in-memory previous snapshot so stale source handling is tested directly.
    await page.reload();await page.waitForFunction(()=>state.snapshot);
    assert.equal(await page.evaluate(()=>C.quoteState(state.snapshot,coins()[0]).usable),false);
    assert.match(await page.locator('#assetRows').textContent(),/Unavailable/);
    stale=false;await page.evaluate(()=>refresh());assert.equal(await page.evaluate(()=>state.analysis.current),true);
    assert.deepEqual(await context.cookies(),[]);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    console.log('PASS: browser FR/EN, 320/390/768/1440, list/search/sort, reference, filter, keyboard, import/export, persistence, outage and recovery, no third-party calls.');
  }catch(error){if(page)await page.screenshot({path:path.join(screenshots,'failure.png'),fullPage:true});throw error;}
  finally{if(browser)await browser.close();server.kill();await fs.rm(tmp,{recursive:true,force:true});}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
