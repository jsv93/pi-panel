"""P4 runtime settings, deliberately separate from Pi display behaviour."""
import copy
import math
import re

DISPLAY_LIVE = ('idle_timeout_s','backlight_off_s','backlight_default','backlight_min',
    'adaptive_brightness','adaptive_sensor','adaptive_min_pct','adaptive_max_pct',
    'adaptive_dark_lux','adaptive_bright_lux','adaptive_transition_s',
    'p4_presence_pin','p4_presence_debounce_ms','palette','diagnostics','browse_view','mini_art',
    'touch_gesture','touch_points','touch_hold_ms','remember_last_state')
PI_ONLY = ('browser_recovery','browser_stale_s','browser_recovery_limit','remote_diagnostics',
           'idle_power_saving','presence_pin','presence_sensor','presence_debounce_ms')

def structural(config):
    value=copy.deepcopy(config)
    for key in list(value):
        if key.startswith('_'):value.pop(key)
    for light in value.get('lights',[]):
        for key in ('soft','bright','include_presets'):light.pop(key,None)
    for key in DISPLAY_LIVE+PI_ONLY:value.get('display',{}).pop(key,None)
    bell=value.setdefault('doorbell',{})
    for key in ('enabled','duration_s','camera','trigger'):bell.pop(key,None)
    bell['title']=bell.get('title') or 'Someone at the door'
    for key in ('temperature','humidity','climate'):value.setdefault('sensors',{}).pop(key,None)
    media=value.get('media',{})
    for key in ('speakers','default_speaker','default_speaker_name'):media.pop(key,None)
    return value

def compatible(config,compiled):
    return structural(config)==structural(compiled)

def validate(config):
    d=config.get('display',{})
    for section in ('display','doorbell','sensors','media'):
        if not isinstance(config.get(section,{}),dict):raise ValueError(f'{section} must be an object')
    if d.get('theme','architectural')!='architectural':raise ValueError('This P4 supports Architectural and its palettes')
    for key,expected in (('screen_width',720),('screen_height',1280)):
        if d.get(key,expected) not in (0,expected):raise ValueError('This P4 requires the 5-inch 720 × 1280 display')
    if 'lights' in config and (not isinstance(config['lights'],list) or not 1<=len(config['lights'])<=12):
        raise ValueError('This P4 supports 1–12 Home Assistant lights')
    if config.get('dali',{}).get('enabled') or config.get('dali',{}).get('gateway'):
        raise ValueError('DALI is not enabled in this P4 firmware')
    media=config.get('media',{});speakers=media.get('speakers',[])
    if not isinstance(speakers,list):raise ValueError('Speakers must be a list')
    ids=[]
    def player(entity):
        return isinstance(entity,str) and len(entity)<=96 and re.fullmatch(r'media_player\.[a-z0-9_]+',entity)
    def label(name):return isinstance(name,str) and len(name.encode('utf8'))<=96 and all(ord(c)>=32 for c in name)
    for entry in speakers:
        entity=entry if isinstance(entry,str) else entry.get('entity_id') if isinstance(entry,dict) else None
        name=entry.get('name','') if isinstance(entry,dict) else ''
        if not player(entity) or entity in ids or not label(name):raise ValueError('Choose unique speakers with names up to 96 UTF-8 bytes')
        ids.append(entity)
    default=media.get('default_speaker','')
    if default and not player(default):raise ValueError('Choose a valid default speaker')
    if not label(media.get('default_speaker_name','')):raise ValueError('Invalid default speaker name')
    if len(set(ids+([default] if default else [])))>16:raise ValueError('P4 supports up to 16 speakers including the default')
    for section,keys in [('display',('adaptive_sensor',)),('doorbell',('camera','trigger')),('media',('default_speaker',))]:
        for key in keys:
            v=config.get(section,{}).get(key,'')
            if not isinstance(v,str) or len(v)>96:raise ValueError(f'{key} must be at most 96 characters')
    for key,default,lo,hi in [('idle_timeout_s',45,0,86400),('backlight_off_s',0,0,86400),
        ('backlight_default',100,1,100),('backlight_min',5,1,100)]:
        n=d.get(key,default)
        if type(n) not in (int,float) or not math.isfinite(n) or not lo<=n<=hi:
            raise ValueError(f'{key} must be between {lo} and {hi}')
    for key,domain in [('temperature','sensor'),('humidity','sensor'),('climate','climate')]:
        v=config.get('sensors',{}).get(key,'')
        if not isinstance(v,str) or (v and not re.fullmatch(domain+r'\.[a-z0-9_]{1,80}',v)):
            raise ValueError(f'Choose a valid {key} entity')
