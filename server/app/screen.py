"""Display behaviour settings; appearance and room assignments remain separate."""
import math
import re

DEFAULTS = {
    'remote_diagnostics': True,
    'browser_recovery': True,
    'browser_stale_s': 90,
    'browser_recovery_limit': 3,
    'adaptive_brightness': False,
    'adaptive_sensor': '',
    'adaptive_min_pct': 10,
    'adaptive_max_pct': 100,
    'adaptive_dark_lux': 5,
    'adaptive_bright_lux': 300,
    'adaptive_transition_s': 5,
}
RANGES = {
    'browser_stale_s': (60, 600), 'browser_recovery_limit': (1, 6),
    'adaptive_min_pct': (1, 100), 'adaptive_max_pct': (1, 100),
    'adaptive_dark_lux': (0, 100000), 'adaptive_bright_lux': (1, 200000),
    'adaptive_transition_s': (1, 60),
}


def validate(display):
    if not isinstance(display, dict):
        raise ValueError('display must be an object')
    values = {**DEFAULTS, **display}
    for key, default in DEFAULTS.items():
        value = values[key]
        if isinstance(default, bool):
            if type(value) is not bool:
                raise ValueError(f'{key} must be true or false')
        elif key == 'adaptive_sensor':
            if not isinstance(value, str) or (value and not re.fullmatch(r'sensor\.[a-z0-9_]+', value)):
                raise ValueError('Choose a sensor entity for adaptive brightness')
        else:
            low, high = RANGES[key]
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'{key} must be between {low} and {high}')
            if key.startswith('browser_') and int(value) != value:
                raise ValueError(f'{key} must be a whole number')
    if values['adaptive_min_pct'] > values['adaptive_max_pct']:
        raise ValueError('Adaptive minimum brightness must not exceed maximum')
    if values['adaptive_dark_lux'] >= values['adaptive_bright_lux']:
        raise ValueError('Bright-room lux must exceed dark-room lux')
    if values['adaptive_brightness'] and not values['adaptive_sensor']:
        raise ValueError('Select an illuminance sensor before enabling adaptive brightness')
