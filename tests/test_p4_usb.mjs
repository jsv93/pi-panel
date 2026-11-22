// Exercise the production controller with a byte-addressed flash double.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {inflateSync} from 'node:zlib';
const source=await readFile(new URL('../server/app/static/p4-usb.js',import.meta.url));
const {inspect,writePackage,sha256,disconnect}=await import('data:text/javascript;base64,'+source.toString('base64'));
let writes=[],memory=new Map(),reset=[];
const loader={main:async()=>{},chip:{CHIP_NAME:'ESP32-P4',getChipRevision:async()=>103,readMac:async()=>'02:00:00:00:00:01'},detectFlashSize:async()=>'32MB',readFlash:async(offset,size)=>memory.get(offset)||new Uint8Array(size).fill(255),writeFlash:async options=>{assert.equal(options.eraseAll,false);const f=options.fileArray[0];assert.ok(f.data instanceof Uint8Array);writes.push(f.address);memory.set(f.address,f.data.slice());}};
const device=await inspect(loader);assert.equal(device.installed,false);
const table=new Uint8Array(4096).fill(255),view=new DataView(table.buffer);
view.setUint16(0,0x50aa,true);view.setUint32(4,0x610000,true);view.setUint32(8,0x1980000,true);table.set(new TextEncoder().encode('motion\0'),12);
memory.set(0x8000,table);assert.equal((await inspect(loader)).installed,true);memory.clear();
const files=[];
for(const [role,offset,size] of [['bootloader',0x2000,16],['partitions',0x8000,32],['application',0x10000,128],['otadata',0x9000,8192],['nvs',0x1f90000,0x70000]]){
 const data=new Uint8Array(size).fill(['nvs','otadata'].includes(role)?255:42);
 files.push({role,offset,bytes:size,sha256:await sha256(data),data:Buffer.from(data).toString('base64')});
}
const pkg={mac:device.mac,expires:Math.floor(Date.now()/1000)+100,files};
await assert.rejects(()=>writePackage(loader,pkg,{...device,installed:true}),/already installed/);assert.equal(writes.length,0);
await assert.rejects(()=>writePackage(loader,pkg,{...device,mac:'02:00:00:00:00:02'}),/different board/);assert.equal(writes.length,0);
await assert.rejects(()=>writePackage(loader,{...pkg,expires:1},device),/expired/);assert.equal(writes.length,0);
await assert.rejects(()=>writePackage(loader,{...pkg,files:[...files.slice(1),files[1]]},device),/Invalid flash layout/);assert.equal(writes.length,0);
await writePackage(loader,pkg,device);assert.deepEqual(writes,[0x1f90000,0x9000,0x10000,0x2000,0x8000]);
writes=[];const read=loader.readFlash;loader.readFlash=async()=>new Uint8Array(10);
await assert.rejects(()=>writePackage(loader,pkg,device),/Verification failed/);assert.equal(writes.length,1);loader.readFlash=read;
await disconnect(loader,{device:{readable:true},setDTR:async v=>reset.push(['dtr',v]),setRTS:async v=>reset.push(['rts',v]),disconnect:async()=>reset.push(['close'])});
assert.deepEqual(reset,[['dtr',false],['rts',true],['rts',false],['close']]);
// Use the actual pinned vendor's writeFlash method too: mocks alone would not
// catch API changes (0.7.1 requires Uint8Array, unlike older binary strings).
const vendor=await readFile(new URL('../server/app/static/p4-vendor/esptool-0.7.1.js',import.meta.url));
const {ESPLoader}=await import('data:text/javascript;base64,'+vendor.toString('base64'));
let compressed=[],address=0;
const rom={IS_STUB:true,FLASH_WRITE_SIZE:16384,ERASE_WRITE_TIMEOUT_PER_MB:40000,
 debug(){},info(){},timeoutPerMb:()=>3000,_updateImageFlashParams:async data=>data,
 flashDeflBegin:async(_,size,offset)=>{compressed=[];address=offset;return Math.ceil(size/16384);},
 flashDeflBlock:async data=>compressed.push(data),
 flashDeflFinish:async()=>memory.set(address,new Uint8Array(inflateSync(Buffer.concat(compressed))))};
loader.writeFlash=options=>ESPLoader.prototype.writeFlash.call(rom,options);
memory.clear();await writePackage(loader,pkg,device);
assert.equal(await sha256(memory.get(0x10000)),files.find(f=>f.role==='application').sha256);
console.log('PASS USB identification, installed/wrong-device lockout, package hashes, bounded flash writes, readback failure and hard reset');

// Run the real bridge with browser-window doubles. Forged messages cannot
// obtain a package; closing the popup aborts outstanding server preparation.
const sessionSource=(await readFile(new URL('../server/app/static/p4-usb-session.js',import.meta.url),'utf8')).replace(/^import .*;\r?\n/gm,'');
const {openUsbWindow,PROTOCOL,trustedMessage}=await import('data:text/javascript;base64,'+Buffer.from(sessionSource).toString('base64'));
const listeners=new Map(),messages=[];let popupUrl,prepared=0,aborted=false;
const popup={closed:false,postMessage:(data,origin)=>messages.push({data,origin})};
globalThis.location={origin:'http://panel.test'};
globalThis.window={open:url=>{popupUrl=new URL(url);return popup;},addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name)};
const pending=openUsbWindow({room:'Test room',prepare:(_,signal)=>{prepared++;return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>{aborted=true;reject(Error('aborted'));},{once:true}));}});
const nonce=new URLSearchParams(popupUrl.hash.slice(1)).get('nonce');
const event=type=>({source:popup,origin:popupUrl.origin,data:{protocol:PROTOCOL,nonce,type,probe:device}});
assert.equal(trustedMessage({...event('ready'),source:{}},popup,popupUrl.origin,nonce),false);
assert.equal(trustedMessage({...event('ready'),origin:'https://wrong.test'},popup,popupUrl.origin,nonce),false);
assert.equal(trustedMessage({...event('ready'),data:{protocol:PROTOCOL,nonce:'wrong'}},popup,popupUrl.origin,nonce),false);
await listeners.get('message')({...event('probe'),origin:'https://wrong.test'});assert.equal(prepared,0);
await listeners.get('message')(event('ready'));assert.equal(messages[0].data.type,'start');assert.equal(messages[0].origin,popupUrl.origin);
const preparation=listeners.get('message')(event('probe'));assert.equal(prepared,1);
popup.closed=true;await assert.rejects(pending,/window closed/);await preparation;
assert.equal(aborted,true);assert.equal(listeners.has('message'),false);
assert.ok(messages.every(m=>m.data.type!=='package'));
console.log('PASS USB window origin/source/nonce binding and cancellation of server preparation');
