"""Exercise CPU ownership, crash recovery and browser liveness using fake sysfs."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    tmp=Path(tmp)
    os.environ['PANEL_DIR']=str(tmp)
    spec=importlib.util.spec_from_file_location('power_agent',ROOT/'agent/panel-agent.py')
    agent=importlib.util.module_from_spec(spec);spec.loader.exec_module(agent)
    policy=tmp/'policy';policy.mkdir();journal=tmp/'saved.json'
    def put(name,value): (policy/name).write_text(str(value))
    def maximum():return int((policy/'scaling_max_freq').read_text())
    for key,value in {'cpuinfo_min_freq':1500000,'cpuinfo_max_freq':2400000,'scaling_min_freq':1500000,'scaling_max_freq':2200000,'scaling_governor':'ondemand'}.items():put(key,value)
    power=agent.IdlePowerLimit(policy,journal)
    assert power.update(True) and maximum()==1500000
    saved=journal.stat().st_mtime_ns
    assert power.update(True) and journal.stat().st_mtime_ns==saved,'do not rewrite journal while idle'
    assert power.update(False) and maximum()==2200000 and not journal.exists(),'restore original cap, not firmware maximum'
    assert (policy/'scaling_governor').read_text()=='ondemand'
    power.update(True)
    recovered=agent.IdlePowerLimit(policy,journal)
    assert recovered.update(False) and maximum()==2200000,'restart restores interrupted cap before browser connects'
    power=agent.IdlePowerLimit(policy,journal);power.update(True);put('scaling_max_freq',1800000)
    assert power.update(True) and maximum()==1800000 and not journal.exists()
    assert power.update(True) and maximum()==1800000,'external changes are not fought'
    power.update(False);power.update(True);power.update(False);assert maximum()==1800000
    put('scaling_max_freq',1500000);power.update(True);assert not journal.exists();power.update(False);assert maximum()==1500000
    put('scaling_max_freq',2400000)
    journal.write_text(json.dumps({'normal':99999999,'idle':1500000}))
    assert not agent.IdlePowerLimit(policy,journal).update(False) and maximum()==2400000
    journal.unlink()
    missing=agent.IdlePowerLimit(tmp/'missing',journal);assert not missing.update(True) and not journal.exists()
    power=agent.IdlePowerLimit(policy,journal)
    original_write=Path.write_text
    def denied(path,*args,**kwargs):
        if path==policy/'scaling_max_freq':raise PermissionError('fixture')
        return original_write(path,*args,**kwargs)
    with patch.object(Path,'write_text',denied):assert not power.update(True)
    assert maximum()==2400000 and journal.exists()
    assert power.update(False) and not journal.exists()
    print('PASS temporary ceiling, no governor changes, idempotence, original limit, crash recovery, external ownership, unsupported and permission failure')

    agent.IDLE_POWER=agent.IdlePowerLimit(policy,journal)
    page=object();agent.PAGES.add(page)
    with patch.object(agent,'screen_settings',return_value={'idle_power_saving':True}),patch.object(agent.time,'monotonic',return_value=100):
        agent.reconcile_idle_power();assert maximum()==2400000
        agent.POWER_PAGES[page]=('blanked',99);agent.reconcile_idle_power();assert maximum()==1500000
        agent.POWER_PAGES[page]=('idle',99);agent.reconcile_idle_power();assert maximum()==2400000
        agent.POWER_PAGES[page]=('blanked',74);agent.reconcile_idle_power();assert maximum()==2400000
        agent.POWER_PAGES[page]=('blanked',99);agent.reconcile_idle_power();assert maximum()==1500000
        second=object();agent.PAGES.add(second);agent.reconcile_idle_power();assert maximum()==2400000
        agent.PAGES.remove(second);agent.reconcile_idle_power();assert maximum()==1500000
        asyncio.run(agent.tell_pages({'type':'wake'}));assert maximum()==2400000
        agent.PAGES.add(page);agent.POWER_PAGES[page]=('blanked',99);agent.reconcile_idle_power();assert maximum()==1500000
        with patch.object(agent,'screen_settings',return_value={'idle_power_saving':False}):agent.reconcile_idle_power()
        assert maximum()==2400000 and agent.IDLE_POWER.status=='Off'
        agent.reconcile_idle_power();assert maximum()==1500000
        agent.PAGES.clear();agent.reconcile_idle_power();assert maximum()==2400000
    print('PASS blank-only policy, stale/missing/multiple pages, wake-before-message, disable and disconnect restoration')

    async def stopped():
        agent.IDLE_POWER.update(True)
        raise asyncio.CancelledError
    with patch.object(agent,'main',stopped):
        try:asyncio.run(agent.run_agent())
        except asyncio.CancelledError:pass
    assert maximum()==2400000 and not journal.exists()
    print('PASS shutdown cancellation restores CPU ceiling')
