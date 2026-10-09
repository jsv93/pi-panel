/* Run against tests/serve_under_ingress.py with media capability fixtures. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('path'),fs=require('fs');
(async()=>{
 const base=process.env.ADMIN_TEST_URL||'http://127.0.0.1:8877/api/hassio_ingress/testtoken';
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL}:{})});
 const context=await browser.newContext({viewport:{width:1300,height:1100}}),api=context.request;
 assert((await api.post(base+'/api/login',{data:{password:'local-qa-only'}})).ok());
 await api.post(base+'/api/register',{data:{panel_id:'media-qa',hostname:'Media QA'}});
 await api.post(base+'/api/panels/media-qa/claim',{data:{room:'Study',template:'default'}});
 await api.put(base+'/api/panels/media-qa/config',{data:{room_label:'Study',media:{default_speaker:'media_player.lamp_ma',speakers:[{entity_id:'media_player.lamp_native',name:'Lamp'}]},display:{theme:'architectural',palette:'linen',touch_gesture:'lights',touch_hold_ms:100}}});
 assert((await api.post(base+'/api/heartbeat',{data:{panel_id:'media-qa',metrics:{}}})).ok());
 const page=await context.newPage(),errors=[],failures=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=400)failures.push(r.url()+' '+r.status());});
 await page.goto(base+'/');await page.waitForSelector('#app:visible');await page.evaluate(()=>openPanel('media-qa'));
 assert.equal(await page.locator('#fGlass').count(),0);
 assert.match(await page.locator('#diagStrip').textContent(),/RAM\s*—/);
 for(const [used,pct,expected] of [[448,43.8,'43.8% · 448 / 1,024 MiB'],[0,0,'0.0% · 0 / 1,024 MiB']]){
  assert((await api.post(base+'/api/heartbeat',{data:{panel_id:'media-qa',metrics:{ram_used_mb:used,ram_total_mb:1024,ram_used_pct:pct}}})).ok());
  await page.evaluate(()=>openPanel('media-qa'));assert((await page.locator('#diagStrip').textContent()).includes(expected));
 }
 await page.locator('#sectNav [data-s=media]').click();
 assert.match(await page.locator('#fSpeaker option[value="media_player.lamp_ma"]').textContent(),/Queue transfer/);
 assert.match(await page.locator('#fSpeaker option[value="media_player.lamp_native"]').textContent(),/Control only/);
 assert.match(await page.locator('#fSpeaker option[value="media_player.offline"]').textContent(),/Offline/);
 assert.match(await page.locator('#speakerCompatibility').textContent(),/Lamp.*Control only/);
 await page.locator('#speakerList select').selectOption('media_player.lamp_ma');
 assert.doesNotMatch(await page.locator('#speakerCompatibility').textContent(),/Control only/);
 await page.locator('#speakerList input').fill('Custom lamp name');await page.locator('#speakerList input').blur();
 await page.locator('#refreshSpeakerCompatibility').click();await page.waitForFunction(()=>!document.querySelector('#refreshSpeakerCompatibility').disabled);
 assert.equal(await page.locator('#speakerList select').inputValue(),'media_player.lamp_ma');assert.equal(await page.locator('#speakerList input').inputValue(),'Custom lamp name');
 await page.locator('#saveBtn').click();await page.waitForFunction(()=>document.querySelector('#toast').textContent.startsWith('Saved'));
 const config=(await (await api.get(base+'/api/panels/media-qa')).json()).config;
 assert.equal(config.media.speakers[0].entity_id,'media_player.lamp_ma');assert.equal(config.display.touch_hold_ms,600);
 if(process.env.SCREENSHOTS_DIR){fs.mkdirSync(process.env.SCREENSHOTS_DIR,{recursive:true});await page.screenshot({path:path.join(process.env.SCREENSHOTS_DIR,'server-transfer-compatibility.png'),fullPage:true});}
 assert.deepEqual(errors,[]);assert.deepEqual(failures,[]);await browser.close();
 console.log('PASS ingress admin: RAM readings including zero/older agent, capability labels, selected-speaker section, live changes, refresh preserves edits, saved config and hold threshold');
})().catch(e=>{console.error(e);process.exit(1)});
