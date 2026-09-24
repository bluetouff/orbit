// Real static documentation, including no-JavaScript reading and language navigation.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path');
const base=new URL(process.env.ORBIT_DOCS_URL||'http://127.0.0.1:8767/web/docs/');
(async()=>{
  const screenshots=await fs.mkdtemp(path.join(os.tmpdir(),'orbit2-docs-'));
  const browser=await chromium.launch({headless:true});
  try{
    const context=await browser.newContext({javaScriptEnabled:false}),page=await context.newPage(),external=[],errors=[];
    page.on('request',r=>{if(new URL(r.url()).origin!==base.origin)external.push(r.url());});
    page.on('pageerror',e=>errors.push(e.message));
    for(const lang of ['fr','en']){
      const url=new URL(lang==='fr'?'./':'en/',base).href;
      const response=await page.goto(url);assert.equal(response.status(),200);
      assert.equal(await page.locator('html').getAttribute('lang'),lang);
      assert.equal(await page.locator('h1').count(),1);
      assert.equal(await page.locator('.docs-section').count(),6);
      assert.equal(await page.locator('script').count(),0);
      assert.equal(await page.locator('a[aria-current="page"]').getAttribute('lang'),lang);
      for(const [width,height]of [[1440,950],[768,1024],[390,844],[320,568]]){
        await page.setViewportSize({width,height});
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${lang} overflow at ${width}`);
        await page.screenshot({path:path.join(screenshots,`guide-${lang}-${width}.png`),fullPage:true});
      }
      await page.locator('.docs-toc a[href="#docs-xstocks"]').click();
      assert.equal(new URL(page.url()).hash,'#docs-xstocks');
      assert.ok(await page.evaluate(()=>scrollY)>0);
      await page.keyboard.press('Tab');
      const links=await page.locator('a[href]').evaluateAll(as=>as.map(a=>({raw:a.getAttribute('href'),url:a.href})));
      for(const link of links){
        if(link.raw.startsWith('#'))assert.equal(await page.locator(link.raw).count(),1);
        else if(new URL(link.url).origin===base.origin){
          const response=await context.request.get(link.url);assert.equal(response.status(),200,link.url);
        }
      }
      const opposite=lang==='fr'?'en':'fr';
      await page.locator(`.docs-languages a[lang="${opposite}"]`).click();
      assert.equal(await page.locator('html').getAttribute('lang'),opposite);
    }
    assert.deepEqual(await context.cookies(),[]);assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
    await context.close();
    const interactive=await browser.newContext({locale:'fr-FR'}),app=await interactive.newPage();
    await app.goto(new URL('../legal/',base).href);
    assert.equal(new URL(await app.locator('[data-docs]').getAttribute('href'),app.url()).pathname,base.pathname);
    await app.locator('[data-lang="en"]').click();
    await app.locator('[data-docs]').click();assert.equal(await app.locator('html').getAttribute('lang'),'en');
    await interactive.close();
    console.log(JSON.stringify({result:'PASS',languages:['fr','en'],widths:[320,390,768,1440],noJavaScript:true,cookies:0,external:[],screenshots},null,2));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
