"""Exercise the actual SSH-file helper as the current user in disposable Linux files."""
import ast
from pathlib import Path
import sys
if sys.platform != 'linux':
    print('SKIP SSH file helper requires Linux; run on a Linux test host')
    raise SystemExit(0)
tree=ast.parse((Path(__file__).resolve().parents[1]/'agent/panel-agent.py').read_text(encoding='utf-8'))
HELPER=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SSH_KEY_HELPER' for t in n.targets))

import json, os, pathlib, subprocess, tempfile
with tempfile.TemporaryDirectory(prefix='panel-key-helper-test-') as tmp:
    home=pathlib.Path(tmp)
    for name in ('server','computer'):
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(home/name)],check=True)
    server=' '.join((home/'server.pub').read_text().split()[:2])+' panel-config-server\n'
    public=' '.join((home/'computer.pub').read_text().split()[:2])
    ssh=home/'.ssh';ssh.mkdir(mode=0o700);keys=ssh/'authorized_keys';keys.write_text('# Preserve this comment\n'+server)
    def call(**body):
        r=subprocess.run(['python3','-c',HELPER],input=json.dumps({'home':tmp,**body}),text=True,capture_output=True,check=True)
        return json.loads(r.stdout)
    initial=call(action='list');assert initial['keys'][0]['protected']
    added=call(action='add',key=public,name='Test laptop')
    assert added['changed'] and len(added['keys'])==2
    assert keys.read_text().startswith('# Preserve this comment\n'+server)
    assert keys.stat().st_mode&0o777==0o600 and ssh.stat().st_mode&0o777==0o700
    assert not call(action='add',key=public,name='Duplicate')['changed']
    assert 'error' in call(action='remove',fingerprint=initial['keys'][0]['fingerprint'])
    fp=next(k['fingerprint'] for k in added['keys'] if not k['protected'])
    assert len(call(action='remove',fingerprint=fp)['keys'])==1
    assert list(ssh.glob('authorized_keys.before-panel-*'))
    original=keys.read_text();keys.unlink();outside=home/'outside';outside.write_text('untouched');keys.symlink_to(outside)
    assert 'error' in call(action='add',key=public,name='Symlink test')
    assert outside.read_text()=='untouched'
    keys.unlink();os.link(outside,keys)
    assert 'error' in call(action='add',key=public,name='Hard link test')
    assert outside.read_text()=='untouched'
    print('PASS Linux helper: user-owned files, preserved keys/comments, atomic add/remove, duplicate handling, server-key protection, backups, modes, symlink/hardlink refusal. No real SSH keys changed.')
