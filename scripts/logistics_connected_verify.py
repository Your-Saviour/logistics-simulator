import os
import httpx
from stack_acceptance import wait_for
with httpx.Client(base_url='http://logistics-api:8000',auth=(os.environ['APP_USERNAME'],os.environ['APP_PASSWORD']),timeout=10) as c:
    wait_for(c,'/api/status',lambda s:s['run']['mode']=='helics',timeout=120)
    if os.environ.get('LOGISTICS_PEER_LOSS')=='true':
        wait_for(c,'/api/status',lambda s:s['run']['state']=='stalled',timeout=60)
        snap=c.get('/api/transport').json();assert len(snap['transfers'])==1
        tr=snap['transfers'][0];assert tr['status']=='in_transit' and tr['custody']=='vehicle' and tr['received_at'] is None
        assert not any(m['action'] in ('arrive','unload','receive') for m in snap['movements'])
        print('logistics V1: native peer loss stalls time and retains in-transit custody without synthetic fallback',flush=True)
        raise SystemExit(0)
    snap=wait_for(c,'/api/transport',lambda s:any(t['status']=='received' for t in s['transfers']),timeout=120)
    assert len(snap['transfers'])==1
    tr=snap['transfers'][0];assert tr['quantity']==5 and tr['external_reference'] and tr['custody']=='destination'
    assert tr['arrived_at']>=tr['planned_eta'] and tr['received_at']>tr['unloaded_at']
    assert len(snap['movements'])==7
    assert {m['action'] for m in snap['movements']}=={'request','assign','load','depart','arrive','unload','receive'}
    assert not any(x['status']=='rejected' for x in snap['commands'])
    assert c.post('/api/control/hold',json={}).status_code==200
    print('logistics V1: actual native storage transfer, separate shipping receipt, duplicate deliveries and correlated transport facts passed',flush=True)
