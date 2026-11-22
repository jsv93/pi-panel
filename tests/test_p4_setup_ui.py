"""Real browser UI/USB-window protocol; only backend and physical ROM are doubles."""
import base64,hashlib,json,os,sys,tempfile,time
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from app.db import DEFAULT_TEMPLATE
STATIC=ROOT/'server/app/static'
HOST='https://jsv93.github.io/pi-panel/usb/'
PROBE=dict(schema=1,chip='ESP32-P4',revision=103,flash='32MB',mac='02:00:00:00:00:01',installed=False)

ROM='''export class Transport {constructor(device){this.device=device;}async setDTR(){}async setRTS(){}async disconnect(){this.device.readable=false;}}
export class ESPLoader {constructor({transport}){this.transport=transport;this.memory=new Map();this.chip={CHIP_NAME:'ESP32-P4',getChipRevision:async()=>103,readMac:async()=>'02:00:00:00:00:01'};}
async main(){this.transport.device.readable=true;}async detectFlashSize(){return '32MB';}
async readFlash(address,size){return this.memory.get(address)||new Uint8Array(size).fill(255);}
async writeFlash(options){const f=options.fileArray[0];window.usbWrites=(window.usbWrites||0)+1;this.memory.set(f.address,f.data.slice());options.reportProgress(0,f.data.length,f.data.length);}}
'''

def package():
 files=[]
 for role,offset,size in [('bootloader',0x2000,32),('partitions',0x8000,32),('otadata',0x9000,8192),('application',0x10000,256),('nvs',0x1f90000,0x70000)]:
  data=bytes([255 if role in ('nvs','otadata') else 42])*size
  files.append(dict(role=role,offset=offset,bytes=size,sha256=hashlib.sha256(data).hexdigest(),data=base64.b64encode(data).decode()))
 return dict(mac=PROBE['mac'],files=files,expires=int(time.time())+600)

