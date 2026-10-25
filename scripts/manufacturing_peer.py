"""Native reference peer models issued materials and external power, not a business engine."""
import copy
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
    seen=set();received=[];grant=0;reservations={};handoffs={}
    def handling(value):
        event=envelope('handling.'+value['state']+'.v1','materials',value,grant,value['id'],value['unit']['version'])
        event['causation_id']=value['id']
        send(event);send(event)

    while True:
        grant=h.helicsFederateRequestTime(fed,grant+1)
        h.helicsPublicationPublishDouble(power,100 if grant>=15 else 0)
        while h.helicsEndpointHasMessage(endpoint):
            event=json.loads(h.helicsEndpointGetMessage(endpoint).data);received.append(event)
            if event['event_id'] in seen: continue
            seen.add(event['event_id'])
            if event['type']=='storage.request.v1':
                reservation=str(uuid4());p=event['payload'];fact={**p,'id':reservation,'run_id':run,'correlation_id':correlation,'status':'issued','version':2}
                # Quantity-only facts are observations. Reserve a real whole unit,
                # then honour Java's receiving assignment and custody acceptance.
                uid=str(uuid4())
                unit={'id':uid,'barcode':'HU-'+uid.replace('-','').upper(),'run_id':run,'epoch':epoch,
                      'contents':[{'sku':p['sku'],'quantity':p['quantity']}],'category':'raw','state':'reserved',
                      'owner':'storage','version':1,'custody_generation':0,'last_sequence':1,
                      'position':'storage.raw.r01.b01.l01','origin':None,'destination':None,'handoff_id':None}
                reservations[reservation]=(fact,unit)
                notification=envelope('storage.reserve.completed.v1','materials',{**fact,'status':'reserved','version':1,'unit_manifest':[unit]},grant,reservation,1)
                notification['causation_id']=event['event_id'];send(notification);send(notification)
            if event['type']=='storage.issue.v1':
                fact,unit=reservations[event['payload']['reference']]
                issue=envelope('storage.issue.completed.v1','materials',fact,grant,fact['id'],2);send(issue);send(issue)
                hid=str(uuid4());offered={'id':hid,'run_id':run,'epoch':epoch,'source':'storage','destination_owner':'manufacturing',
                    'origin':unit['position'],'destination':event['payload']['unit_destinations'][unit['id']],
                    'state':'offered','unit':unit,'departure_token':None,'receipt_id':None,'reason':None}
                handoffs[hid]=offered;handling(offered)
            if event['type']=='handling.accepted.v1':
                offered=handoffs[event['payload']['id']];departed=copy.deepcopy(offered);departed['state']='departed'
                transit=departed['unit'];transit.update(state='in_transit',position=None,origin=offered['origin'],destination=offered['destination'],handoff_id=offered['id'],version=2,last_sequence=2,custody_generation=1)
                departed['departure_token']={'id':str(uuid4()),'handoff_id':offered['id'],'unit_id':transit['id'],'run_id':run,'epoch':epoch,'custody_generation':1,'last_sequence':2,'unit_version':2}
                handling(departed)
            if event['type']=='handling.offered.v1' and event['payload']['source']=='manufacturing':
                accepted=copy.deepcopy(event['payload']);accepted['state']='accepted';handling(accepted)
            if event['type']=='handling.departed.v1' and event['payload']['source']=='manufacturing':
                receipt=copy.deepcopy(event['payload']);receipt.update(state='received',receipt_id=str(uuid4()));handling(receipt)
            if event['type']=='handling.acknowledged.v1' and event['payload']['source']=='manufacturing':
                Path('/evidence/result.json').write_text(json.dumps({'grant':grant,'events':received,'power_restored_at':15}))
        # Keep the native participant alive until verifier terminates this disposable project.
        time.sleep(.01)


if __name__=='__main__': main()
