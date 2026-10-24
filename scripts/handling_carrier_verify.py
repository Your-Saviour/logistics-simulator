"""Real native Shipping→Logistics custody acceptance, with Twin absent."""
import json
import os
import time
from uuid import uuid4
from pathlib import Path
import httpx
import psycopg
from simulator.handling_contracts import validate_snapshot, validate_movement, validate_handoff


def wait(fetch, predicate, label, timeout=150):
    deadline=time.monotonic()+timeout
    last=None
    while time.monotonic()<deadline:
        try:
            last=fetch()
            if predicate(last): return last
        except httpx.HTTPError as error:
            last=str(error)
        time.sleep(.15)
    raise AssertionError(f'{label}: {last}')


def main():
    evidence=Path(os.environ.get('CARRIER_EVIDENCE_DIR','/tmp'))/'evidence.json'
    evidence.write_text(json.dumps({'status':'running','project':os.environ.get('CARRIER_TEST_PROJECT'),'run_id':os.environ['EXPECTED_RUN_ID'],'epoch':os.environ['EXPECTED_EPOCH']},indent=2))
    identities=json.loads(os.environ['CARRIER_IDENTITIES'])
    clients={name:httpx.Client(base_url=f'http://{name}-api:8000',auth=(identity['username'],identity['password']),timeout=10) for name,identity in identities.items()}
    shipping,logistics=clients['shipping'],clients['logistics']
    # Disposable transport fault injection only: retain the durable envelope but
    # suppress publication until its gate opens. No stock/business rows change.
    databases={name:psycopg.connect(host=name+'-db',dbname=name,user=name,password=value['password'],autocommit=True) for name,value in identities.items()}
    stages={'logistics':'handling.received.v1','shipping':'handling.acknowledged.v1'}
    for name,connection in databases.items():
        connection.execute("CREATE TABLE test_custody_transport_gate(open boolean NOT NULL DEFAULT false,dropped integer NOT NULL DEFAULT 0)")
        connection.execute("INSERT INTO test_custody_transport_gate DEFAULT VALUES")
        connection.execute("CREATE FUNCTION test_drop_custody_publication() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.envelope->>'type'=TG_ARGV[0] AND EXISTS(SELECT 1 FROM test_custody_transport_gate WHERE NOT open) THEN UPDATE test_custody_transport_gate SET dropped=dropped+1; NEW.sent_at=clock_timestamp(); END IF; RETURN NEW; END $$")
        connection.execute("CREATE TRIGGER test_transport_loss BEFORE INSERT ON boundary_outbox FOR EACH ROW EXECUTE FUNCTION test_drop_custody_publication('"+stages[name]+"')")
    def get(client,path):
        result=client.get(path);result.raise_for_status();return result.json()
    for name,client in clients.items():
        status=wait(lambda:get(client,'/api/status'),lambda row:row['run']['state']=='running' and row['run']['granted']>0,name+' native initialization')
        assert status['run']['id']==os.environ['EXPECTED_RUN_ID'] and status['run']['epoch']==os.environ['EXPECTED_EPOCH']
    employee=next(value for value in identities['shipping']['identities'] if value['role']=='employee')
    def submit(action,**fields):
        run=get(shipping,'/api/status')['run']
        body={'run_id':run['id'],'epoch':run['epoch'],'due_at':max(run['granted'],run['requested'])+10,'action':action,**fields}
        response=shipping.post('/api/shipping/commands',json=body,auth=(employee['username'],employee['password']),headers={'Idempotency-Key':uuid4().hex});response.raise_for_status();identity=response.json()['id']
        snapshot=wait(lambda:get(shipping,'/api/shipping'),lambda row:any(command['id']==identity and command['outcome']!='pending' for command in row['commands']),action)
        command=next(command for command in snapshot['commands'] if command['id']==identity)
        assert command['outcome']=='completed',command
        return identity
    order=submit('create',customer='Native whole carrier',destination='CUSTOMER-A',lines=[{'sku':'PRODUCT','quantity':3}])
    submit('fulfil',reference=order)
    ready=wait(lambda:get(shipping,'/api/shipping/orders/'+order),lambda row:row['status']=='ready','whole receipt')
    ids=ready['lines'][0]['unit_ids'];assert ids
    submit('pack',reference=order);submit('dispatch',reference=order)
    delivered=wait(lambda:get(shipping,'/api/shipping/orders/'+order),lambda row:row['status']=='delivered','native carrier delivery')
    before_ack=get(shipping,'/api/shipping')['handling']
    versions={unit['id']:unit['version'] for unit in before_ack['units'] if unit['id'] in ids}
    assert databases['logistics'].execute('SELECT dropped FROM test_custody_transport_gate').fetchone()[0]>0
    databases['logistics'].execute('UPDATE test_custody_transport_gate SET open=true')
    wait(lambda:get(shipping,'/api/shipping')['handling']['handoffs'],lambda rows:rows and all(row['state']=='acknowledged' for row in rows),'late native custody receipt')
    assert databases['shipping'].execute('SELECT dropped FROM test_custody_transport_gate').fetchone()[0]>0
    databases['shipping'].execute('UPDATE test_custody_transport_gate SET open=true')
    wait(lambda:get(logistics,'/api/transport')['handling']['handoffs'],lambda rows:rows and all(row['state']=='acknowledged' for row in rows),'lost native custody acknowledgement recovery')
    source=get(shipping,'/api/shipping');destination=get(logistics,'/api/transport')
    run,epoch=os.environ['EXPECTED_RUN_ID'],os.environ['EXPECTED_EPOCH']
    for snapshot in (source,destination):
        validate_snapshot(snapshot['handling']['units'],run,epoch)
        for movement in snapshot['handling']['movements']: validate_movement(movement,run,epoch)
        for handoff in snapshot['handling']['handoffs']: validate_handoff(handoff,run,epoch)
    source_units={unit['id']:unit for unit in source['handling']['units']}
    target_units={unit['id']:unit for unit in destination['handling']['units']}
    for identity in ids:
        assert source_units[identity]['version']==versions[identity], 'late custody reply repeated source retirement'
        assert source_units[identity]['barcode']==target_units[identity]['barcode']
        assert source_units[identity]['contents']==target_units[identity]['contents']
        assert source_units[identity]['position'] is None and target_units[identity]['position'] is None
        assert source_units[identity]['state']=='dispatched' and target_units[identity]['state']=='dispatched'
        assert source_units[identity]['custody_generation']==target_units[identity]['custody_generation']==1
        moves=[move for move in destination['handling']['movements'] if move['unit_id']==identity]
        assert [move['action'] for move in moves]==['receive','load'],moves
        assert moves[1]['destination'].startswith('logistics.outbound.truck02.slot')
    assert delivered['shipment']['confirmation_id']
    transfer=next(value for value in destination['transfers'] if value['unit_ids']==ids)
    assert transfer['status']=='received' and transfer['customer_destination']=='CUSTOMER-A'
    assert delivered['shipment']['journey_id']==transfer['id']
    wait(lambda:get(shipping,'/api/shipping')['handling']['handoffs'],lambda rows:all(row['state']=='acknowledged' for row in rows),'source custody acknowledgement')
    evidence.write_text(json.dumps({'status':'passed','project':os.environ.get('CARRIER_TEST_PROJECT'),'run_id':run,'epoch':epoch,'unit_ids':ids,'source_units':[source_units[key] for key in ids],'destination_units':[target_units[key] for key in ids],'transport_drops':{name:connection.execute('SELECT dropped FROM test_custody_transport_gate').fetchone()[0] for name,connection in databases.items()},'transfer_id':transfer['id'],'shipment_id':delivered['shipment']['id'],'source_handling':source['handling'],'destination_handling':destination['handling'],'twin_present':False},indent=2))
    print('Real PHP/Go + private native HELICS: exact barcodes, assigned staging, receipt/load, customer delivery, custody acknowledgement and schema validation, delayed receipt and lost-ack recovery passed; Twin absent',flush=True)
    for connection in databases.values(): connection.close()
    for client in clients.values(): client.close()


if __name__=='__main__': main()
