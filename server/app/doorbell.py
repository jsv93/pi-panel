"""Bounded camera configuration; rings travel over Home Assistant's event bus."""
import re


def validate(value):
    if not isinstance(value, dict) or set(value) - {'enabled', 'camera', 'title', 'duration_s', 'trigger'}:
        raise ValueError('Doorbell settings must contain only enabled, camera, title, duration_s and trigger')
    if type(value.get('enabled', False)) is not bool:
        raise ValueError('Doorbell enabled must be true or false')
    camera = value.get('camera', '')
    trigger = value.get('trigger', '')
    if not isinstance(camera, str) or (camera and not re.fullmatch(r'camera\.[a-z0-9_]{1,200}', camera)):
        raise ValueError('Choose a Home Assistant camera entity')
    if value.get('enabled') and not camera:
        raise ValueError('Choose a camera before enabling the doorbell')
    if not isinstance(trigger, str) or (trigger and not re.fullmatch(r'(binary_sensor|event|input_button)\.[a-z0-9_]{1,200}', trigger)):
        raise ValueError('Choose a binary sensor, event entity or input button for the ring trigger')
    if type(value.get('duration_s', 30)) is not int or not 10 <= value.get('duration_s', 30) <= 120:
        raise ValueError('Doorbell duration must be between 10 and 120 seconds')
    if not isinstance(value.get('title', ''), str) or len(value.get('title', '')) > 80:
        raise ValueError('Doorbell title must be at most 80 characters')
    return value