def main():
 with sync_playwright() as p:
  options={'executable_path':os.environ['PANEL_CHROMIUM_PATH']} if os.environ.get('PANEL_CHROMIUM_PATH') else {'channel':'msedge'}
  browser=p.chromium.launch(headless=True,**options)
  for scheme,prefix in [('https','/'),('http','/api/hassio_ingress/test/')]:
   context=browser.new_context(viewport={'width':1280,'height':1000})
   context.add_init_script("Object.defineProperty(navigator,'serial',{value:{requestPort:async()=>{window.usbRequests=(window.usbRequests||0)+1;return {readable:false};}}});")
   page=context.new_page();errors=[];console=[];posts=[];created=False;bound=False
   page.on('console',lambda m:console.append(m.text) if m.type=='error' else None)
   context.on('page',lambda child:child.on('pageerror',lambda e:errors.append(str(e))))
   page.on('pageerror',lambda e:errors.append(str(e)))
   config=json.loads(json.dumps(DEFAULT_TEMPLATE));config['display'].update(theme='architectural',screen_width=720,screen_height=1280)
   config['lights']=[dict(entity_id='light.test',name='Test lamp',soft=30,bright=100,include_presets=True)]
   config['room_label']='New Study'
   panel=dict(id='p4-new',hostname='p4-new',kind='esp',claimed=True,room='New Study',template='default',last_seen=None,metrics={})
   def serve(r,path,hosted=False):
    if path=='p4-vendor/esptool-0.7.1.js':return r.fulfill(content_type='text/javascript',body=ROM)
    if path in ('','index.html') and hosted:path='p4-usb-window.html'
    f=STATIC/path
    if not f.is_file():return r.fulfill(status=404,body='')
    kind='text/html' if f.suffix=='.html' else 'text/javascript'
    return r.fulfill(content_type=kind,body=f.read_bytes())
   def route(r):
    nonlocal created,bound
    url=r.request.url
    if url.startswith(HOST):return serve(r,url[len(HOST):].split('#')[0],True)
    path=url.split(scheme+'://panel.test',1)[-1]
    if path==prefix:
     body=(STATIC/'index.html').read_text(encoding='utf8');script=body.split('<script>',1)[1].split('</script>',1)[0]
     digest=base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
     csp=f"default-src 'self'; script-src 'sha256-{digest}' 'strict-dynamic'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'"
     return r.fulfill(content_type='text/html',body=body,headers={'Content-Security-Policy':csp})
    if path.startswith(prefix+'p4-'):return serve(r,path[len(prefix):])
    if not path.startswith(prefix+'api/'):return r.fulfill(status=404,body='')
    endpoint=path[len(prefix+'api'):]
    state=dict(initial=True,enrolled=bound,enabled=bound,generation=None,jobs=[dict(id=123,state='ready',detail='Ready')] if bound else [],metrics={},last_seen=None,saved_version=1,applied_version=0)
    if endpoint=='/me':data={'authenticated':True}
    elif endpoint=='/panels':data=[panel] if created else []
    elif endpoint=='/p4-setup' and r.request.method=='POST':created=True;posts.append(r.request.post_data_json);data={'panel_id':'p4-new'}
    elif endpoint=='/p4-setup/p4-new/connect':bound=True;posts.append(r.request.post_data_json);data={}
    elif endpoint in ('/p4-setup/p4-new','/panels/p4-new/p4'):data=state
    elif endpoint=='/p4-setup/p4-new/package/123':data=package()
    elif endpoint=='/p4-setup/p4-new/pairing':data={'api_key':'test-only-key','api_name':'p4-new'}
    elif endpoint=='/panels/p4-new':data=dict(panel=panel,config=config,own=config,history=[],latest_version=1,problems=[],live=False)
    elif endpoint.startswith('/panels/p4-new/performance'):data=dict(panel=panel,samples=[],live=False)
    elif endpoint=='/provision':data=[]
    elif endpoint.startswith('/entities'):data=[{'entity_id':'light.test','name':'Test lamp','domain':'light'}] if 'light' in endpoint else []
    elif endpoint=='/templates':data=[{'name':'default'}]
    else:data={}
    r.fulfill(content_type='application/json',body=json.dumps(data))
   context.route('**/*',route)
   page.goto(scheme+'://panel.test'+prefix)
   page.locator('#addPanelBtn').click();expect(page.locator('#provKind')).to_be_visible()
   assert page.locator('#provKind').input_value()=='pi' # Existing Pi default preserved.
   page.locator('#provKind').select_option('esp');page.locator('#provRoom').fill('New Study');page.locator('#mOk').click()
   expect(page.locator('#setupCmdBtn')).to_be_visible();page.locator('#setupCmdBtn').click()
   try:expect(page.locator('#p4InstallUsb')).to_be_enabled()
   except Exception:
    print(page.locator('#p4UsbStatus').inner_text(),console,errors);raise
   assert not page.locator('#modal input[type=file]').count()
   if scheme=='http':
    with context.expect_page() as event:page.locator('#p4InstallUsb').click()
    usb=event.value;expect(usb.locator('#connect')).to_be_enabled();usb.locator('#connect').click()
   else:usb=page;page.locator('#p4InstallUsb').click()
   expect(page.locator('#p4UsbStatus')).to_contain_text('USB installation complete',timeout=20000)
   assert usb.evaluate('window.usbRequests')==1 and usb.evaluate('window.usbWrites')==5
   assert len(posts)==2 and posts[1]['mac']==PROBE['mac']
   assert page.locator('#p4InstallUsb').is_disabled()
   page.get_by_text('Connect Home Assistant',exact=True).click();expect(page.locator('#p4ShowKey')).to_be_enabled()
   page.locator('#p4ShowKey').click();expect(page.locator('#p4SetupKey')).to_have_text('test-only-key')
   page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   if scheme=='https':page.screenshot(path=str(Path(tempfile.gettempdir())/'p4-usb-setup.png'))
   assert not errors,errors
   context.close()
  browser.close()
 print('PASS Add panel → Setup command → USB; HTTPS direct, HTTP secure handoff, ingress, CSP, one picker, verified writes, pairing and Pi default')
if __name__=='__main__':main()
