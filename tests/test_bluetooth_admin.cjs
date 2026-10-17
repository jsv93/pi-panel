const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
(async()=>{
 const base=process.env.ADMIN_TEST_URL||'http://127.0.0.1:8877/api/hassio_ingress/testtoken';
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'msedge'});
 const context=await browser.newContext({viewport:{width:1300,height:1050}}),api=context.request;
 assert((await api.post(base+'/api/login',{data:{password:'local-qa-only'}})).ok());
 await api.post(base+'/api/register',{data:{panel_id:'bluetooth-qa',hostname:'Study',kind:'pi',ip:'192.168.1.159'}});
 await api.post(base+'/api/panels/bluetooth-qa/claim',{data:{room:'Study',template:'default'}});
 const initial={lights:[{entity_id:'light.study',soft:17}],display:{theme:'architectural'},media:{default_speaker:'media_player.lamp_ma'}};
 await api.put(base+'/api/panels/bluetooth-qa/config',{data:initial});
 await api.post(base+'/api/heartbeat',{data:{panel_id:'bluetooth-qa',metrics:{}}});
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/');await page.waitForSelector('#app:visible');await page.evaluate(()=>openPanel('bluetooth-qa'));
 await page.locator('#sectNav [data-s=tracking]').click();
 assert.equal(await page.locator('#fBluetoothMode').inputValue(),'existing');
 assert.match(await page.locator('#bluetoothStatus').textContent(),/No recent scanner report/);
 for(const mode of ['on','off','existing']){
  await page.locator('#fBluetoothMode').selectOption(mode);await page.locator('#saveBluetoothBtn').click();
  await page.waitForFunction(()=>!document.querySelector('#saveBluetoothBtn').disabled);
  const cfg=(await(await api.get(base+'/api/panels/bluetooth-qa')).json()).config;
  assert.equal(cfg.bluetooth.mode,mode);assert.deepEqual(cfg.lights,initial.lights);assert.equal(cfg.media.default_speaker,initial.media.default_speaker);
 }
 await api.post(base+'/api/heartbeat',{data:{panel_id:'bluetooth-qa',metrics:{bluetooth_sample_at:Date.now()/1000,bluetooth_status:'Running',bluetooth_service:'study-bt-proxy.service',bluetooth_boot:'enabled',bluetooth_adapter:'hci0',bluetooth_memory_mb:32.5}}});
 await page.locator('#fBluetoothMode').selectOption('on');
 await page.locator('#refreshBluetoothBtn').click();await page.waitForFunction(()=>!document.querySelector('#refreshBluetoothBtn').disabled);
 assert.match(await page.locator('#bluetoothStatus').textContent(),/Running/);assert.match(await page.locator('#bluetoothStatus').textContent(),/32.5 MiB/);
 assert.equal(await page.locator('#fBluetoothMode').inputValue(),'on','status refresh must preserve unsaved selection');
 assert.match(await page.locator('#bluetoothEspLink').getAttribute('href'),/\/config\/integrations\/integration\/esphome$/);
 assert.match(await page.locator('#bluetoothPanelLink').getAttribute('href'),/\/pi_panel$/);
 if(process.env.SCREENSHOTS_DIR){fs.mkdirSync(process.env.SCREENSHOTS_DIR,{recursive:true});await page.screenshot({path:path.join(process.env.SCREENSHOTS_DIR,'server-room-detection.png'),fullPage:true});}
 assert.deepEqual(errors,[]);await browser.close();console.log('PASS ingress UI: legacy state, management modes, narrow saving, status refresh, edit preservation and HA links');
})().catch(error=>{console.error(error);process.exit(1)});
