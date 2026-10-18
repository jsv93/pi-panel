// A disposable headless browser, never the user's browser/profile.
const {chromium}=require('playwright'),http=require('node:http'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawn}=require('node:child_process'),assert=require('node:assert/strict');
(async()=>{
 const server=http.createServer((req,res)=>{res.setHeader('content-type','text/html');res.end('<html><body style="background:#21190f;color:#ddd"><h1>Screen capture test</h1></body></html>');});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const profile=fs.mkdtempSync(path.join(os.tmpdir(),'panel-cdp-'));
 const browser=await chromium.launchPersistentContext(profile,{headless:true,channel:'msedge',args:['--remote-debugging-address=127.0.0.1','--remote-debugging-port=9222'],viewport:{width:720,height:1280}});
 try{
  const page=browser.pages()[0];await page.goto(`http://127.0.0.1:${server.address().port}/panel.html`);
  const python=process.env.PANEL_TEST_PYTHON;
  assert(python,'PANEL_TEST_PYTHON is required');
  const code=`import asyncio,importlib.util,os,base64
from pathlib import Path
spec=importlib.util.spec_from_file_location('agent','agent/panel-agent.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
async def test():
 shot=await a.browser_cdp('Page.captureScreenshot',{'format':'jpeg','quality':70,'captureBeyondViewport':False})
 image=base64.b64decode(shot['data']);assert image[:2]==bytes([255,216]) and len(image)>1000
 await a.browser_cdp('Page.reload',{'ignoreCache':True})
 print('PASS real browser CDP: current viewport JPEG and kiosk page reload')
asyncio.run(test())`;
  const result=await new Promise(resolve=>{const child=spawn(python,['-c',code],{cwd:path.resolve(__dirname,'..'),env:{...process.env,PANEL_DIR:profile,PANEL_UI_PORT:String(server.address().port)}});let output='';child.stdout.on('data',d=>output+=d);child.stderr.on('data',d=>output+=d);child.on('exit',status=>resolve({status,output}));});
  assert.equal(result.status,0,result.output);console.log(result.output.trim());
 }finally{await browser.close();server.close();fs.rmSync(profile,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1)});
