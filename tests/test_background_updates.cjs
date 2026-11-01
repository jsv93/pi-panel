/* Exercise the shipped page: hidden rendering stops, state and wake keep working. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'panel-ui/panel.html'),'utf8').replace('panelReady=true;browserHeartbeat();','panelReady=true;browserHeartbeat();window.backgroundTest=code=>eval(code);');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'msedge'});
 try{
  for(const theme of ['architectural','ambient','default']){
   const page=await browser.newPage({viewport:{width:720,height:1280}}),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   const run=fn=>page.evaluate(code=>window.backgroundTest('('+code+')()'),fn.toString());
   await page.clock.install({time:new Date('2026-11-01T12:34:20')});
   await page.addInitScript(()=>{
    window.reports=[];
    window.WebSocket=class{
     constructor(url){this.url=url;this.readyState=1;setTimeout(()=>{this.onopen?.();if(url.endsWith('/api/websocket'))this.emit({type:'auth_required'});},0);}
     emit(data){this.onmessage?.({data:JSON.stringify(data)});}
     send(raw){const m=JSON.parse(raw);if(this.url.endsWith('/agent')){window.reports.push(m);return;}
      setTimeout(()=>this.emit(m.type==='auth'?{type:'auth_ok'}:{id:m.id,type:'result',success:true,result:m.type==='get_states'?[]:{}}),0);
     }
     close(){this.readyState=3;}
    };
   });
   await page.route('**/*',r=>{
    const u=new URL(r.request().url());
    if(u.pathname==='/panel.html')return r.fulfill({contentType:'text/html',body:source});
    if(u.pathname==='/config.json')return r.fulfill({json:{room_label:'Study',display:{theme,idle_timeout_s:600,backlight_off_s:90},lights:[{entity_id:'light.test',name:'Test light'}],sensors:{temperature:'sensor.temp'},media:{speakers:[{entity_id:'media_player.room',name:'Study'}],default_speaker:'media_player.room'},connection:{ha_url:'http://ha.test'}}});
    if(u.pathname==='/secrets.json')return r.fulfill({json:{ha_token:'fixture'}});
    if(u.pathname.endsWith('.woff2'))return r.fulfill({path:path.join(root,'panel-ui',path.basename(u.pathname))});
    return r.fulfill({json:{}});
   });
   await page.goto('http://panel.test/panel.html');await page.waitForFunction(()=>window.backgroundTest?.('panelReady&&wsReady'));
   await page.clock.pauseAt(new Date('2026-11-01T12:34:25'));
   await run(()=>{
    st.playing=true;st.dur=600;st.pos=40;st.posAt=Date.now();paintAll();showSheet('media');
    window.mutations={clock:0,media:0,uptime:0};window.observers=[];window.resetMutations=()=>{window.observers.forEach(o=>o.takeRecords());window.mutations={clock:0,media:0,uptime:0};};
    const watch=(selectors,key)=>selectors.forEach(selector=>{const observer=new MutationObserver(rs=>window.mutations[key]+=rs.length);observer.observe($(selector),{attributes:true,childList:true,characterData:true,subtree:true});window.observers.push(observer);});
    watch(['#clock','#idleClock','#datestr','#archClock','#archDate'],'clock');
    watch(['#mFill','#mBar','#mElapsed','#stripProg','.mp-wave'],'media');watch(['#sUp'],'uptime');
   });
   await page.clock.runFor(2000);
   assert((await page.locator('#mBar').getAttribute('aria-valuenow'))>=42);
   assert.equal(await page.evaluate(()=>window.mutations.clock),0,'unchanged clock does not repaint each second');
   assert.equal(await page.evaluate(()=>window.mutations.uptime),0,'hidden uptime does not repaint');
   await run(()=>{showSheet('lights');window.resetMutations();});await page.clock.runFor(1500);
   assert.equal(await page.evaluate(()=>window.mutations.media),0,'hidden player does not tick on another page');
   await run(()=>showSheet('media'));assert(Number(await page.locator('#mBar').getAttribute('aria-valuenow'))>=43,'opening player catches up immediately');
   await run(()=>{st.playing=false;paintAll();window.resetMutations();});await page.clock.runFor(1500);
   assert.equal(await page.evaluate(()=>window.mutations.media),0,'paused playback has no progress timer');
   await run(()=>{st.playing=true;paintAll();diag=true;applyDiag();goIdle();window.resetMutations();});
   const beforeClock=await page.locator('#idleClock').textContent();await page.clock.runFor(35000);
   assert.notEqual(await page.locator('#idleClock').textContent(),beforeClock,'visible standby clock keeps time');
   assert.equal(await page.evaluate(()=>window.mutations.media),0,'standby does not update hidden media');
   assert.equal(await run(()=>fpsOn),false,'diagnostic frame loop stops while asleep');
   await run(()=>{goBlank();window.resetMutations();});
   const reports=await page.evaluate(()=>window.reports.length);
   await run(()=>{
    applyState({entity_id:'sensor.temp',state:'25.5',attributes:{}});
    applyState({entity_id:'media_player.room',state:'playing',attributes:{media_title:'Updated while asleep',media_duration:600,media_position:100,media_position_updated_at:new Date().toISOString()}});paintAll();
   });
   await page.clock.runFor(65000);
   assert.equal(await page.evaluate(()=>window.mutations.clock),0,'blanked clocks do not repaint');
   assert.equal(await page.evaluate(()=>window.mutations.media),0,'blanked media does not repaint');
   assert((await page.evaluate(()=>window.reports.length))>reports,'agent heartbeat continues while blanked');
   assert.equal(await run(()=>panelReady),true);
   await run(()=>bump());
   assert.equal(await page.locator('#mTitle').textContent(),'Updated while asleep');
   assert.equal(await page.locator('#archTemp').textContent(),'25.5°');
   assert.equal(await page.locator('#clock').textContent(),await run(()=>new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',hour12:false})));
   await run(()=>showSheet('media'));assert(Number(await page.locator('#mBar').getAttribute('aria-valuenow'))>=165,'wake uses elapsed playback time');
   assert.equal(await run(()=>fpsOn),true,'diagnostics resumes on wake');
   await run(()=>{window.testHidden=true;Object.defineProperty(document,'hidden',{configurable:true,get:()=>window.testHidden});document.dispatchEvent(new Event('visibilitychange'));window.resetMutations();});
   await page.clock.runFor(65000);
   assert.equal(await page.evaluate(()=>window.mutations.media+window.mutations.clock),0,'hidden document has no clock or progress writes');
   await run(()=>{window.testHidden=false;document.dispatchEvent(new Event('visibilitychange'));});
   assert(Number(await page.locator('#mBar').getAttribute('aria-valuenow'))>=230,'visible document catches up');
   assert.equal(await run(()=>fpsOn),true);
   await run(()=>{openLight(0);goIdle();applyState({entity_id:'light.test',state:'on',attributes:{brightness:180,supported_color_modes:['color_temp'],effect_list:['New effect']}});bump();});
   assert.match(await page.locator('#lightBody').textContent(),/New effect/,'open light controls refresh after standby');
   assert.deepEqual(errors,[]);await page.close();
   console.log('PASS '+theme+': clock cadence, visible-only media, idle/blank/wake, current state, heartbeat, visibility and diagnostic frame loop');
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
