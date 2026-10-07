/* Run with Playwright installed in your test environment (not on the panel).
   NODE_PATH=/path/to/node_modules node tests/test_architectural_theme.cjs
   Uses the shipped panel against a deterministic HA/agent stub. No live devices. */
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'panel-ui/panel.html'),'utf8');
const config={room_label:'Living room',connection:{ha_url:'http://ha.test'},lights:[
 {entity_id:'light.downlights',name:'Downlights',soft:35,bright:90},
 {entity_id:'light.cove',name:'Cove lighting',soft:60,bright:100},
 {entity_id:'light.floor',name:'Floor lamp',soft:45,bright:80,include_presets:false}],
 sensors:{temperature:'sensor.temperature',humidity:'sensor.humidity',climate:'climate.room'},
 media:{speakers:[{entity_id:'media_player.room',name:'Living room'}],default_speaker:'media_player.room'},
 display:{theme:'architectural',palette:'linen',idle_timeout_s:600,glass_tier:3,mini_art:false,hide_nav_on_sheets:true}};
const states=[
 {entity_id:'light.downlights',state:'on',attributes:{brightness:89,supported_color_modes:['color_temp'],color_temp_kelvin:2700}},
 {entity_id:'light.cove',state:'on',attributes:{brightness:153,supported_color_modes:['hs','color_temp'],color_temp_kelvin:3000,hs_color:[40,60],effect_list:['None','Slow glow']}},
 {entity_id:'light.floor',state:'on',attributes:{brightness:115,supported_color_modes:['brightness']}},
 {entity_id:'sensor.temperature',state:'23.4',attributes:{}},
 {entity_id:'sensor.humidity',state:'48',attributes:{}},
 {entity_id:'climate.room',state:'heat',attributes:{temperature:22,min_temp:16,max_temp:28,target_temp_step:.5,current_temperature:23.4}},
 {entity_id:'media_player.room',state:'idle',attributes:{volume_level:.4,supported_features:65535}}];

