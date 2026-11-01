const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{
 const base='http://127.0.0.1:8877/api/hassio_ingress/testtoken';
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
 const context=await browser.newContext({viewport:{width:1300,height:1000}}),api=context.request;
 assert((await api.post(base+'/api/login',{data:{password:'local-qa-only'}})).ok());
 await api.post(base+'/api/register',{data:{panel_id:'doorbell-qa',hostname:'Doorbell QA'}});
 await api.post(base+'/api/panels/doorbell-qa/claim',{data:{room:'Study',template:'default'}});
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/');await page.waitForSelector('#app:visible');await page.evaluate(()=>openPanel('doorbell-qa'));
 await page.locator('#sectNav [data-s=doorbell]').click();
 await page.locator('#fBellEnabled').selectOption('1');await page.locator('#fBellCamera').selectOption('camera.test');
 await page.locator('#fBellTrigger').selectOption('binary_sensor.ring');await page.locator('#fBellTitle').fill('Front door');
 await page.locator('#fBellDuration').selectOption('60');await page.locator('#saveBtn').click();
 await page.waitForFunction(()=>document.querySelector('#toast').textContent.startsWith('Saved'));
 const config=(await (await api.get(base+'/api/panels/doorbell-qa')).json()).config;
 assert.deepEqual(config.doorbell,{enabled:true,camera:'camera.test',trigger:'binary_sensor.ring',title:'Front door',duration_s:60});
 await page.locator('#sectNav [data-s=doorbell]').click();await page.locator('#testDoorbellBtn').click();
 await page.waitForFunction(()=>document.querySelector('#doorbellStatus').textContent.includes('offline'));
 assert.match(await page.locator('#doorbellEventData').textContent(),/doorbell-qa/);
 await page.screenshot({path:path.resolve(__dirname,'../../doorbell-settings-test.png'),fullPage:true});
 assert.deepEqual(errors,[]);console.log('PASS real ingress: left navigation, selectors, save/reload, test endpoint and offline error');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
