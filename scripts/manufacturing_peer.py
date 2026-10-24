"""Native reference peer models issued materials and external power, not a business engine."""
import json
import os
from pathlib import Path
import time
from uuid import uuid4
import helics as h


def main():
    fed=h.helicsCreateCombinationFederateFromConfig(os.environ['HELICS_CONFIG'])
    endpoint=h.helicsFederateGetEndpointByIndex(fed,0);power=h.helicsFederateGetPublicationByIndex(fed,0)
    h.helicsFederateEnterInitializingMode(fed)
    h.helicsPublicationPublishDouble(power,0);h.helicsFederateEnterExecutingMode(fed)
    run=os.environ['FEDERATION_RUN_ID'];epoch=os.environ['FEDERATION_EPOCH'];correlation=str(uuid4())
    def envelope(kind,boundary,payload,grant,aggregate=None,version=1):
        event_id=str(uuid4());aggregate=aggregate or str(uuid4())
        return {'schema_version':'1.0','type':kind,'event_id':event_id,'federation_id':os.environ['FEDERATION_ID'],
                'run_id':run,'epoch':epoch,'correlation_id':correlation,'causation_id':event_id,'aggregate_id':aggregate,
                'aggregate_version':version,'source':'storage','destination':'manufacturing','boundary':boundary,
                'effective_time':grant+1,'wall_time':'2026-10-24T00:00:00Z','quantity_unit':'item','payload':payload}
    def send(event): h.helicsEndpointSendBytesTo(endpoint,json.dumps(event).encode(),'manufacturing/events')
    demand=envelope('manufacturing.demand.v1','demand',{'product':'PRODUCT','line':'LINE-1','quantity':4},0)
    send(demand);send(demand)
    seen=set();received=[];grant=0
    while True:
        grant=h.helicsFederateRequestTime(fed,grant+1)
        h.helicsPublicationPublishDouble(power,100 if grant>=15 else 0)
        while h.helicsEndpointHasMessage(endpoint):
            event=json.loads(h.helicsEndpointGetMessage(endpoint).data);received.append(event)
            if event['event_id'] in seen: continue
            seen.add(event['event_id'])
            if event['type']=='storage.request.v1':
                reservation=str(uuid4());p=event['payload'];fact={**p,'id':reservation,'run_id':run,'correlation_id':correlation,'status':'issued','version':2}
                notification=envelope('storage.reserve.completed.v1','materials',{**fact,'status':'reserved','version':1},grant,reservation,1);send(notification);send(notification)
                issue=envelope('storage.issue.completed.v1','materials',fact,grant,reservation,2);send(issue);send(issue)
            if event['type']=='storage.receipt.v1':
                Path('/evidence/result.json').write_text(json.dumps({'grant':grant,'events':received,'power_restored_at':15}))
        # Keep the native participant alive until verifier terminates this disposable project.
        time.sleep(.01)


if __name__=='__main__': main()
