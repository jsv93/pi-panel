const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),source=fs.readFileSync(path.join(root,'panel-ui/panel.html'),'utf8').replace('panelReady=true;browserHeartbeat();','panelReady=true;browserHeartbeat();window.screenTestEval=code=>eval(code);');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const context=await browser.newContext({viewport:{width:720,height:1280}}),page=await context.newPage(),errors=[],writes=[];
 page.on('pageerror',e=>errors.push(e.message));
 const evaluate=fn=>page.evaluate(code=>window.screenTestEval('('+code+')()'),fn.toString());
 const display={theme:'architectural',palette:'linen',idle_timeout_s:600,adaptive_brightness:true,adaptive_sensor:'sensor.lux',adaptive_min_pct:20,adaptive_max_pct:80,adaptive_dark_lux:0,adaptive_bright_lux:100,adaptive_transition_s:1};
 await page.addInitScript(()=>{
  window.agentReports=[];
  window.WebSocket=class {
   constructor(url){this.url=url;this.readyState=1;setTimeout(()=>{this.onopen?.();if(!url.endsWith('/agent'))this.emit({type:'auth_required'});},0);}
   emit(data){this.onmessage?.({data:JSON.stringify(data)});}
   send(raw){const m=JSON.parse(raw);if(this.url.endsWith('/agent')){window.agentReports.push(m);return;}
    if(m.type==='auth'){setTimeout(()=>this.emit({type:'auth_ok'}),0);return;}
    setTimeout(()=>this.emit({id:m.id,type:'result',success:true,result:m.type==='get_states'?[]:{}}),0);
   }
   close(){this.readyState=3;}
  };
 });
 await page.route('**/*',r=>{
  const u=new URL(r.request().url());
  if(u.pathname==='/panel.html')return r.fulfill({contentType:'text/html',body:source});
  if(u.pathname==='/config.json')return r.fulfill({json:{room_label:'Study',display,lights:[],media:{},sensors:{},connection:{ha_url:'http://ha.test'}}});
  if(u.pathname==='/secrets.json')return r.fulfill({json:{ha_token:'test-only'}});
  if(u.pathname==='/backlight'){writes.push(Number(u.searchParams.get('v')));return r.fulfill({body:'ok'});}
  if(u.pathname.endsWith('.woff2'))return r.fulfill({path:path.join(root,'panel-ui',path.basename(u.pathname))});
  return r.fulfill({json:{}});
 });
 await page.goto('http://panel.test/panel.html');await page.waitForFunction(()=>window.screenTestEval?.('panelReady&&wsReady'));
 assert.equal(await evaluate(()=>adaptiveStatus()),'Waiting for lux sensor · default brightness');
 await evaluate(()=>applyState({entity_id:'sensor.lux',state:'0',attributes:{unit_of_measurement:'lx'}}));
 await page.waitForTimeout(2200);
 assert((await evaluate(()=>panelBrightness()))<=22);
 await evaluate(()=>applyState({entity_id:'sensor.lux',state:'100',attributes:{unit_of_measurement:'lx'}}));
 assert((await evaluate(()=>panelBrightness()))<30,'sensor must not cause an immediate jump');
 await page.waitForTimeout(2200);
 assert((await evaluate(()=>panelBrightness()))>=78);
 await evaluate(()=>applyState({entity_id:'sensor.lux',state:'unavailable',attributes:{unit_of_measurement:'lx'}}));
 assert.match(await evaluate(()=>adaptiveStatus()),/holding/);
 await evaluate(()=>goIdle());await page.waitForTimeout(100);
 assert(writes.at(-1)<=52,'idle dims adaptive brightness');
 await evaluate(()=>goBlank());await page.waitForTimeout(100);const count=writes.length;
 await evaluate(()=>applyState({entity_id:'sensor.lux',state:'0',attributes:{unit_of_measurement:'lx'}}));
 await page.waitForTimeout(2200);assert.equal(writes.at(-1),0);assert.equal(writes.length,count,'sensor must not wake the panel');
 await evaluate(()=>{bump();browserHeartbeat();});await page.waitForTimeout(200);
 assert(writes.at(-1)>0&&writes.at(-1)<60);
 const beat=await evaluate(()=>window.agentReports.filter(x=>x.type==='browser_heartbeat').at(-1));
 assert.equal(beat.screen_mode,'awake');assert.equal(beat.adaptive_lux,0);
 await evaluate(()=>{st.bl=65;adaptiveOverrideUntil=Date.now()+600000;setBacklight(st.bl);});
 await page.waitForTimeout(1100);assert.equal(writes.at(-1),166);assert.match(await evaluate(()=>adaptiveStatus()),/Manual override/);
 assert.deepEqual(errors,[]);
 console.log('PASS panel: smoothed lux response, unavailable sensor, idle/blank/wake, manual override, heartbeat, no JS errors');

 const base=process.env.ADMIN_TEST_URL||'http://127.0.0.1:8877/api/hassio_ingress/testtoken',admin=await browser.newContext({viewport:{width:1280,height:1000}}),api=admin.request;
 assert((await api.post(base+'/api/login',{data:{password:'local-qa-only'}})).ok());
 await api.post(base+'/api/register',{data:{panel_id:'screen-qa',hostname:'Study',kind:'pi'}});
 await api.post(base+'/api/panels/screen-qa/claim',{data:{room:'Study',template:'default'}});
 const original={lights:[{entity_id:'light.study',soft:20}],display:{...display,background:{mode:'room'},future_setting:'preserve'}};
 assert((await api.put(base+'/api/panels/screen-qa/config',{data:original})).ok());
 const q=await admin.newPage();q.on('pageerror',e=>errors.push(e.message));
 await q.goto(base+'/');await q.waitForSelector('#app:visible');await q.evaluate(()=>openPanel('screen-qa'));
 await q.locator('#sectNav [data-s=display]').click();
 assert.equal(await q.locator('#fAdaptiveSensor').inputValue(),'sensor.lux','missing entity assignment retained');
 await q.locator('#fAdaptiveMin').fill('25');await q.locator('#saveScreenBtn').click();
 await q.waitForFunction(()=>!document.querySelector('#saveScreenBtn').disabled);
 let cfg=(await(await api.get(base+'/api/panels/screen-qa')).json()).config;
 assert.equal(cfg.display.adaptive_min_pct,25);assert.equal(cfg.display.theme,'architectural');assert.equal(cfg.display.future_setting,'preserve');assert.deepEqual(cfg.lights,original.lights);
 await q.locator('#fAdaptiveMin').fill('99');await q.locator('#saveScreenBtn').click();
 await q.waitForFunction(()=>!document.querySelector('#saveScreenBtn').disabled);
 assert.match(await q.locator('#screenSaveStatus').textContent(),/minimum/);
 await q.locator('#fAdaptiveMin').fill('25');
 await q.locator('#sectNav [data-s=diag]').click();
 await q.locator('#screenCaptureBtn').click();await q.waitForFunction(()=>!document.querySelector('#screenCaptureBtn').disabled);
 assert.match(await q.locator('#screenDiagnosticStatus').textContent(),/offline/);
 assert.equal(await q.locator('#screenCapture').isVisible(),false);
 assert.deepEqual(errors,[]);
 if(process.env.SCREENSHOTS_DIR){fs.mkdirSync(process.env.SCREENSHOTS_DIR,{recursive:true});await q.locator('#sectNav [data-s=display]').click();await q.screenshot({path:path.join(process.env.SCREENSHOTS_DIR,'screen-settings.png'),fullPage:true});}
 await browser.close();console.log('PASS ingress settings: sensor retention, narrow save, validation feedback, existing config preserved, offline capture');
})().catch(e=>{console.error(e);process.exit(1)});
