// Shared by the dashboard and its secure USB window. No network calls.
export async function inspect(loader) {
  await loader.main('default_reset');
  if (loader.chip.CHIP_NAME !== 'ESP32-P4') throw new Error('Select the Waveshare ESP32-P4 board.');
  const revision = await loader.chip.getChipRevision(loader);
  const flash = await loader.detectFlashSize();
  const mac = await loader.chip.readMac(loader);
  if (flash !== '32MB') throw new Error(`This installer requires 32 MB flash; found ${flash}.`);
  // This product uses the tested engineering-sample board revision.
  if (revision < 100 || revision >= 300) throw new Error('This P4 revision needs a different firmware build. Nothing was written.');
  const table = new Uint8Array(await loader.readFlash(0x8000, 0x1000));
  const view = new DataView(table.buffer);
  const partitions = [];
  for (let p = 0; p + 32 <= table.length && view.getUint16(p, true) === 0x50aa; p += 32) {
    partitions.push({type: table[p+2], subtype: table[p+3], offset: view.getUint32(p+4,true),
      size: view.getUint32(p+8,true), label: new TextDecoder().decode(table.slice(p+12,p+28)).replace(/\0.*$/s,'')});
  }
  // This exact partition map is reserved by Pi Panel. Block even a damaged or
  // offline installation rather than relying on server discovery or readable NVS.
  const installed = partitions.some(p => p.label === 'motion' && p.offset === 0x610000) ||
    partitions.some(p => p.label === 'nvs' && p.offset === 0x1f90000);
  return {schema: 1, chip: 'ESP32-P4', revision, flash, mac: mac.toLowerCase(), installed, partitions};
}

const ranges={bootloader:[0x2000,0x6000],partitions:[0x8000,0x1000],otadata:[0x9000,0x2000],application:[0x10000,0x300000],nvs:[0x1f90000,0x70000]};
export async function sha256(data) {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),x=>x.toString(16).padStart(2,'0')).join('');
}
export async function verifyPackage(pkg) {
  if (!pkg || !/^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$/.test(pkg.mac) ||
      !Number.isSafeInteger(pkg.expires) || Date.now()/1000>pkg.expires ||
      !Array.isArray(pkg.files) || pkg.files.length!==5) throw new Error('This installation expired. Start Install over USB again.');
  const seen=new Set(), files=[];
  for(const f of pkg.files){
    const range=ranges[f.role];
    if(!range || seen.has(f.role) || f.offset!==range[0] || !Number.isSafeInteger(f.bytes) || f.bytes<=0 || f.bytes>range[1]) throw new Error('Invalid flash layout. Nothing was written.');
    seen.add(f.role);
    const data=Uint8Array.from(atob(f.data),c=>c.charCodeAt(0));
    if(data.length!==f.bytes || await sha256(data)!==f.sha256) throw new Error('Firmware verification failed. Start Install over USB again.');
    if(['otadata','nvs'].includes(f.role) && (data.length!==range[1] || data.some(x=>x!==255))) throw new Error('Invalid initial storage.');
    files.push({...f,bytesData:data});
  }
  return files;
}
export async function writePackage(loader,pkg,device,progress=()=>{}) {
  const files=await verifyPackage(pkg);
  if(device.mac!==pkg.mac || device.chip!=='ESP32-P4' || device.flash!=='32MB' || device.revision<100 || device.revision>=300)
    throw new Error('This installer belongs to a different board. Nothing was written.');
  if(device.installed) throw new Error('Pi Panel is already installed. Use Panel Server for updates. Nothing was written.');
  // Commit the identifying partition table last. An interrupted first install
  // can be retried while the old table is present. Never erase the whole flash.
  for(const role of ['nvs','otadata','application','bootloader','partitions']){
    const f=files.find(x=>x.role===role);
    progress(role,0);
    await loader.writeFlash({fileArray:[{data:f.bytesData,address:f.offset}],flashSize:'keep',flashMode:'keep',flashFreq:'keep',eraseAll:false,compress:true,
      reportProgress:(_,written,total)=>progress(role,written/total)});
    const actual=new Uint8Array(await loader.readFlash(f.offset,f.bytes));
    if(await sha256(actual)!==f.sha256) throw new Error(`Verification failed for ${role}. Keep USB connected and retry Install over USB.`);
  }
}

export async function disconnect(loader, transport) {
  try {
    if (transport.device.readable) {
      // Hard reset returns to the existing flash application; never softReset,
      // which uses flash commands in the ROM path.
      await transport.setDTR(false);
      await transport.setRTS(true);
      await new Promise(resolve => setTimeout(resolve, 120));
      await transport.setRTS(false);
    }
  } finally {
    if (transport.device.readable) await transport.disconnect();
  }
}
