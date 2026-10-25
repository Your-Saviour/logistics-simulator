"""Disposable native adapter-loss acceptance with an actual carried whole unit."""
import json
import os
from pathlib import Path
import time
from uuid import uuid4

import httpx
import psycopg
from psycopg.rows import dict_row

from handling_factory_verify import wait
from fleet_factory_verify import write


def signature(value):
    return {'robots':value['robots'], 'reservations':value['reservations'],
            'jobs':[(job['id'],job['state'],job['carried']) for job in value['jobs']]}


def main():
    record={'status':'running','scope':'native adapter SIGKILL freezes an actual carried unit and retains all physical claims'}
    evidence=Path('/evidence/fleet-fault-evidence.json')
    identities=json.loads(os.environ['FACTORY_IDENTITIES'])
    clients={name:httpx.Client(base_url=f'http://{name}-api:8000',auth=(identity['username'],identity['password']),timeout=10)
             for name,identity in identities.items()}
    fleet=httpx.Client(base_url=os.environ['FLEET_URL'],headers={'Authorization':'Bearer '+os.environ['FLEET_TOKEN']},timeout=5)
    db=psycopg.connect(json.loads(os.environ['FACTORY_DATABASES'])['logistics'],autocommit=True,row_factory=dict_row)
    started=time.monotonic()
    def get(app,path):
        response=clients[app].get('/api/'+path);response.raise_for_status();return response.json()
    def snapshot():
        response=fleet.get('/v1/snapshot');response.raise_for_status();return response.json()
    def control(app,action):
        run=get(app,'status')['run']
        response=clients[app].post('/api/control/'+action,json={'run_id':run['id'],'epoch':run['epoch']},headers={'Idempotency-Key':uuid4().hex})
        response.raise_for_status()
    def command(body,settle=True):
        for _ in range(20):
            run=get('logistics','status')['run']
            payload={**body,'run_id':run['id'],'epoch':run['epoch'],
                     'due_at':max(run['granted'],run['requested'])+2*float(os.environ['FACTORY_HANDOFF_QUANTUM'])}
            response=clients['logistics'].post('/api/transport/commands',json=payload,headers={'Idempotency-Key':uuid4().hex})
            if response.status_code==409 and 'Schedule' in response.text:continue
            response.raise_for_status();identity=response.json()['id']
            if settle:
                row=wait(lambda:db.execute('SELECT status FROM transport_commands WHERE id=%s',(identity,)).fetchone(),
                         lambda row:row and row['status']!='pending','native '+body['action'],timeout=180)
                assert row['status']=='completed',row
            return identity
        raise AssertionError('Could not schedule native command beyond the grant')
    try:
        for app in clients:
            wait(lambda:get(app,'status')['run'],lambda run:run['state']=='running' and run['granted']>0,app+' native initialization',timeout=90)
        unit,correlation=str(uuid4()),str(uuid4())
        command({'action':'intake','sku':'COMPONENT','category':'raw','location':'WAREHOUSE','quantity':2,
                 'correlation_id':correlation,'units':[{'id':unit,'quantity':2}]})
        transfer=command({'action':'request','route':'WAREHOUSE-DISPATCH','sku':'COMPONENT','quantity':2,
                          'correlation_id':correlation,'unit_ids':[unit]})
        command({'action':'assign','reference':transfer,'vehicle':'TRUCK-3'})
        load=command({'action':'load','reference':transfer},settle=False)
        wait(snapshot,lambda value:any(robot.get('carried_unit_id')==unit for robot in value['robots']),
             'actual native load is carried by Fleet',timeout=180)
        for app in clients:control(app,'hold')
        held=wait(snapshot,lambda value:value['run']['state']=='held','native holds freeze loaded Fleet',timeout=30)
        assert any(robot.get('carried_unit_id')==unit for robot in held['robots']),'Load finished before fault checkpoint'
        physical=signature(held)
        # The remaining three holds keep the floor still while the faulted
        # department is resumed and its private native adapter is killed.
        control('storage','resume')
        write(Path('/evidence/native-adapter-loss.request'),{'service':'storage-adapter','signal':'SIGKILL'})
        ack=Path('/evidence/native-adapter-loss.ack')
        wait(ack.exists,bool,'host kills only this disposable native adapter',timeout=90)
        wait(lambda:get('storage','status')['run'],lambda run:run['state']=='stalled',
             'Storage fences its lost native session',timeout=30)
        for app in clients:
            if get(app,'status')['run']['state']=='held':control(app,'resume')
        states={app:get(app,'status')['run']['state'] for app in clients}
        assert all(state!='held' for state in states.values()),states
        frozen=wait(snapshot,lambda value:value['run']['state']=='held','adapter loss independently holds Fleet',timeout=30)
        assert signature(frozen)==physical,'Adapter loss changed the held load or physical claims'
        time.sleep(6)  # Exceeds the five-second source/worker freshness bound.
        final=snapshot()
        assert final['run']['state']=='held' and signature(final)==physical,'Adapter loss released or advanced physical state'
        native=db.execute('SELECT state,position FROM transport_handling_units WHERE id=%s',(unit,)).fetchone()
        assert native['state']=='in_transit' and native['position'] is None,native
        assert db.execute('SELECT status FROM transport_commands WHERE id=%s',(load,)).fetchone()['status']=='pending'
        assert final['reservations'] and any(robot.get('carried_unit_id')==unit for robot in final['robots'])
        assert not any(event['kind']=='arrival' for event in final['events']),'Fault invented a physical arrival'
        record.update(status='passed',elapsed_wall_seconds=time.monotonic()-started,native_states=states,
                      adapter=json.loads(ack.read_text()),held_physical=physical,final_snapshot=final,native_unit=native)
    except Exception as error:
        record.update(status='failed',error=str(error),elapsed_wall_seconds=time.monotonic()-started)
        raise
    finally:
        write(evidence,record)
        db.close();fleet.close()
        for client in clients.values():client.close()


if __name__=='__main__':
    os.umask(0o077)
    main()