(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL}:{})});
 let count=0;
 const check=(label)=>{count++;console.log('PASS '+label);};
 async function fixture(cfg,options={}){
  const page=await browser.newPage({viewport:{width:720,height:1280}}), errors=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(({states,services})=>{
   window.testCalls=[];window.testStates=states;
   class FakeSocket{
    constructor(url){this.url=url;this.readyState=1;setTimeout(()=>{this.onopen?.();if(url.includes('/api/websocket')){window.testHA=this;this.emit({type:'auth_required'});}},0);}
    emit(d){this.onmessage?.({data:JSON.stringify(d)});}
    send(raw){const m=JSON.parse(raw);if(!this.url.includes('/api/websocket'))return;
     if(m.type==='auth'){setTimeout(()=>this.emit({type:'auth_ok'}),0);return;}
     if(m.type==='call_service')window.testCalls.push(m);
     if(m.service==='transfer_queue' && window.testHoldTransfer){window.testTransferResult=(error)=>this.emit({type:'result',id:m.id,success:!error,error:{message:error},result:{}});return;}
     const result=m.type==='get_states'?window.testStates:m.type==='get_services'?services:m.type==='media_player/browse_media'?{children:[{title:'Evening',media_class:'playlist',can_expand:true,media_content_id:'evening',media_content_type:'playlist'}]}:{};
     setTimeout(()=>this.emit({type:'result',id:m.id,success:true,result}),0);
    }
    close(){this.readyState=3;}
   }
   window.WebSocket=FakeSocket;
   window.testState=s=>{window.testStates=window.testStates.filter(x=>x.entity_id!==s.entity_id).concat(s);window.testHA.emit({type:'event',event:{event_type:'state_changed',data:{new_state:s}}});};
  },{states:options.states||states,services:options.services??{music_assistant:{transfer_queue:{}}}});
  await page.route('**/*',async r=>{
   const u=new URL(r.request().url());
   if(r.request().method()==='POST')requests.push({path:u.pathname,body:r.request().postDataJSON()});
   if(u.pathname==='/presets')return r.fulfill({json:{changed:2}});
   if(u.pathname==='/panel.html')return r.fulfill({contentType:'text/html',body:source});
   if(u.pathname==='/background-'+'a'.repeat(64)+'.webp')return r.fulfill({contentType:'image/webp',path:path.join(root,'server/app/static/abstract-room.webp')});
   if(u.pathname==='/config.json')return r.fulfill({json:cfg});
   if(u.pathname==='/secrets.json')return r.fulfill({json:{ha_token:'test-only'}});
   if(u.pathname.endsWith('.woff2'))return r.fulfill({path:path.join(root,'panel-ui',path.basename(u.pathname))});
   if(u.pathname==='/wifi')return r.fulfill({json:{connected:true,ssid:'Test',networks:[]}});
   if(u.pathname==='/backlight')return r.fulfill({json:{ok:true}});
   return r.fulfill({json:{ok:true}});
  });
  await page.goto('http://panel.test/panel.html');
  await page.waitForFunction(()=>document.querySelector('#archTemp').textContent==='23.4°');
  await page.evaluate(()=>document.fonts.ready);
  return {page,errors,requests};
 }
 const {page:p,errors,requests}=await fixture(config);
 const open=async(name)=>{await p.locator('[data-sheet="'+name+'"]:visible').first().click();await p.waitForTimeout(260);};
 const back=async()=>{await p.locator('.sheet.on [data-close]').click();await p.waitForTimeout(260);};
 const snap=async(name)=>{if(process.env.SCREENSHOTS_DIR){fs.mkdirSync(process.env.SCREENSHOTS_DIR,{recursive:true});await p.waitForTimeout(220);await p.screenshot({path:path.join(process.env.SCREENSHOTS_DIR,name+'.png')});}};
 assert.deepEqual(await p.locator('.nav button:visible b').allTextContents(),['Scenes','Lights','Climate','Covers']);
 assert.equal(await p.locator('body').evaluate(x=>getComputedStyle(x).color),'rgb(232, 188, 136)');
 assert.equal(await p.locator('#rmTitle').textContent(),'Music');await snap('home');check('navigation order and persistent idle player');
 await p.locator('#archTemp').click();await p.waitForTimeout(260);assert(await p.locator('#s-climate').evaluate(x=>x.classList.contains('on')));
 assert.equal(await p.locator('#s-climate #spTemp').textContent(),'22.0');await p.locator('#spUp').click();
 assert.equal((await p.evaluate(()=>window.testCalls.at(-1))).service_data.temperature,22.5);
 await snap('climate');await back();check('temperature link and shared thermostat action');
 await open('scenes');await snap('scenes');await p.locator('#s-scenes [data-preset=off]').click();
 let calls=await p.evaluate(()=>window.testCalls.filter(x=>x.domain==='light'));assert.equal(calls.length,2);assert(calls.every(x=>x.service==='turn_off'));assert(calls.every(x=>x.service_data.entity_id!=='light.floor'));
 await p.locator('#s-scenes [data-preset=bright]').click();calls=await p.evaluate(()=>window.testCalls.filter(x=>x.domain==='light'));assert.equal(calls.at(-2).service_data.brightness_pct,90);assert.equal(calls.at(-1).service_data.brightness_pct,100);await back();check('scenes preserve light exclusions and correct service calls');
 await open('lights');await snap('lights');await p.locator('[data-arch-light="1"]').click();await p.waitForTimeout(220);await snap('brightness');await p.locator('#archLightMore').click();assert(await p.locator('#ovLight').evaluate(x=>x.classList.contains('on')));await snap('light-detail');await p.locator('#ovLight [data-ov-back]').click();await back();await back();check('per-light controls retained');
 await p.locator('#roomMedia .meta').click();await p.waitForTimeout(260);await snap('music-idle');await p.locator('#pp').click();assert.equal((await p.evaluate(()=>window.testCalls.at(-1))).service,'media_play');
 await p.evaluate(()=>window.testState({entity_id:'media_player.room',state:'playing',attributes:{media_title:'Quiet spaces',media_artist:'Evening collection',media_duration:214,media_position:5,volume_level:.4,supported_features:65535}}));
 await p.locator('#rep').click();await p.locator('#rep').click();assert.equal(await p.locator('#rep').getAttribute('aria-label'),'Repeat one');await snap('music-playing');await back();
 assert.equal(await p.locator('#rmTitle').textContent(),'Quiet spaces');assert.equal(await p.locator('#rmEq i').first().evaluate(el=>getComputedStyle(el).animationName),'eqbar');
 await p.locator('#rmPP').click();assert.equal((await p.evaluate(()=>window.testCalls.at(-1))).service,'media_pause');assert(await p.locator('#roomMedia').isVisible());check('playback, repeat and pause keep media access');
 await p.locator('#roomMedia .meta').click();await p.waitForTimeout(260);await p.locator('#icoSearch').click();await p.waitForTimeout(260);assert.equal(await p.locator('.bitem .n').first().textContent(),'Evening');await p.locator('#bBack').click();await p.waitForTimeout(260);await back();check('media library navigation retained');
 await open('blinds');assert.equal(await p.locator('#coversEmpty').textContent(),'No covers configured');await back();
 await open('room-menu');await snap('menu');await open('settings');await snap('settings');assert(await p.locator('#saveSoftRow').count());assert(await p.locator('#wifiRow').count());await back();await back();check('settings, diagnostics and covers entry retained');
 await p.emulateMedia({reducedMotion:'reduce'});await p.evaluate(()=>window.testState({entity_id:'media_player.room',state:'playing',attributes:{media_title:'Quiet spaces'}}));assert.equal(await p.locator('#rmEq i').first().evaluate(el=>getComputedStyle(el).animationName),'none');check('reduced-motion equalizer');
 for(const [w,h] of [[480,800],[320,610],[720,1280]]){await p.setViewportSize({width:w,height:h});await p.waitForTimeout(80);const bounds=await p.locator('.nav').boundingBox();assert(bounds.x>=-1&&bounds.x+bounds.width<=w+1);assert.equal(await p.locator('.nav button:visible').count(),4);await snap('home-'+w);}
 check('home fits 320/480/720 widths');
 assert.deepEqual(errors,[]);await p.close();
 const edit=await fixture(config),e=edit.page;
 const eback=async()=>{await e.locator('.sheet.on [data-close]').click();await e.waitForTimeout(220);};
 await e.locator('.nav [data-sheet=scenes]').click();await e.waitForTimeout(220);
 assert.equal(await e.locator('#s-scenes').evaluate(x=>getComputedStyle(x).animationName),'arch-page-enter');
 assert.equal(await e.locator('#s-scenes .preset').first().evaluate(x=>getComputedStyle(x,'::before').display),'none');
 await e.locator('#s-scenes [data-sheet=scene-edit]').click();await e.waitForTimeout(220);
 assert.equal(await e.locator('#s-scene-edit .down').getAttribute('data-back-label'),'Scenes');
 if(process.env.SCREENSHOTS_DIR)await e.screenshot({path:path.join(process.env.SCREENSHOTS_DIR,'scene-edit.png')});
 await e.locator('#saveSoftRow').click();assert.deepEqual(edit.requests.at(-1),{path:'/presets',body:{preset:'soft',levels:{'light.downlights':35,'light.cove':60}}});
 await e.route('**/presets',r=>r.fulfill({status:503,json:{error:'Server unavailable'}}));await e.locator('#saveBrightRow').click();await e.waitForTimeout(100);assert.match(await e.locator('#brightV').textContent(),/failed.*Server unavailable/);await e.unroute('**/presets');
 await e.locator('#s-scene-edit [data-sheet=scene-members]').click();await e.waitForTimeout(220);
 await e.locator('#archMembers button').nth(2).click();assert.deepEqual(edit.requests.at(-1),{path:'/light',body:{entity_id:'light.floor',include_presets:true}});await e.waitForFunction(()=>document.querySelectorAll('#archMembers button')[2].getAttribute('aria-pressed')==='true');
 await eback();assert(await e.locator('#s-scene-edit').isVisible());await eback();assert(await e.locator('#s-scenes').isVisible());await eback();
 await e.locator('.nav [data-sheet=lights]').click();await e.waitForTimeout(220);await e.locator('[data-arch-light="1"]').click();await e.waitForTimeout(220);
 await e.locator('#archDimUp').click();assert.equal((await e.evaluate(()=>window.testCalls.at(-1))).service_data.brightness_pct,65);
 const dragBox=await e.locator('#archBrightness').boundingBox();await e.mouse.move(dragBox.x+dragBox.width*.8,dragBox.y+dragBox.height/2);await e.mouse.down();
 await e.evaluate(()=>window.testState({entity_id:'light.cove',state:'on',attributes:{brightness:51,supported_color_modes:['hs','color_temp'],hs_color:[40,60],color_temp_kelvin:3000,effect_list:['None','Slow glow']}}));
 assert.equal(await e.locator('#archBrightnessValue').textContent(),'80');await e.mouse.up();assert.equal((await e.evaluate(()=>window.testCalls.at(-1))).service_data.brightness_pct,80);
 await e.setViewportSize({width:360,height:640});await e.waitForTimeout(100);
 const scaled=await e.locator('#archBrightness').boundingBox();await e.mouse.move(scaled.x+scaled.width*.6,scaled.y+scaled.height/2);await e.mouse.down();
 const knob=await e.locator('#archBrightness .knob').boundingBox();assert(Math.abs(knob.x+knob.width/2-(scaled.x+scaled.width*.6))<2,'scaled slider knob tracks the finger');await e.mouse.up();await e.setViewportSize({width:720,height:1280});await e.waitForTimeout(100);
 await e.locator('#archLightMore').click();await e.waitForTimeout(220);assert.equal(await e.locator('#ovLight .ov-card').evaluate(x=>getComputedStyle(x).borderRadius),'0px');
 await e.locator('#lightBody button').filter({hasText:'Colour'}).click();await e.waitForTimeout(220);assert(await e.locator('#ovColour').isVisible());await e.locator('#archColourHost .sw').first().click();assert.deepEqual((await e.evaluate(()=>window.testCalls.at(-1))).service_data.hs_color,[0,85]);
 await e.locator('#ovColour [data-ov-back]').click();assert(await e.locator('#ovLight').isVisible());await e.locator('#archEffect').selectOption('Slow glow');assert.equal((await e.evaluate(()=>window.testCalls.at(-1))).service_data.effect,'Slow glow');
 await e.locator('#ovLight [data-ov-back]').click();await eback();assert(await e.locator('#s-lights').isVisible());await eback();
 await e.locator('#roomMedia .meta').click();await e.waitForTimeout(220);await e.locator('#shuf').click();assert.equal((await e.evaluate(()=>window.testCalls.at(-1))).service,'shuffle_set');await e.locator('#s-media [data-sheet=playback]').click();await e.waitForTimeout(220);assert.equal(await e.locator('#archShuffle,#archRepeat').count(),0);await e.locator('#archMiniArt').click();assert.equal(await e.locator('#archMiniArt .v').textContent(),'On');await eback();assert(await e.locator('#s-media').isVisible());await eback();
 await e.emulateMedia({reducedMotion:'reduce'});await e.locator('.nav [data-sheet=scenes]').click();assert.equal(await e.locator('#s-scenes').evaluate(x=>getComputedStyle(x).animationName),'none');await eback();
 await e.locator('#archMenu').click();await e.waitForTimeout(220);await e.locator('#archRoomLinks [data-sheet=settings]').click();await e.waitForTimeout(220);await e.locator('#s-settings [data-sheet=display]').click();await e.waitForTimeout(220);await e.locator('#glassRow').click();await e.waitForTimeout(220);
 assert.deepEqual(await e.locator('#archChoices .t').allTextContents(),['Full','No sheet','Tiles only','Off']);await eback();await eback();await e.locator('#s-settings [data-sheet=diagnostics]').click();await e.waitForTimeout(220);await e.locator('#diagRow').click();assert(await e.locator('#scrollTestRow').isVisible());
 assert.deepEqual(edit.errors,[]);await e.close();check('preview navigation, scene capture and failure, membership, drag protection, colour, effects and diagnostics');
 for(const theme of ['default','ambient']){const f=await fixture({...config,display:{...config.display,theme,palette:theme==='ambient'?'ember':'midnight'}});assert.equal(await f.page.locator('.nav button:visible').count(),4);assert.equal(await f.page.locator('.nav [data-sheet=scenes]').isVisible(),false);assert.equal(await f.page.locator('#homeReadings .setpoint').count(),1);assert.deepEqual(f.errors,[]);await f.page.close();check(theme+' navigation and thermostat retained');}
 const empty=await fixture({...config,media:{},sensors:{temperature:'sensor.temperature'},lights:[]});await empty.page.locator('#roomMedia').click();await empty.page.waitForTimeout(260);for(const id of ['pp','prev','next','shuf','rep'])await empty.page.locator('#'+id).click();await empty.page.locator('#icoSearch').click();await empty.page.waitForTimeout(260);assert.equal(await empty.page.locator('#bList').textContent(),'No speakers configured');assert.deepEqual(empty.errors,[]);await empty.page.close();check('unconfigured media does not throw or send commands');
 const pinned=await fixture({...config,display:{...config.display,hide_nav_on_sheets:false}});
 await pinned.page.locator('#roomMedia .meta').click();await pinned.page.waitForTimeout(260);
 assert(await pinned.page.locator('.nav').isVisible());
 const sheetBox=await pinned.page.locator('#s-media').boundingBox(), navBox=await pinned.page.locator('.nav').boundingBox();
 assert(sheetBox.y+sheetBox.height<=navBox.y,'media sheet must stop above the persistent navigation: '+JSON.stringify({sheetBox,navBox}));
 await pinned.page.locator('#icoMore').click();assert(await pinned.page.locator('#ovQueue').evaluate(x=>x.classList.contains('on')));
 await pinned.page.locator('#ovQueue [data-ov-back]').click();
 await pinned.page.locator('.sheet.on [data-close]').click();await pinned.page.waitForTimeout(260);
 await pinned.page.locator('#archMenu').click();await pinned.page.waitForTimeout(260);
 await pinned.page.locator('#s-room-menu [data-sheet=settings]:visible').click();await pinned.page.waitForTimeout(260);
 await pinned.page.locator('#s-settings [data-sheet=display]').click();await pinned.page.waitForTimeout(220);
 await pinned.page.locator('#themeRow').click();await pinned.page.waitForTimeout(220);
 await pinned.page.locator('#archChoices button').filter({hasText:'Default'}).click();
 for(const next of ['default','ambient','architectural']){
  if(next!=='default')await pinned.page.locator('#archChoices button').filter({hasText:next==='ambient'?'Ambient':'Architectural'}).click();
  assert(await pinned.page.locator('body').evaluate((b,t)=>b.classList.contains('theme-'+t),next));
  assert.equal(await pinned.page.locator((next==='architectural'?'#archClimateTarget':'#homeReadings')+' .setpoint').count(),1);
 }
 assert.equal(await pinned.page.locator('#rmTitle').textContent(),'Music');assert.deepEqual(pinned.errors,[]);
 await pinned.page.close();check('persistent navigation, queue access and live theme switching');
 for(const theme of ['default','ambient','architectural']){
  const f=await fixture({...config,display:{...config.display,theme}}),q=f.page;
  if(theme==='architectural'){await q.locator('#archMenu').click();await q.locator('#archRoomLinks [data-sheet=settings]').click();await q.locator('#archSettingsLinks [data-sheet=display]').click();}
  else await q.locator('.nav [data-sheet=settings]').click();
  await q.locator('#paletteRow').click();await q.waitForTimeout(250);
  assert.equal(await q.locator('#archChoices button').count(),6);
  assert.equal(f.requests.filter(r=>r.path==='/display').length,0,'opening a list must not change the selection');
  await q.locator('#archChoices button').filter({hasText:'Ember'}).click();
  assert.deepEqual(f.requests.at(-1),{path:'/display',body:{palette:'ember'}});
  await q.locator('#s-choices [data-close]').click();await q.waitForTimeout(250);assert(await q.locator(theme==='architectural'?'#s-display':'#s-settings').isVisible());
  await q.locator('#themeRow').click();await q.waitForTimeout(250);assert.equal(await q.locator('#archChoices button').count(),3);
  assert.equal(await q.locator('#idle .hint').count(),0);
  assert.equal(await q.locator('#archRoomLinks [data-sheet=blinds],#s-settings [data-sheet=blinds]').count(),0);
  assert.deepEqual(f.errors,[]);await q.close();
 }
 check('theme and colour selection lists in every theme, without cycling on entry');
 for(const [mode,colour] of [['solid','#453020'],['pattern','#2b2018'],['room','#2b2018'],['image','#2b2018']]){
  const f=await fixture({...config,display:{...config.display,background:{mode,colour,image:'a'.repeat(64)}}});
  assert.equal(await f.page.locator('body').getAttribute('data-background'),mode);
  const bg=await f.page.locator('body').evaluate(x=>getComputedStyle(x,'::before').backgroundColor);
  if(mode==='solid')assert.equal(bg,'rgb(69, 48, 32)');
  if(mode==='image')await f.page.waitForFunction(()=>document.body.style.getPropertyValue('--panel-background').includes('background-'));
  assert.deepEqual(f.errors,[]);await f.page.close();
 }
 const missing=await fixture({...config,display:{...config.display,background:{mode:'image',image:'b'.repeat(64)}}});
 assert.equal(await missing.page.locator('body').evaluate(x=>x.style.getPropertyValue('--panel-background')),'var(--arch-room)');assert.deepEqual(missing.errors,[]);await missing.page.close();
 check('background choices and missing-image fallback do not break the panel');
 const transferConfig={...config,media:{default_speaker:'media_player.room',speakers:[
  {entity_id:'media_player.room',name:'Living room'},{entity_id:'media_player.kitchen',name:'Kitchen'},
  {entity_id:'media_player.offline',name:'Offline'},{entity_id:'media_player.cast',name:'Cast speaker'},
  {entity_id:'media_player.group_member',name:'Grouped room'}]}};
 const musicState=(entity_id,state,queue)=>({entity_id,state,attributes:{mass_player_type:'player',active_queue:queue,media_title:state==='playing'?'Evening track':'',volume_level:.4}});
 const transferStates=states.filter(s=>!s.entity_id.startsWith('media_player.')).concat([
  musicState('media_player.room','playing','room-queue'),musicState('media_player.kitchen','idle','kitchen-queue'),
  musicState('media_player.offline','unavailable','offline-queue'),{entity_id:'media_player.cast',state:'idle',attributes:{}},
  musicState('media_player.group_member','playing','room-queue')]);
 const openSpeakers=async page=>{await page.locator('#icoSpk').click();await page.waitForTimeout(260);};
 for(const theme of ['architectural','ambient','default']){
  const f=await fixture({...transferConfig,display:{...config.display,theme}},{states:transferStates}),s=f.page;
  await s.locator('#roomMedia .meta').click();await s.waitForTimeout(260);await openSpeakers(s);
  assert.equal(await s.locator('.spk-transfer').count(),5);
  for(const i of [0,2,3,4])assert(await s.locator('.spk-transfer').nth(i).isDisabled());
  assert(await s.locator('.spk-transfer').nth(1).isEnabled());
  assert.match(await s.locator('.dev').nth(3).textContent(),/Control only/);
  await s.locator('.spk-select').nth(1).click();await s.waitForTimeout(80);
  assert.equal(await s.locator('#spkNow').textContent(),'Kitchen');assert.equal(await s.evaluate(()=>window.testCalls.length),0);
  await openSpeakers(s);await s.locator('.spk-select').first().click();await openSpeakers(s);
  await s.evaluate(()=>window.testHoldTransfer=true);
  await s.locator('.spk-transfer').nth(1).click();
  assert.match(await s.locator('#spkStatus').textContent(),/Transferring to Kitchen/);
  assert.equal(await s.locator('#spkNow').textContent(),'Living room');
  assert(await s.locator('.spk-select').nth(1).isDisabled());assert(await s.locator('.spk-transfer').nth(1).isDisabled());
  await s.locator('.spk-transfer').nth(1).dispatchEvent('click');
  const calls=await s.evaluate(()=>window.testCalls);assert.equal(calls.length,1);
  assert.equal(calls[0].domain,'music_assistant');assert.equal(calls[0].service,'transfer_queue');
  assert.deepEqual(calls[0].target,{entity_id:'media_player.kitchen'});
  assert.deepEqual(calls[0].service_data,{source_player:'media_player.room',auto_play:true});
  await s.evaluate(newState=>{window.testState(newState);window.testTransferResult();},musicState('media_player.kitchen','playing','kitchen-queue'));
  await s.waitForFunction(()=>document.querySelector('#spkNow').textContent==='Kitchen');
  assert.equal(await s.locator('#ovSpk').evaluate(el=>el.classList.contains('on')),false);
  assert.equal(await s.locator('#mTitle').textContent(),'Evening track');
  assert.deepEqual(f.errors,[]);await s.close();
 }
 check('speaker row selection and independent native queue transfer across all themes');
 const tf=await fixture(transferConfig,{states:transferStates}),s=tf.page;
 await s.locator('#roomMedia .meta').click();await s.waitForTimeout(260);await openSpeakers(s);
 await s.evaluate(()=>window.testHoldTransfer=true);await s.locator('.spk-transfer').nth(1).click();
 await s.evaluate(()=>window.testTransferResult('Destination refused transfer'));
 await s.waitForFunction(()=>document.querySelector('#spkStatus').textContent.includes('not confirmed'));
 assert(await s.locator('#ovSpk').isVisible());assert.equal(await s.locator('#spkNow').textContent(),'Living room');
 assert(await s.locator('.spk-transfer').nth(1).isEnabled());
 await s.evaluate(newState=>window.testState(newState),musicState('media_player.room','paused','room-queue'));
 await s.locator('.spk-transfer').nth(1).click();
 assert.equal((await s.evaluate(()=>window.testCalls.at(-1))).service_data.auto_play,false);
 await s.evaluate(()=>window.testTransferResult('Cancelled in test'));await s.waitForTimeout(50);
 for(const newState of [musicState('media_player.room','idle','room-queue'),musicState('media_player.room','playing',null)]){
  await s.evaluate(newState=>window.testState(newState),newState);assert(await s.locator('.spk-transfer').nth(1).isDisabled());
 }
 await s.evaluate(newState=>window.testState(newState),musicState('media_player.room','playing','room-queue'));
 await s.clock.install();await s.locator('.spk-transfer').nth(1).click();await s.clock.runFor(30100);
 assert.match(await s.locator('#spkStatus').textContent(),/not confirmed.*did not respond/);
 assert.equal(await s.locator('#spkNow').textContent(),'Living room');
 await s.evaluate(()=>window.testTransferResult());assert.equal(await s.locator('#spkNow').textContent(),'Living room','late ACK must not change the selected speaker');
 await s.locator('.spk-transfer').nth(1).click();await s.evaluate(()=>window.testHA.onclose());
 await s.waitForTimeout(50);assert.match(await s.locator('#spkStatus').textContent(),/not confirmed.*disconnected/);
 assert(await s.locator('.spk-transfer').nth(1).isDisabled());assert.deepEqual(tf.errors,[]);await s.close();
 check('transfer failures, paused queues, empty sources, timeouts and disconnects');
 const noTransfer=await fixture(transferConfig,{states:transferStates,services:{}});
 await noTransfer.page.locator('#roomMedia .meta').click();await noTransfer.page.waitForTimeout(260);await openSpeakers(noTransfer.page);
 assert(await noTransfer.page.locator('.spk-transfer').nth(1).isDisabled());assert(await noTransfer.page.locator('.spk-select').nth(1).isEnabled());await noTransfer.page.close();
 const touch=await fixture(transferConfig,{states:transferStates});await touch.page.locator('#roomMedia .meta').click();await touch.page.waitForTimeout(260);await openSpeakers(touch.page);
 for(const [width,height] of [[720,1280],[480,800],[360,640]]){
  await touch.page.setViewportSize({width,height});await touch.page.waitForTimeout(100);
  const name=await touch.page.locator('.spk-select').nth(1).boundingBox(),button=await touch.page.locator('.spk-transfer').nth(1).boundingBox();
  assert(button.width>=43.9 && button.height>=43.9,'44px transfer touch target at minimum scale');
  assert(button.x>=name.x+name.width+7.9,'separate touch targets');assert(button.x+button.width<=width);
 }
 if(process.env.SCREENSHOTS_DIR){fs.mkdirSync(process.env.SCREENSHOTS_DIR,{recursive:true});await touch.page.setViewportSize({width:720,height:1280});await touch.page.screenshot({path:path.join(process.env.SCREENSHOTS_DIR,'speaker-transfer.png')});}
 assert.deepEqual(touch.errors,[]);await touch.page.close();check('transfer capability gating and touch layout');
 const player=await fixture(config),q=player.page;
 await q.locator('#roomMedia .meta').click();await q.waitForTimeout(250);
 for(const [width,height] of [[720,1280],[480,800],[360,640]]){
  await q.setViewportSize({width,height});await q.waitForTimeout(100);
  const art=await q.locator('#mpArt').boundingBox(),volume=await q.locator('.mp-vol').boundingBox(),bottom=await q.locator('.mp-bottom').boundingBox(),transport=await q.locator('.mp-transport').boundingBox();
  assert(Math.abs(art.x+art.width/2-width/2)<2,'album is centred');assert(Math.abs(art.width-art.height)<2,'album stays square');
  assert(volume.y>=transport.y+transport.height-1,'volume below transport');
  assert(volume.y+volume.height<=bottom.y+1,'volume above navigation');
  assert(bottom.y+bottom.height<=height+1,'bottom controls fit');
  assert(await q.locator('.mp-vol>svg').isVisible());assert.equal(await q.locator('#archVolumeLabel').count(),0);
 }
 assert.deepEqual(player.errors,[]);await q.close();check('centred album art and bottom volume at panel sizes');
 const sliderPage=await browser.newPage();
 await sliderPage.route('**/*',r=>r.fulfill({contentType:'text/html',body:r.request().url().endsWith('panel.html')?source:fs.readFileSync(path.join(__dirname,'test_slider_drag.html'),'utf8')}));
 await sliderPage.goto('http://panel.test/test_slider_drag.html');
 await sliderPage.waitForFunction(()=>document.querySelector('#out').textContent.includes('passed'));
 const sliderResult=await sliderPage.locator('#out').textContent();assert(!sliderResult.includes('FAIL'),sliderResult);console.log(sliderResult);await sliderPage.close();
 await browser.close();console.log(count+' checks passed');
})().catch(e=>{console.error(e);process.exit(1)});
