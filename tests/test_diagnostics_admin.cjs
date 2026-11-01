/* Real ingress UI with tests/serve_diagnostics_under_ingress.py fixtures. */
const {chromium}=require('playwright'),assert=require('node:assert/strict');
(async()=>{
 const base=process.env.ADMIN_TEST_URL||'http://127.0.0.1:8878/api/hassio_ingress/testtoken';
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'msedge'});
 const context=await browser.newContext({viewport:{width:1280,height:1000}}),api=context.request;
 assert((await api.post(base+'/api/login',{data:{password:'local-qa-only'}})).ok());
 const detail=(await (await api.get(base+'/api/panels/diagnostics-qa')).json());
 assert((await api.put(base+'/api/panels/diagnostics-qa/config',{data:detail.config})).ok());
 const page=await context.newPage(),errors=[],requests=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
 await page.goto(base+'/');await page.waitForSelector('#app:visible');
 await page.locator('[data-open="diagnostics-qa"]').click();
 await page.locator('#fRoomLabel').fill('Unsaved room label');
 await page.locator('#sectNav [data-s=diag]').click();
 await page.waitForResponse(r=>r.url().includes('/performance?period=live')&&r.ok());
 assert.equal(await page.locator('#performanceCards .perf-card').count(),4);
 assert.equal(await page.locator('[data-period]').count(),4);
 assert.equal(await page.locator('.sect[data-s=diag] input[type=range]').count(),0);
 for(const range of ['15m','1h','24h']){
  const response=page.waitForResponse(r=>r.url().endsWith('/performance?period='+range)&&r.ok());
  await page.locator('[data-period="'+range+'"]').click();await response;
  await page.waitForFunction(p=>document.querySelector('[data-period="'+p+'"]').getAttribute('aria-pressed')==='true',range);
 }
 assert.equal(await page.locator('#pc-cpu_usage_pct').getAttribute('viewBox'),'0 0 370 145');
 await page.locator('#historySelect').selectOption('1');await page.locator('#historyRestore').click();
 assert.match(await page.locator('#mTitle').textContent(),/Restore v1/);
 await page.keyboard.press('Escape');assert.equal(await page.locator('#modal').isVisible(),false);
 await page.locator('#sectNav [data-s=identity]').click();assert.equal(await page.locator('#fRoomLabel').inputValue(),'Unsaved room label');
 await page.locator('#sectNav [data-s=access]').click();await page.waitForFunction(()=>!document.querySelector('#accessAdd').disabled);
 assert.equal(await page.locator('#accessCommand').textContent(),'ssh joel@192.0.2.15');
 assert.equal(await page.locator('[data-remove-key]').count(),1); // managed server key is protected
 await page.locator('#accessAdd').click();await page.locator('#mOk').click();
 assert.match(await page.locator('#accessFormError').textContent(),/Enter a computer name/);
 await page.locator('#mCancel').click();
 await page.locator('#navSettings').click();
 await page.getByRole('button',{name:'Appearance',exact:true}).click();
 assert.equal(await page.locator('#sGuiTheme').isVisible(),true);
 await page.locator('#navFleet').click();await page.locator('[data-open="diagnostics-qa"]').click();
 await page.locator('#sectNav [data-s=diag]').click();await page.setViewportSize({width:390,height:844});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth));
 await page.locator('#sectNav [data-s=access]').click();
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth));
 assert(!requests.some(u=>new URL(u).pathname.startsWith('/api/panels')),'requests must retain ingress prefix');
 assert.deepEqual(errors,[]);await browser.close();
 console.log('PASS ingress UI: shared navigation, four ranges, no sample slider, history confirmation, preserved edits, access form, protected keys, settings navigation and mobile overflow');
})().catch(e=>{console.error(e);process.exit(1)});
