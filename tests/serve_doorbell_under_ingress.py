from serve_media_under_ingress import outer
from app import ha

async def states(force=False):
    return [{'entity_id':'camera.test','state':'idle','attributes':{'friendly_name':'Test camera'}},
            {'entity_id':'binary_sensor.ring','state':'off','attributes':{'friendly_name':'Doorbell ring'}}]
ha.states=states
