const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../server/app/static/management');
const prefix = '/api/hassio_ingress/testtoken/management/';
(async () => {
  const browser = await chromium.launch({headless:true, channel:'msedge'});
  try {
    const context = await browser.newContext({viewport:{width:1280,height:1000}});
    const page = await context.newPage(), errors = [], requests = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', async route => {
      const req = route.request(), u = new URL(req.url());
      assert(u.pathname.startsWith(prefix), 'all URLs must preserve ingress prefix');
      const relative = u.pathname.slice(prefix.length);
      if (relative.startsWith('api/')) {
        requests.push({path:relative, body:req.postDataJSON(), headers:req.headers()});
        if (relative === 'api/session') return route.fulfill({json:{session:'test-session',panel:'study-7543',expires_in:600,idle_timeout:120}});
        if (relative === 'api/logout') return route.fulfill({json:{ok:true}});
        return route.fulfill({json:{panel:'study-7543',metrics:{cpu_temp:64,ram_used_mb:580,browser_health:'Healthy',test_text:'<img src=x onerror=alert(1)>'}}});
      }
      const name = relative || 'index.html';
      assert(['index.html','console.js','console.css'].includes(name));
      return route.fulfill({path:path.join(root,name),contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html',
        headers:name === 'index.html'?{'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'"}:{}});
    });
    await page.goto('https://panels.example' + prefix + '?panel=study-7543');
    assert.equal(await page.locator('#panel').inputValue(),'study-7543');
    await page.locator('#user').fill('joel');
    await page.locator('#key').fill('test-operator-key');
    await page.locator('#key').press('Enter');
    await page.waitForSelector('#session:visible');
    await page.waitForFunction(()=>document.activeElement.id==='connection');
    assert.equal(await page.locator('#key').inputValue(),'');
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(()=>document.activeElement.id),'health');
    await page.keyboard.press('Enter');
    await page.waitForFunction(()=>document.getElementById('output').textContent.includes('64'));
    assert.equal(await page.locator('#output img').count(),0);
    assert.equal(await page.evaluate(()=>localStorage.length+sessionStorage.length),0);
    const health = requests.find(r=>r.path.endsWith('/diagnostic'));
    assert.equal(health.headers.authorization,'Bearer test-session');
    assert.equal(health.headers.origin,'https://panels.example');
    assert.deepEqual(health.body,{operation:'health'});
    if (process.env.MANAGEMENT_SCREENSHOT) {
      await page.evaluate(() => {
        const output = document.getElementById('output');
        const data = JSON.parse(output.textContent);
        delete data.metrics.test_text;
        output.textContent = JSON.stringify(data, null, 2);
        document.getElementById('status').textContent = 'Preview with simulated diagnostic data. Not connected to a live panel.';
      });
      await page.screenshot({path:process.env.MANAGEMENT_SCREENSHOT,fullPage:true});
    }
    for (const width of [375,820,1280]) {
      await page.setViewportSize({width,height:900});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no horizontal page overflow at '+width);
    }
    await page.emulateMedia({colorScheme:'dark',reducedMotion:'reduce'});
    await page.locator('#close').click();
    await page.waitForSelector('#login:visible');
    assert.equal(await page.locator('#output').textContent(),'Choose a check to begin.');
    assert(requests.some(r=>r.path==='api/logout'));
    await page.goto('http://panels.example' + prefix);
    assert(await page.locator('#open').isDisabled());
    assert.deepEqual(errors,[]);
    console.log('PASS console: ingress URLs, CSP, keyboard sign-in/check/logout, no credential storage, output escaping, responsive sizes, HTTP refusal, no JS errors');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1);});
