"""Actual C#/Java raw-to-production-to-finished custody with loss recovery."""
import json
import os
import time
from pathlib import Path
from uuid import uuid4
import httpx
import psycopg
from psycopg.rows import dict_row
from simulator.handling_contracts import validate_snapshot, validate_movement, validate_handoff, validate_lineage


def wait(fetch,predicate,label,timeout=120):
    end=time.monotonic()+timeout;last=None
    while time.monotonic()<end:
        try:
            last=fetch()
            if predicate(last):return last
        except httpx.HTTPError as error:last=str(error)
        time.sleep(.15)
    raise AssertionError(f'{label}: {last}')


def main():
    run,epoch=os.environ['EXPECTED_RUN_ID'],os.environ['EXPECTED_EPOCH'];path=Path('/evidence/evidence.json')
    record={'status':'running','run_id':run,'epoch':epoch,'twin_present':False,'scope':'raw custody, once-only recipe consumption and fresh finished-output custody'};path.write_text(json.dumps(record,indent=2))
    identities=json.loads(os.environ['MATERIAL_IDENTITIES']);urls=json.loads(os.environ['MATERIAL_DATABASES'])
    clients={app:httpx.Client(base_url=f'http://{app}-api:8000',auth=(identity['username'],identity['password']),timeout=10) for app,identity in identities.items()}
    db={app:psycopg.connect(url,row_factory=dict_row,autocommit=True) for app,url in urls.items()}
    def row(app,sql,*args):return db[app].execute(sql,args).fetchone()
    def get(app,path):response=clients[app].get('/api/'+path);response.raise_for_status();return response.json()
    def command(app,body):
        kind='warehouse' if app=='storage' else 'production'
        for _ in range(20):
            r=get(app,'status')['run'];payload={**body,'run_id':run,'epoch':epoch,'due_at':max(r['granted'],r['requested'])+2}
            response=clients[app].post('/api/'+kind+'/commands',json=payload,headers={'Idempotency-Key':uuid4().hex})
            if response.status_code==409 and 'Schedule' in response.text:continue
            response.raise_for_status();accepted=response.json();table='warehouse_commands' if app=='storage' else 'production_commands'
            done=wait(lambda:row(app,f'SELECT * FROM {table} WHERE id=%s',accepted['id']),lambda v:v and v['status']!='pending',app+' '+body['action'])
            assert done['status']=='completed',done
            return accepted['id']
        raise AssertionError('Could not schedule a command beyond the current grant')
    try:
        for app in clients:wait(lambda:get(app,'status'),lambda s:s['run']['state']=='running' and s['run']['granted']>0,app+' executing')
        # Fault injection changes publication metadata only. The native services
        # still own every business, inventory, movement and receipt transaction.
        for app,stages in {'manufacturing':['handling.accepted.v1','handling.received.v1','handling.acknowledged.v1'],'storage':['handling.acknowledged.v1','handling.accepted.v1','handling.received.v1']}.items():
            db[app].execute('CREATE TABLE material_transport_gate(kind text PRIMARY KEY,closed boolean NOT NULL DEFAULT true,dropped integer NOT NULL DEFAULT 0)')
            for stage in stages:db[app].execute('INSERT INTO material_transport_gate(kind) VALUES (%s)',(stage,))
            db[app].execute("""CREATE FUNCTION gate_material_publication() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF EXISTS(SELECT 1 FROM material_transport_gate WHERE kind=NEW.envelope->>'type' AND closed) THEN
                  UPDATE material_transport_gate SET dropped=dropped+1 WHERE kind=NEW.envelope->>'type';NEW.sent_at=clock_timestamp();
                END IF;RETURN NEW;END$$;
                CREATE TRIGGER gate_material_publication BEFORE INSERT ON boundary_outbox FOR EACH ROW EXECUTE FUNCTION gate_material_publication()""")
        batch=command('manufacturing',{'action':'create','product':'PRODUCT','line':'LINE-1','quantity':1});command('manufacturing',{'action':'release','reference':batch})
        shortage=wait(lambda:row('manufacturing',"SELECT * FROM production_material_failures WHERE run_id=%s AND state='applied' AND envelope->'payload'->>'action'='reserve' LIMIT 1",run),bool,'real source shortage recorded without stalling')
        assert get('manufacturing','status')['run']['state']=='running'
        assert row('manufacturing','SELECT count(*) n FROM production_handling_units WHERE run_id=%s',run)['n']==0
        unit=str(uuid4());receipt=command('storage',{'action':'expect','sku':'COMPONENT','location':'RAW-A','quantity':2,'correlation_id':str(uuid4()),'units':[{'id':unit,'quantity':2}]})
        command('storage',{'action':'receive','reference':receipt})
        shelf='storage.raw.r01.b01.l04';command('storage',{'action':'putaway','unit_id':unit,'destination':shelf})
        accepted=wait(lambda:row('manufacturing',"SELECT * FROM production_custody WHERE unit_id=%s AND state='accepted'",unit),bool,'native capacity accepted')
        source=row('storage','SELECT * FROM warehouse_handling_units WHERE id=%s',unit);stock=row('storage',"SELECT * FROM warehouse_stock WHERE run_id=%s AND sku='COMPONENT' AND location='RAW-A'",run)
        assert source['position']==shelf and source['state']=='reserved' and stock['on_hand']==stock['reserved']==2,(source,stock)
        assert row('manufacturing','SELECT count(*) n FROM production_handling_units WHERE id=%s',unit)['n']==0
        db['manufacturing'].execute("UPDATE material_transport_gate SET closed=false WHERE kind='handling.accepted.v1'")
        consumed=wait(lambda:row('manufacturing','SELECT * FROM production_handling_units WHERE id=%s',unit),lambda v:v and v['state']=='consumed','actual recipe consumes imported unit')
        assert str(consumed['batch_id'])==batch,'Imported inputs must remain assigned to their requesting batch'
        source=row('storage','SELECT * FROM warehouse_handling_units WHERE id=%s',unit)
        assert source['state']=='in_transit' and source['position'] is None,source
        assert row('manufacturing','SELECT count(*) n FROM production_unit_inputs WHERE unit_id=%s AND batch_id=%s',unit,batch)['n']==1
        assert row('manufacturing','SELECT status FROM production_orders WHERE id=%s',batch)['status']=='running'
        assert row('manufacturing',"SELECT quantity FROM production_materials WHERE run_id=%s AND sku='COMPONENT'",run)['quantity']==0
        db['manufacturing'].execute("UPDATE material_transport_gate SET closed=false WHERE kind='handling.received.v1'")
        retired=wait(lambda:row('storage','SELECT * FROM warehouse_handling_units WHERE id=%s',unit),lambda v:v['state']=='dispatched','late receipt retires same source generation')
        assert row('manufacturing','SELECT state FROM production_custody WHERE unit_id=%s',unit)['state']=='received'
        db['storage'].execute("UPDATE material_transport_gate SET closed=false WHERE kind='handling.acknowledged.v1'")
        wait(lambda:row('manufacturing','SELECT state FROM production_custody WHERE unit_id=%s',unit),lambda v:v['state']=='acknowledged','lost acknowledgement converges')
        final_source=row('storage','SELECT * FROM warehouse_handling_units WHERE id=%s',unit);final_target=row('manufacturing','SELECT * FROM production_handling_units WHERE id=%s',unit)
        assert final_source['version']==retired['version'] and final_source['custody_generation']==final_target['custody_generation']==1
        assert final_source['last_sequence']==3 and final_target['last_sequence']==4,(final_source,final_target)
        assert final_source['barcode']==final_target['barcode']=='HU-'+unit.replace('-','').upper()
        assert final_source['quantity']==final_target['quantity']==2 and final_target['position'] is None
        # Finished output is created by the actual durable finish job, never a test birth/import.
        promised=wait(lambda:row('storage',"SELECT * FROM warehouse_custody_receivers WHERE run_id=%s AND state='accepted'",run),bool,'finished dock capacity accepted')
        output_id=str(promised['unit_id']);assert output_id!=unit
        fresh=row('manufacturing','SELECT * FROM production_handling_units WHERE id=%s',output_id)
        assert fresh['state']=='reserved' and fresh['position']=='manufacturing.cell01.output01' and fresh['quantity']==1,fresh
        assert row('storage','SELECT count(*) n FROM warehouse_handling_units WHERE id=%s',output_id)['n']==0
        assert row('storage',"SELECT on_hand FROM warehouse_stock WHERE run_id=%s AND sku='PRODUCT' AND location='FINISHED-A'",run)['on_hand']==0
        assert row('manufacturing',"SELECT count(*) n FROM boundary_outbox WHERE run_id=%s AND envelope->>'type'='storage.receipt.v1'",run)['n']==0
        db['storage'].execute("UPDATE material_transport_gate SET closed=false WHERE kind='handling.accepted.v1'")
        imported=wait(lambda:row('storage','SELECT * FROM warehouse_handling_units WHERE id=%s',output_id),bool,'proved finished output imported')
        assert imported['position']==promised['destination'] and imported['barcode']==fresh['barcode'] and imported['quantity']==1
        pending=row('manufacturing','SELECT * FROM production_handling_units WHERE id=%s',output_id)
        assert pending['state']=='in_transit' and pending['position'] is None and pending['custody_generation']==1
        assert imported['version']==4 and imported['last_sequence']==3 and imported['custody_generation']==1
        # A receipt remains valid after the destination has moved the unit onward.
        command('storage',{'action':'putaway','unit_id':output_id,'destination':'storage.finished.r01.b01.l04'})
        db['storage'].execute("UPDATE material_transport_gate SET closed=false WHERE kind='handling.received.v1'")
        retired_output=wait(lambda:row('manufacturing','SELECT * FROM production_handling_units WHERE id=%s',output_id),lambda v:v['state']=='dispatched','late finished receipt retires source')
        assert retired_output['version']==4 and retired_output['last_sequence']==2
        db['manufacturing'].execute("UPDATE material_transport_gate SET closed=false WHERE kind='handling.acknowledged.v1'")
        wait(lambda:row('storage','SELECT state FROM warehouse_custody_receivers WHERE unit_id=%s',output_id),lambda v:v['state']=='acknowledged','lost finished acknowledgement converges')
        assert row('storage',"SELECT on_hand,reserved FROM warehouse_stock WHERE run_id=%s AND sku='PRODUCT' AND location='FINISHED-A'",run)=={'on_hand':1,'reserved':0}
        final_output=row('storage','SELECT * FROM warehouse_handling_units WHERE id=%s',output_id)
        assert final_output['position']=='storage.finished.r01.b01.l04' and final_output['last_sequence']==4
        mfg=get('manufacturing','production')['handling']
        for lineage in mfg['lineage']:validate_lineage(lineage,mfg['units'],run,epoch)
        assert len(mfg['lineage'])==1 and mfg['lineage'][0]['input_unit_ids']==[unit] and mfg['lineage'][0]['output_unit_ids']==[output_id]
        assert row('manufacturing','SELECT count(*) n FROM production_unit_inputs WHERE batch_id=%s',batch)['n']==1
        record.update(output_unit_id=output_id,output_barcode=fresh['barcode'],output_source_version=retired_output['version'],output_target_version=final_output['version'],lineage=mfg['lineage'])
        frames=[];drops={}
        for app in clients:
            state=get(app,'warehouse' if app=='storage' else 'production');handling=state['handling'];validate_snapshot(handling['units'],run,epoch)
            for movement in handling['movements']:validate_movement(movement,run,epoch)
            for handoff in handling['handoffs']:validate_handoff(handoff,run,epoch)
            envelopes=db[app].execute("SELECT envelope FROM boundary_outbox WHERE run_id=%s AND envelope->>'type' LIKE 'handling.%%'",(run,)).fetchall();by_event={}
            for value in envelopes:
                e=value['envelope'];validate_handoff(e['payload'],run,epoch)
                if e['event_id'] in by_event:assert by_event[e['event_id']]==e,'Retransmission changed immutable evidence'
                by_event[e['event_id']]=e
            frames.extend(by_event.values());drops[app]=db[app].execute('SELECT kind,dropped FROM material_transport_gate ORDER BY kind').fetchall()
        assert all(v['dropped']>0 for values in drops.values() for v in values),drops
        plan=row('manufacturing','SELECT p.* FROM production_material_plans p JOIN production_material_expected e ON e.reservation_id=p.id WHERE e.unit_id=%s',unit)
        assert str(plan['batch_id'])==batch and plan['status']=='received'
        attempts=db['manufacturing'].execute('SELECT a.* FROM production_material_attempts a JOIN production_material_requests r ON r.id=a.request_id WHERE r.batch_id=%s ORDER BY a.generation',(batch,)).fetchall()
        assert len(attempts)>=2 and attempts[0]['state']=='rejected' and attempts[-1]['state']=='received',attempts
        assert len({str(a['aggregate_id']) for a in attempts})==len(attempts)
        assert all(a['envelope']['payload']['quantity']==2 for a in attempts)
        assert row('storage',"SELECT on_hand,reserved FROM warehouse_stock WHERE run_id=%s AND sku='COMPONENT' AND location='RAW-A'",run)=={'on_hand':0,'reserved':0}
        record.update(status='passed',unit_id=unit,batch_id=batch,barcode=final_source['barcode'],source_sequence=3,receipt_sequence=4,source_version=final_source['version'],target_version=final_target['version'],dropped_publications=drops,handling_frames=frames,material_attempts=[{'event_id':str(a['event_id']),'aggregate_id':str(a['aggregate_id']),'generation':a['generation'],'state':a['state']} for a in attempts])
        path.write_text(json.dumps(record,indent=2,default=str));print('C#/Java native custody: raw shelf, shortage recovery, once-only recipe consumption, fresh output lineage and finished receipt after putaway; lost acceptance/receipt/ack recovery on both legs passed',flush=True)
    except Exception as error:
        record.update(status='failed',error=str(error));path.write_text(json.dumps(record,indent=2,default=str));raise
    finally:
        for value in clients.values():value.close()
        for value in db.values():value.close()


if __name__=='__main__':main()
