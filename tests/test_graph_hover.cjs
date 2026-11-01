/* Run against serve_diagnostics_under_ingress.py; inspect real SVG coordinates. */
const {chromium}=require('playwright'),assert=require('node:assert/strict');
(async()=>{
 const base=process.env.ADMIN_TEST_URL||'http://127.0.0.1:8878/api/hassio_ingress/testtoken';
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'msedge'});
 try{
  const context=await browser.newContext({viewport:{width:1280,height:1000},hasTouch:true,locale:'en-AU'});
  await context.request.post(base+'/api/login',{data:{password:'local-qa-only'}});
  const data=await (await context.request.get(base+'/api/panels/diagnostics-qa/performance?period=live')).json();
  const end=Math.floor(Date.now()/1000),start=end-300;
  const samples=[{at:end-200,cpu_usage_pct:14,cpu_temp:45,ram_used_pct:30,net_rx_kbps:25,net_tx_kbps:4},
   {at:end-195,cpu_usage_pct:0,cpu_temp:46,ram_used_pct:31,net_rx_kbps:0,net_tx_kbps:7},
   {at:end-190,cpu_temp:47,ram_used_pct:32},
   {at:end-10,cpu_usage_pct:90,cpu_temp:48,ram_used_pct:33,net_rx_kbps:32,net_tx_kbps:8}];
  let current={...data,start,end,samples,latest:samples.at(-1),bucket_s:5};
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/performance?period=*',route=>route.fulfill({json:current}));
  await page.goto(base+'/');await page.locator('[data-open="diagnostics-qa"]').click();
  await page.locator('#sectNav [data-s=diag]').click();await page.waitForSelector('#pc-cpu_usage_pct path');
  const cpu=page.locator('#pc-cpu_usage_pct'),tip=page.locator('#pt-cpu_usage_pct');
  async function coordinate(chart,at){return chart.evaluate((el,{at,start,end})=>{
   const point=new DOMPoint(30+330*(at-start)/(end-start),70).matrixTransform(el.getScreenCTM());return {x:point.x,y:point.y};
  },{at,start:current.start,end:current.end});}
  async function hover(chart,at){await chart.scrollIntoViewIfNeeded();const p=await coordinate(chart,at);await page.mouse.move(p.x,p.y);}
  await hover(cpu,end-195);assert.match(await tip.innerText(),/CPU usage: 0.0 %/);
  assert.match(await tip.innerText(),/\d\d:\d\d:\d\d/);assert.equal(await cpu.locator('.perf-cursor circle').count(),1);
  const selected=await tip.innerText();
  // Polling redraws must retain the historical sample, not jump to the latest reading.
  current={...current,end:end+5};
  await page.waitForResponse(r=>r.url().includes('/performance?')&&r.ok());
  assert.equal(await tip.isVisible(),true);assert.equal(await tip.innerText(),selected);
  await hover(cpu,end-190);assert.match(await tip.innerText(),/No reading/);assert.equal(await cpu.locator('.perf-cursor circle').count(),0);
  await hover(cpu,end-100);assert.equal(await tip.isVisible(),false);
  await hover(cpu,end-200);await page.mouse.move(0,0);assert.equal(await tip.isVisible(),false);
  await cpu.focus();assert.match(await tip.innerText(),/90.0 %/);
  await cpu.press('Home');assert.match(await tip.innerText(),/14.0 %/);
  await cpu.press('ArrowRight');assert.match(await tip.innerText(),/0.0 %/);
  await cpu.press('Escape');assert.equal(await tip.isVisible(),false);
  const network=page.locator('#pc-net_rx_kbps'),networkTip=page.locator('#pt-net_rx_kbps');
  await hover(network,end-195);assert.match(await networkTip.innerText(),/Receive: 0.0 KB\/s\nSend: 7.0 KB\/s/);
  assert.equal(await network.locator('.perf-cursor circle').count(),2);
  const temperature=page.locator('#pc-cpu_temp'),temperatureTip=page.locator('#pt-cpu_temp');
  await temperature.focus();await temperature.press('End');
  await page.waitForResponse(r=>r.url().includes('/performance?')&&r.ok());
  assert.equal(await temperatureTip.isVisible(),true);
  assert((await temperatureTip.boundingBox()).height<=60,'edge tooltip keeps timestamp and value on two readable lines');
  current={...current,bucket_s:300,start:end-86400};
  await page.locator('[data-period="24h"]').click();await page.waitForResponse(r=>r.url().includes('period=24h')&&r.ok());
  assert.equal(await networkTip.isVisible(),false);
  await cpu.focus();assert.match(await tip.innerText(),/5-minute average/);
  await page.setViewportSize({width:390,height:844});await cpu.scrollIntoViewIfNeeded();
  const touch=await coordinate(cpu,end-200);await page.touchscreen.tap(touch.x,touch.y);
  assert.equal(await tip.isVisible(),true);
  const bounds=await tip.boundingBox();assert(bounds.x>=0&&bounds.x+bounds.width<=390);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth));
  await page.locator('#performanceRefresh').tap();assert.equal(await tip.isVisible(),false);
  assert.deepEqual(errors,[]);
  console.log('PASS graph inspection: zero/missing/gaps, timestamp, both network series, live refresh, keyboard, averages, touch and mobile bounds');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
