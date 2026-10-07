"""Deterministic HA data for the real ingress media-settings browser test."""
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'server'))
os.environ['PANEL_SERVER_DIR'] = str(root / 'server')
from serve_under_ingress import outer
from app import ha


async def states(force=False):
    return [
        {'entity_id': 'media_player.lamp_native', 'state': 'idle',
         'attributes': {'friendly_name': 'Lamp (Sonos)'}},
        {'entity_id': 'media_player.lamp_ma', 'state': 'idle',
         'attributes': {'friendly_name': 'Lamp (Music Assistant)', 'mass_player_type': 'player'}},
        {'entity_id': 'media_player.offline', 'state': 'unavailable',
         'attributes': {'friendly_name': 'Offline speaker'}},
    ]


async def transfer():
    return True


ha.states = states
ha.transfer_service_available = transfer
