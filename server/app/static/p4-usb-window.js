import {installSelected,trustedMessage,PROTOCOL,SESSION_MS} from './p4-usb-session.js';
const query=new URLSearchParams(location.hash.slice(1)),origin=query.get('origin'),nonce=query.get('nonce');
const parent=window.opener,button=document.querySelector('#connect'),status=document.querySelector('#status');
let started=false,busy=false,awaiting=null;
const controller=new AbortController();
function send(type,extra={}){parent.postMessage({protocol:PROTOCOL,nonce,type,...extra},origin);}
function text(value){status.textContent=value;}
let valid=false;
try{const u=new URL(origin);valid=!!parent&&u.origin===origin&&['http:','https:'].includes(u.protocol)&&/^[a-f0-9]{48}$/.test(nonce);}catch{}
if(!valid){text('Start from Panel Server → Setup command → Install over USB.');}
else{
  history.replaceState(null,'',location.pathname);
  document.querySelector('#server').textContent='Panel Server: '+origin;
  window.addEventListener('message',event=>{
    if(!trustedMessage(event,parent,origin,nonce))return;
    const m=event.data;
    if(m.type==='start'&&!started){
      started=true;document.querySelector('#room').textContent=String(m.room||'New P4').slice(0,100);
      if(!isSecureContext||!navigator.serial){text('Open Panel Server in desktop Chrome or Edge to use USB.');return;}
      text('Connect the new P4 to this computer.');button.disabled=false;
    }else if(m.type==='progress'&&awaiting&&typeof m.text==='string'){text(m.text.slice(0,200));}
    else if(m.type==='package'&&awaiting){const pending=awaiting;awaiting=null;pending.resolve(m.package);}
    else if(m.type==='error'||m.type==='cancel'){
      controller.abort();awaiting?.reject(Error(m.text||'Setup cancelled'));awaiting=null;button.disabled=true;text(m.text||'Setup cancelled. Return to Panel Server to try again.');
    }
  });
  const hello=setInterval(()=>{if(started)clearInterval(hello);else send('ready');},300);
  setTimeout(()=>{clearInterval(hello);controller.abort();awaiting?.reject(Error('USB session expired'));button.disabled=true;},SESSION_MS);
  button.onclick=async()=>{
    if(busy||!started)return;
    busy=true;button.disabled=true;
    try{
      await installSelected({signal:controller.signal,status:value=>{text(value);send('status',{text:value});},prepare:probe=>new Promise((resolve,reject)=>{awaiting={resolve,reject};send('probe',{probe});text('Preparing your room on Panel Server. Keep this window open…');})});
      text('Installed. Artwork loads automatically; return to Panel Server for progress.');send('complete');
    }catch(e){text(e.message);send('error',{text:e.message});}
    finally{busy=false;}
  };
}
window.addEventListener('beforeunload',event=>{if(busy){event.preventDefault();event.returnValue='';}});
