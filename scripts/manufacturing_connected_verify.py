import base64
import json
import os
from pathlib import Path
import time
import urllib.request

headers={'Authorization':'Basic '+base64.b64encode((os.environ['APP_USERNAME']+':'+os.environ['APP_PASSWORD']).encode()).decode()}
def get(path):
    with urllib.request.urlopen(urllib.request.Request('http://manufacturing-api:8000/api/'+path,headers=headers),timeout=5) as response:return json.load(response)
end=time.monotonic()+150
while time.monotonic()<end:
    try:
        production=get('production');status=get('status');orders=production['orders']
        assert status['run']['state'] not in ('stalled','failed'),status['run']
        if orders and orders[0]['status']=='completed' and Path('/evidence/result.json').exists():break
    except (OSError,ValueError):pass
    time.sleep(.2)
else:raise AssertionError('Native production did not complete')
assert len(orders)==1,orders
order=orders[0];assert order['quantity']==order['output_quantity']==4 and order['scrap_quantity']==0,order
assert order['started_at']>=15 and order['finish_due']>=order['started_at']+20,order
assert production['materials'][0]['quantity']==0,production['materials']
assert sum(m['quantity'] for m in production['movements'] if m['kind']=='consume')==-8
assert len([m for m in production['movements'] if m['kind']=='output'])==1
report=json.loads(Path('/evidence/result.json').read_text());events=report['events']
requests=[e for e in events if e['type']=='storage.request.v1'];receipts=[e for e in events if e['type']=='storage.receipt.v1']
assert len(requests)==len(receipts)==1,events
assert requests[0]['payload']['quantity']==8 and receipts[0]['payload']['quantity']==4
assert requests[0]['correlation_id']==receipts[0]['correlation_id']==order['correlation_id']
print('Manufacturing native HELICS: typed demand/issued materials, actual duplicate deliveries, power gating, finite duration and correlated output passed')
