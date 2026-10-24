"""Verify actual HELICS domain transport and C# worker effects through HTTP."""
import os
import httpx
from stack_acceptance import wait_for

with httpx.Client(base_url='http://storage-api:8000',auth=(os.environ['APP_USERNAME'],os.environ['APP_PASSWORD']),timeout=10) as c:
    status=wait_for(c,'/api/status',lambda s:s['run']['mode']=='helics',timeout=120)
    snap=wait_for(c,'/api/warehouse',lambda s:any(t['status']=='received' for t in s['transfers']),timeout=120)
    def stock(sku,location):return next(s for s in snap['inventory'] if s['sku']==sku and s['location']==location)
    assert stock('COMPONENT','RAW-A')['on_hand']==3
    assert stock('PRODUCT','FINISHED-A')['on_hand']==3
    assert stock('PRODUCT','DISPATCH')['on_hand']==5
    assert all(s['reserved']==0 for s in snap['inventory'])
    assert len(snap['receipts'])==2 and len(snap['reservations'])==2 and len(snap['transfers'])==1
    assert {m['action'] for m in snap['movements']}=={'receive','reserve','issue','pick','transfer','arrive'}
    assert len({m['correlation_id'] for m in snap['movements']})==1
    assert not any(c['status']=='rejected' for c in snap['commands'])
    current=c.get('/api/status').json()
    assert current['run']['state']=='running' and current['run']['committed']<=current['run']['granted']
    assert c.post('/api/control/hold',json={}).status_code==200
    print('storage V1: real two-federate HELICS receipts, production/customer demand, picks, transfer outcomes, duplicate messages and correlated facts passed',flush=True)
