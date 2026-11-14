"""Local browser QA: real server, isolated DB, synthetic panel and HA responses."""
import json
import math
import time
from serve_media_under_ingress import outer
from app import db, main

pid='diagnostics-qa'
db.upsert_panel(pid,'Study QA','00:11:22:33:44:55','192.0.2.15','pi','qa-fixture')
if not db.get_panel(pid)['claimed']:
    db.claim(pid,'Study','default')
db.claim_panel_token(pid,'qa-device-token-'+'t'*32,'qa-signing-key-'+'s'*32,'test')
db.touch(pid,{'cpu_temp':46,'ram_used_mb':448,'ram_total_mb':1024,'ram_used_pct':43.8,
              'ha_connected':True,'browser_health':'Healthy','presence':'Ready',
              'disk_free':'82%','backlight':'180 / 255','bluetooth_status':'Running'},db.latest_version(pid))
now=time.time()
with db.conn() as c:
    c.execute('DELETE FROM performance WHERE panel_id=?',(pid,))
    for n in range(0,86401,30):
        values={'cpu_usage_pct':12+math.sin(n/300)*5,'cpu_temp':46+math.sin(n/400)*2,
                'ram_used_pct':43.8,'ram_used_mb':448,'ram_total_mb':1024,'cpu_cores':4,
                'net_rx_kbps':50+math.sin(n/100)*30,'net_tx_kbps':10,'disk_write_kbps':7,'load_1m':.42}
        c.execute('INSERT INTO performance VALUES(?,?,?)',(pid,now-n,json.dumps(values)))
    # The live window deliberately includes a gap and zero-valued readings.
    for n in range(5,300,5):
        if n%30==0 or 100<n<140: continue
        values={'cpu_usage_pct':0 if n<20 else 12+math.sin(n/30)*5,'cpu_temp':46,
                'ram_used_pct':43.8,'ram_used_mb':448,'ram_total_mb':1024,'cpu_cores':4,
                'net_rx_kbps':50+math.sin(n/10)*30,'net_tx_kbps':10,'disk_write_kbps':7,'load_1m':.42}
        c.execute('INSERT INTO performance VALUES(?,?,?)',(pid,now-n,json.dumps(values)))

class FixturePanel:
    async def send_json(self, payload):
        if payload.get('type')=='ssh_access':
            pending=main.ACCESS_REQUESTS.get(pid)
            if pending:
                pending[1].set_result({'user':'joel','users':['joel'],'port':22,'keys':[
                    {'name':'QA computer','kind':'ssh-ed25519','fingerprint':'SHA256:'+'A'*43,'protected':False},
                    {'name':'Panel Server','kind':'ssh-ed25519','fingerprint':'SHA256:'+'B'*43,'protected':True}],
                    'changed':False})
main.LIVE[pid]=FixturePanel()
