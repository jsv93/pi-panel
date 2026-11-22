import {ESPLoader,Transport} from './p4-vendor/esptool-0.7.1.js';
import {inspect,disconnect,writePackage,verifyPackage} from './p4-usb.js';

export const USB_HOST='https://jsv93.github.io/pi-panel/usb/';
export const PROTOCOL='pi-panel-usb-v1';
export const SESSION_MS=2*60*60*1000;
export function directSerial(){
  const policy=document.permissionsPolicy||document.featurePolicy;
  return !!(window.isSecureContext&&navigator.serial&&(!policy||policy.allowsFeature('serial')));
}
export function trustedMessage(event,source,origin,nonce){
  return event.source===source && event.origin===origin && event.data?.protocol===PROTOCOL && event.data?.nonce===nonce;
}
function live(signal){if(signal?.aborted)throw new DOMException('USB setup cancelled','AbortError');}

// requestPort is the first async operation, so a browser button click supplies
// the required user activation. Reset/release USB while the server compiles.
export async function installSelected({prepare,status=()=>{},signal,serial=navigator.serial}){
  const port=await serial.requestPort();
  let transport,loader;
  const open=()=>{
    transport=new Transport(port);
    loader=new ESPLoader({transport,baudrate:460800,terminal:{clean(){},write(){},writeLine(){}}});
  };
  live(signal);open();
  let probe;
  try{
    status('Checking the connected P4…');probe=await inspect(loader);
    if(probe.installed)throw Error('Pi Panel is already installed on this board. Use its normal update controls. Nothing was written.');
  }finally{await disconnect(loader,transport);}
  live(signal);
  const pkg=await prepare(probe,signal);
  live(signal);await verifyPackage(pkg);live(signal);
  open();
  try{
    status('Rechecking the P4 before installation…');
    const actual=await inspect(loader);live(signal);
    if(probe.mac!==actual.mac)throw Error('The connected P4 changed. Nothing was written.');
    await writePackage(loader,pkg,actual,(role,amount)=>status(`Installing ${role} · ${Math.round(amount*100)}%`));
  }finally{await disconnect(loader,transport);}
  status('USB installation verified. Artwork now loads automatically.');
}

// HTTP/ingress fallback follows ESPHome's secure-window pattern. Firmware
// stays in browser memory. Never include credentials in a URL or use '*'.
export function openUsbWindow({room,prepare,status=()=>{},signal,host=USB_HOST}){
  const nonce=Array.from(crypto.getRandomValues(new Uint8Array(24)),v=>v.toString(16).padStart(2,'0')).join('');
  const url=new URL(host);
  if(url.protocol!=='https:' && !['localhost','127.0.0.1'].includes(url.hostname))throw Error('USB window requires HTTPS');
  url.hash=new URLSearchParams({origin:location.origin,nonce}).toString();
  const popup=window.open(url.toString(),'pi-panel-usb-'+nonce,'popup,width=680,height=740');
  if(!popup)throw Error('Allow the USB setup window to open, then try Install over USB again.');
  const expected=url.origin;
  return new Promise((resolve,reject)=>{
    const session=new AbortController();
    let preparing=false,finished=false;
    const send=(type,extra={})=>popup.postMessage({protocol:PROTOCOL,nonce,type,...extra},expected);
    const cleanup=()=>{window.removeEventListener('message',receive);clearInterval(watch);clearTimeout(expiry);clearTimeout(handshake);signal?.removeEventListener('abort',cancel);};
    const finish=(error)=>{if(finished)return;finished=true;session.abort();cleanup();error?reject(error):resolve();};
    const cancel=()=>{send('cancel');finish(new DOMException('USB setup cancelled','AbortError'));};
    const receive=async event=>{
      if(!trustedMessage(event,popup,expected,nonce)||finished)return;
      const m=event.data;
      if(m.type==='ready'){clearTimeout(handshake);send('start',{room});return;}
      if(m.type==='status'&&typeof m.text==='string'){status(m.text.slice(0,200));return;}
      if(m.type==='error'){finish(Error(String(m.text||'USB setup failed').slice(0,300)));return;}
      if(m.type==='complete'){finish();return;}
      if(m.type!=='probe'||preparing)return;
      preparing=true;
      try{
        const pkg=await prepare(m.probe,session.signal,text=>{status(text);if(!finished)send('progress',{text});});
        live(signal);if(!finished)send('package',{package:pkg});
      }catch(e){if(!finished){send('error',{text:e.message});finish(e);}}
    };
    window.addEventListener('message',receive);
    const watch=setInterval(()=>{if(popup.closed)finish(Error('USB setup window closed. You can resume from Setup command.'));},1000);
    const expiry=setTimeout(()=>{send('cancel');finish(Error('USB session expired. Start Install over USB again.'));},SESSION_MS);
    const handshake=setTimeout(()=>finish(Error('The secure USB window could not load. Check your internet connection and try again.')),20000);
    signal?.addEventListener('abort',cancel,{once:true});
    if(signal?.aborted)cancel();
  });
}
