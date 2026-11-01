const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),source=fs.readFileSync(path.join(root,'panel-ui/panel.html'),'utf8').replace('panelReady=true;browserHeartbeat();','panelReady=true;browserHeartbeat();window.bellTest=code=>eval(code);');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'msedge'});
 try{for(const theme of ['architectural','ambient','default']){
  const page=await browser.newPage({viewport:{width:720,height:1280}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.clock.install();
  await page.addInitScript(()=>{
   window.sent=[];window.peers=[];window.supported=true;
   window.RTCPeerConnection=class{
    constructor(){window.peers.push(this);this.closed=false;this.remoteDescription=null;}
    addTransceiver(){} async createOffer(){return {type:'offer',sdp:'fixture'};}async setLocalDescription(){}
    async setRemoteDescription(s){this.remoteDescription=s;}async addIceCandidate(){if(!this.remoteDescription)throw Error('candidate before answer');}
    close(){this.closed=true;}
   };
   window.WebSocket=class{
    constructor(url){this.url=url;this.readyState=1;setTimeout(()=>{this.onopen?.();if(url.endsWith('/api/websocket'))this.emit({type:'auth_required'});},0);}
    emit(data){this.onmessage?.({data:JSON.stringify(data)});}
    send(raw){const m=JSON.parse(raw);window.sent.push(m);if(this.url.endsWith('/agent'))return;
     setTimeout(()=>this.emit(m.type==='auth'?{type:'auth_ok'}:{id:m.id,type:'result',success:true,result:m.type==='get_states'?[]:m.type==='camera/capabilities'?{frontend_stream_types:window.supported?['web_rtc']:[]}:{}}),0);
    }close(){this.readyState=3;}
   };
  });
  await page.route('**/*',r=>{
   const u=new URL(r.request().url());if(u.pathname==='/panel.html')return r.fulfill({contentType:'text/html',body:source});
   if(u.pathname==='/config.json')return r.fulfill({json:{_panel_id:'p1',room_label:'Study',display:{theme,idle_timeout_s:1,backlight_off_s:1},doorbell:{enabled:true,camera:'camera.test',duration_s:30,trigger:'binary_sensor.ring'},connection:{ha_url:'http://ha.test'}}});
   if(u.pathname==='/secrets.json')return r.fulfill({json:{ha_token:'fixture'}});
   if(u.pathname.endsWith('.woff2'))return r.fulfill({path:path.join(root,'panel-ui',path.basename(u.pathname))});return r.fulfill({json:{}});
  });
  await page.goto('http://panel.test/panel.html');await page.waitForFunction(()=>window.bellTest?.('panelReady&&wsReady'));
  const run=code=>page.evaluate(code=>window.bellTest(code),code);
  await run(`goIdle();goBlank();ringEvent({event_type:'pi_panel_doorbell',data:{panel_id:'other'}})`);
  assert(await page.locator('#doorbellPopup').isHidden());
  await run(`ringEvent({event_type:'pi_panel_doorbell',data:{panel_id:'p1',test:true}})`);
  await page.waitForFunction(()=>window.sent.some(m=>m.type==='camera/webrtc/offer'));
  assert(await page.locator('#doorbellPopup').isVisible());assert.equal(await run(`$('#idle').classList.contains('on')`),false);
  await run(`cameraSubscriptions.get(bellSession.subscription)({type:'candidate',candidate:{candidate:'fixture'}});cameraSubscriptions.get(bellSession.subscription)({type:'answer',answer:'fixture'});`);
  await page.clock.runFor(2000);assert.equal(await run('!!bellSession'),true,'idle timer does not blank active doorbell');
  await run(`$('#doorbellVideo').onplaying();openDoorbell()`);assert.equal(await page.evaluate(()=>window.peers.length),1,'repeat reuses decoder');
  await page.screenshot({path:path.resolve(root,'../../outputs/doorbell-'+theme+'-test.png')});
  await page.clock.runFor(30100);assert(await page.locator('#doorbellPopup').isHidden());
  assert(await page.evaluate(()=>window.peers.every(p=>p.closed)));assert.equal(await run('cameraSubscriptions.size'),0);
  assert(await page.evaluate(()=>window.sent.some(m=>m.type==='unsubscribe_events')));
  assert.equal(await run(`$('#doorbellVideo').srcObject`),null);
  await run(`ringEvent({event_type:'state_changed',data:{entity_id:'binary_sensor.ring',old_state:{state:'off'},new_state:{state:'on'}}})`);
  await page.waitForFunction(()=>window.peers.length===2);await page.locator('#doorbellClose').click();
  assert(await page.locator('#doorbellPopup').isHidden());assert(await page.evaluate(()=>window.peers.every(p=>p.closed)));
  await page.evaluate(()=>window.supported=false);await run('openDoorbell()');
  await page.waitForFunction(()=>document.querySelector('#doorbellPopup').dataset.state==='error');
  assert.match(await page.locator('#doorbellState').textContent(),/does not support/);await run('closeDoorbell()');
  await page.evaluate(()=>window.supported=true);await run('openDoorbell();closeDoorbell()');await page.clock.runFor(100);
  assert(await page.evaluate(()=>window.peers.every(p=>p.closed)),'close during startup does not leak');
  assert.deepEqual(errors,[]);await page.close();console.log('PASS '+theme+': routing, blank wake, live lifecycle, early ICE, repeated ring, timeout, dismiss, unsupported camera and startup cancellation');
 }}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
