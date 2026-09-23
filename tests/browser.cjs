// Optional browser checks. Start scripts/preview.py first; supply Playwright via NODE_PATH.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const origin = process.env.ORBIT_PREVIEW_URL || 'http://127.0.0.1:8767';
const C = require('../web/core.js');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

async function main(){
  const screenshots=await fs.mkdtemp(path.join(os.tmpdir(),'orbit2-browser-'));
  const browser=await chromium.launch({headless:true});
  try{
    const context=await browser.newContext({viewport:{width:1440,height:950}});
    const page=await context.newPage(),errors=[],external=[];
    if(process.argv[2]){
      const release=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
      for(const [name,body] of Object.entries(release.assets)){
        const type=name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':name.endsWith('.svg')?'image/svg+xml':'text/plain';
        await page.route(origin+'/releases/'+release.revision+'/'+name,r=>r.fulfill({body:Buffer.from(body,'base64'),contentType:type}));
      }
      await page.route(origin+'/web/',r=>r.fulfill({body:release.pages['index.html'],contentType:'text/html'}));
      await page.route(origin+'/web/legal/',r=>r.fulfill({body:release.pages['legal/index.html'],contentType:'text/html'}));
    }
    page.on('pageerror',e=>errors.push(e.message));
    page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
    page.on('request',r=>{if(new URL(r.url()).origin!==origin)external.push(r.url());});
    await page.goto(origin+'/web/');await page.waitForSelector('.coin-choice');
    await page.screenshot({path:path.join(screenshots,'home.png')});
    // Build a real-data watchlist through the actual onboarding controls.
    for(const name of ['Bitcoin','Ethereum','Solana','Chainlink','Uniswap','Aave']){
      await page.locator('#welcomeSearch').fill(name);
      await page.locator('#welcomeResults').getByRole('button',{name:'Add '+name,exact:true}).click();
    }
    assert.equal(await page.locator('#watchCount').textContent(),'6');
    await page.locator('#finishWelcome').click();
    await page.waitForFunction(()=>[...logos.values()].filter(l=>l.ok).length>=6);
    await page.waitForTimeout(400);
    async function geometry(){
      return page.evaluate(()=>{
        const pixels=ctx.getImageData(0,0,canvas.width,canvas.height).data;
        let colored=0;for(let i=3;i<pixels.length;i+=400)if(pixels[i]>0)colored++;
        const overlaps=[];for(const a of rects)for(const b of rects)if(a!==b&&Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x)>.01&&Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y)>.01)overlaps.push([a.id,b.id]);
        return {tiles:rects.length,colored,overlaps,overflow:document.documentElement.scrollWidth>innerWidth,
          maxLogo:Math.max(...rects.map(r=>C.tileContent(r.w,r.h).logo))};
      });
    }
    const desktop=await geometry();assert.equal(desktop.tiles,6);assert.ok(desktop.colored>100);assert.deepEqual(desktop.overlaps,[]);assert.equal(desktop.overflow,false);
    await page.screenshot({path:path.join(screenshots,'desktop.png')});
    // Keyboard navigation and modal focus restore.
    await page.locator('.tile-hit').first().focus();await page.keyboard.press('ArrowRight');await page.keyboard.press('Enter');
    assert.equal(await page.locator('#assetDialog').evaluate(e=>e.open),true);
    await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>document.activeElement.className),'tile-hit');
    await page.locator('[data-tf="7d"]').click();await page.locator('#sizeSelect').selectOption('market_cap');
    await page.reload();await page.waitForSelector('.tile-hit');
    assert.equal(await page.locator('[data-tf="7d"]').getAttribute('aria-pressed'),'true');
    assert.equal(await page.locator('#sizeSelect').inputValue(),'market_cap');
    await page.locator('[data-tf="24h"]').click();await page.locator('#sizeSelect').selectOption('perf');
    await page.locator('#fullscreenBtn').click();await page.waitForFunction(()=>!!document.fullscreenElement);
    await page.locator('#fullscreenBtn').click();await page.waitForFunction(()=>!document.fullscreenElement);
    await page.setViewportSize({width:3840,height:2160});await page.waitForTimeout(400);
    const wide=await geometry();assert.ok(wide.maxLogo>desktop.maxLogo*1.8);assert.equal(wide.overflow,false);assert.deepEqual(wide.overlaps,[]);
    await page.screenshot({path:path.join(screenshots,'wide.png')});
    for(const width of [390,320]){
      await page.setViewportSize({width,height:844});await page.waitForTimeout(200);
      const mobile=await geometry();assert.equal(mobile.overflow,false);assert.deepEqual(mobile.overlaps,[]);assert.ok(mobile.colored>50);
      await page.screenshot({path:path.join(screenshots,'mobile-'+width+'.png'),fullPage:true});
    }
    // Export and import a file locally; malformed imports leave selection untouched.
    await page.locator('#settingsBtn').click();
    const downloaded=page.waitForEvent('download');await page.locator('#exportBtn').click();
    const download=await downloaded,exported=JSON.parse(await fs.readFile(await download.path(),'utf8'));
    assert.equal(exported.coins.length,6);
    await page.locator('#importFile').setInputFiles({name:'bad.json',mimeType:'application/json',buffer:Buffer.from('{"version":1,"coins":["../secret"]}')});
    await page.waitForFunction(()=>document.getElementById('toast').textContent.includes('Invalid coin'));
    assert.equal(await page.locator('#watchCount').textContent(),'6');
    await page.locator('#importFile').setInputFiles({name:'watchlist.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({version:1,coins:['bitcoin','ethereum'],settings:{tf:'24h'}}))});
    await page.waitForFunction(()=>document.getElementById('importDialog').open);
    await page.locator('[name="importMode"][value="replace"]').check();await page.locator('#confirmImport').click();
    assert.equal(await page.locator('#watchCount').textContent(),'2');
    // 50-coin and market views preserve bounded, non-overlapping geometry.
    await page.evaluate(()=>{state.selected=new Set(coins().slice(0,50).map(c=>c.id));save();render();});
    await page.setViewportSize({width:1440,height:950});await page.waitForTimeout(600);
    assert.equal((await geometry()).tiles,50);assert.deepEqual((await geometry()).overlaps,[]);
    await page.evaluate(()=>toggleCoin(coins()[60].id));assert.equal(await page.locator('#watchCount').textContent(),'50');
    await page.screenshot({path:path.join(screenshots,'fifty.png')});
    await page.locator('[data-view="market"]').click();await page.waitForTimeout(300);assert.equal((await geometry()).tiles,100);
    await page.goto(origin+'/web/legal/');await page.setViewportSize({width:390,height:844});
    const legal=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,height:document.documentElement.scrollHeight}));
    assert.equal(legal.overflow,false);assert.ok(legal.height>844);
    await page.evaluate(()=>scrollTo(0,document.documentElement.scrollHeight));assert.ok(await page.evaluate(()=>scrollY)>0);
    assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
    await context.close();

    // Network/freshness failure cases use isolated synthetic data, never the preview source.
    const testContext=await browser.newContext({viewport:{width:1200,height:850}}),testPage=await testContext.newPage();
    const stamp=new Date().toISOString();
    const fixture={snapshot:stamp,coins:Array.from({length:30},(_,i)=>({id:'test-'+i,symbol:'t'+i,name:i===0?'<img src=x onerror=alert(1)>':'Test '+i,current_price:1,market_cap:1000,total_volume:20+i,[C.TF['24h']]:i===0?45:i%7-3,has_logo:false}))};
    let mode='offline';
    await testPage.route('**/data.json',r=>mode==='offline'?r.abort():r.fulfill({json:mode==='stale'?{...fixture,snapshot:'2020-01-01T00:00:00Z'}:fixture}));
    await testPage.goto(origin+'/web/');await testPage.waitForFunction(()=>!state.loading);
    assert.equal(await testPage.locator('#mapMessageTitle').textContent(),'Market data unavailable');
    mode='fresh';await testPage.evaluate(()=>refresh());await testPage.waitForSelector('.coin-choice');
    assert.equal(await testPage.locator('#welcomeResults img[src="x"]').count(),0);
    await testPage.evaluate(()=>{toggleCoin('test-0');state.onboarding=false;render();});
    const signal=await testPage.locator('#signalCount').textContent();assert.ok(Number(signal)>0);
    await testPage.evaluate(()=>{state.selected.add('test-1');render();});
    assert.equal(await testPage.evaluate(()=>eventsFor(byId('test-0')).priceZ),C.analyze(C.normalizeSnapshot(fixture),'24h').byId.get('test-0').priceZ);
    mode='offline';await testPage.evaluate(()=>refresh());assert.equal(await testPage.evaluate(()=>state.snapshot.snapshot),stamp);
    mode='stale';await testPage.evaluate(()=>refresh());assert.equal(await testPage.evaluate(()=>state.snapshot.snapshot),stamp);
    await testPage.evaluate(()=>{state.snapshot.snapshot='2020-01-01T00:00:00Z';render();});
    assert.equal(await testPage.locator('#signalCount').textContent(),'0');assert.match(await testPage.locator('#signalList').textContent(),/Signals paused/);
    await testContext.close();
    console.log(JSON.stringify({result:'PASS',screenshots,desktop,wide,checks:['onboarding','keyboard and focus','preferences','fullscreen','mobile','4K scaling','import/export','50-coin cap','market view','legal scroll','same-origin','XSS input','outage recovery','staleness','snapshot regression']},null,2));
  }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exit(1);});
