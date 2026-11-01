const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
(async()=>{
  const browser = await chromium.launch({headless:true,channel:'msedge'});
  try {
    const context = await browser.newContext();
    const errors=[];
    const prefix='/api/hassio_ingress/test/';
    const panel={id:'study',hostname:'study',room:'Study',claimed:true,online:true,metrics:{},config_version:1};
    await context.route('**/*', async route=>{
      const u=new URL(route.request().url());
      if(u.pathname===prefix) return route.fulfill({path:path.resolve(__dirname,'../server/app/static/index.html'),contentType:'text/html'});
      if(u.pathname===prefix+'management/open') {
        assert.equal(u.searchParams.get('panel'),'study');
        return route.fulfill({status:302,headers:{location:'https://panels.example/management/?panel=study'}});
      }
      if(u.hostname==='panels.example') return route.fulfill({contentType:'text/html',body:'<h1>Secure diagnostics</h1>'});
      const endpoint=u.pathname.slice((prefix+'api/').length);
      if(endpoint==='me') return route.fulfill({json:{authenticated:true,ha_configured:true}});
      if(endpoint==='panels') return route.fulfill({json:[panel]});
      if(endpoint==='panels/study') return route.fulfill({json:{panel,config:{media:{speakers:[]},lights:[],display:{}},history:[],problems:[]}});
      return route.fulfill({json:[]});
    });
    const page=await context.newPage();
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://ha.example'+prefix);
    await page.getByRole('button',{name:'Configure',exact:true}).click();
    await page.locator('#sectNav [data-s="diag"]').click();
    const link=page.locator('#secureDiagnostics');
    await link.waitFor({state:'visible'});
    assert.equal(await link.getAttribute('href'),prefix+'management/open?panel=study');
    assert.equal(await link.getAttribute('target'),'_blank');
    const popupPromise=page.waitForEvent('popup');
    await link.click();
    const popup=await popupPromise;
    await popup.waitForURL('https://panels.example/management/?panel=study');
    assert.equal(await popup.locator('h1').textContent(),'Secure diagnostics');
    assert.deepEqual(errors,[]);
    console.log('PASS full dashboard: selected-device diagnostics link opens a new tab through ingress and HTTPS redirect without JS errors');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
