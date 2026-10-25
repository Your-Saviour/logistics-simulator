"""Actual four-department custody and recipe proof, with twelve transport losses."""
import json
import os
import time
from pathlib import Path
from uuid import uuid4
import httpx
import psycopg
from psycopg.rows import dict_row
from simulator.handling_contracts import validate_snapshot, validate_movement, validate_handoff, validate_lineage
from simulator.wire_contracts import transport_envelope


def wait(fetch,predicate,label,timeout=150):
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
    record={'status':'running','run_id':run,'epoch':epoch,'twin_present':False,'scope':'two native recipe/order cycles, finished-rack placement/retrieval, real HTTP projections and customer receipts','steps':[]}
    identities=json.loads(os.environ['FACTORY_IDENTITIES']);urls=json.loads(os.environ['FACTORY_DATABASES'])
    clients={a:httpx.Client(base_url=f'http://{a}-api:8000',auth=(v['username'],v['password']),timeout=10) for a,v in identities.items()}
    db={a:psycopg.connect(url,row_factory=dict_row,autocommit=True) for a,url in urls.items()}
    units={'storage':'warehouse_handling_units','manufacturing':'production_handling_units','shipping':'shipping_handling_units','logistics':'transport_handling_units'}
    receivers={'manufacturing':'production_custody','storage':'warehouse_custody_receivers','shipping':'shipping_handling_handoffs','logistics':'transport_custody'}
    sources={'storage':'warehouse_custody_sources','manufacturing':'production_output_custody','shipping':'shipping_handling_departures'}
    domains={'storage':'warehouse','manufacturing':'production','shipping':'shipping','logistics':'transport'}
    legs=[('storage','manufacturing'),('manufacturing','storage'),('storage','shipping'),('shipping','logistics')]
    def save(step=None):
        if step:record['steps'].append(step);print(step,flush=True)
        path.write_text(json.dumps(record,indent=2,default=str))
    def row(app,sql,*args):return db[app].execute(sql,args).fetchone()
    def get(app,p):r=clients[app].get('/api/'+p);r.raise_for_status();return r.json()
    def unit(app,identity):return row(app,f'SELECT * FROM {units[app]} WHERE id=%s',identity)
    def command(app,body):
        for _ in range(20):
            r=get(app,'status')['run'];payload={**body,'run_id':run,'epoch':epoch,'due_at':max(r['granted'],r['requested'])+2}
            response=clients[app].post('/api/'+domains[app]+'/commands',json=payload,headers={'Idempotency-Key':uuid4().hex})
            if response.status_code==409 and 'Schedule' in response.text:continue
            response.raise_for_status();identity=response.json()['id'];table={'storage':'warehouse_commands','manufacturing':'production_commands','shipping':'shipping_commands'}[app];field='outcome' if app=='shipping' else 'status'
            done=wait(lambda:row(app,f'SELECT * FROM {table} WHERE id=%s',identity),lambda v:v and v[field]!='pending',app+' '+body['action']);assert done[field]=='completed',done;return identity
        raise AssertionError('Could not schedule a command beyond the grant')
    def gate(source,target,stage):
        sender=source if stage=='acknowledged' else target
        db[sender].execute('UPDATE factory_transport_gate SET closed=false WHERE source_owner=%s AND destination_owner=%s AND stage=%s',(source,target,stage))
    def accepted(source,target,identity):
        h=wait(lambda:row(target,f'SELECT * FROM {receivers[target]} WHERE unit_id=%s',identity),lambda v:v and v['state']=='accepted',source+' to '+target+' capacity')
        before=unit(source,identity);assert before['state']=='reserved' and before['position'] is not None,before
        assert unit(target,identity) is None,'Capacity acceptance cannot create target stock'
        gate(source,target,'accepted')
        wait(lambda:row(target,f'SELECT * FROM {receivers[target]} WHERE unit_id=%s',identity),lambda v:v and v['state']=='received',source+' to '+target+' physical receipt')
        departed=unit(source,identity);assert departed['position'] is None and departed['state']=='in_transit' and departed['custody_generation']==before['custody_generation']+1,departed
        received=unit(target,identity);assert received['barcode']==before['barcode'] and received['quantity']==before['quantity'] and received['custody_generation']>=departed['custody_generation'],received
        save(source+' to '+target+': positive capacity, unplaced departure and exact barcode receipt')
        return h
    def close(source,target,identity):
        gate(source,target,'received')
        wait(lambda:row(source,f'SELECT state FROM {sources[source]} WHERE unit_id=%s',identity),lambda v:v and v['state']=='acknowledged',source+' retires same custody')
        gate(source,target,'acknowledged')
        wait(lambda:row(target,f'SELECT state FROM {receivers[target]} WHERE unit_id=%s',identity),lambda v:v and v['state']=='acknowledged',target+' recovers lost acknowledgement')
        save(source+' to '+target+': late receipt and lost acknowledgement converged')
    save()
    try:
        for app in clients:wait(lambda:get(app,'status'),lambda s:s['run']['state']=='running' and s['run']['granted']>0,app+' native initialization')
        for app in db:
            db[app].execute('CREATE TABLE factory_transport_gate(source_owner text,destination_owner text,stage text,closed boolean NOT NULL DEFAULT true,dropped integer NOT NULL DEFAULT 0,PRIMARY KEY(source_owner,destination_owner,stage))')
            for source,target in legs:
                for stage in ('accepted','received','acknowledged'):
                    if app==(source if stage=='acknowledged' else target):db[app].execute('INSERT INTO factory_transport_gate(source_owner,destination_owner,stage) VALUES (%s,%s,%s)',(source,target,stage))
            db[app].execute("""CREATE FUNCTION factory_drop_publication() RETURNS trigger LANGUAGE plpgsql AS $$
              BEGIN IF NEW.envelope->>'type' LIKE 'handling.%' AND EXISTS(SELECT 1 FROM factory_transport_gate WHERE source_owner=NEW.envelope->'payload'->>'source' AND destination_owner=NEW.envelope->'payload'->>'destination_owner' AND stage=NEW.envelope->'payload'->>'state' AND closed) THEN
                UPDATE factory_transport_gate SET dropped=dropped+1 WHERE source_owner=NEW.envelope->'payload'->>'source' AND destination_owner=NEW.envelope->'payload'->>'destination_owner' AND stage=NEW.envelope->'payload'->>'state';NEW.sent_at=clock_timestamp(); END IF;RETURN NEW;END $$;
              CREATE TRIGGER factory_drop_publication BEFORE INSERT ON boundary_outbox FOR EACH ROW EXECUTE FUNCTION factory_drop_publication()""")
        order=command('shipping',{'action':'create','customer':'FACTORY-CUSTOMER','destination':'CUSTOMER-A','lines':[{'sku':'PRODUCT','quantity':1}]});command('shipping',{'action':'fulfil','reference':order});record['order_id']=order
        batch=wait(lambda:row('manufacturing','SELECT * FROM production_orders WHERE run_id=%s',run),bool,'actual Shipping shortage creates native Manufacturing demand')
        wait(lambda:row('manufacturing',"SELECT * FROM production_material_failures WHERE run_id=%s AND state='applied' LIMIT 1",run),bool,'actual raw shortage handled without stalling')
        raw=str(uuid4());receipt=command('storage',{'action':'expect','sku':'COMPONENT','location':'RAW-A','quantity':2,'correlation_id':str(uuid4()),'units':[{'id':raw,'quantity':2}]});command('storage',{'action':'receive','reference':receipt});command('storage',{'action':'putaway','unit_id':raw,'destination':'storage.raw.r01.b01.l04'});record.update(raw_unit_id=raw,batch_id=str(batch['id']))
        accepted('storage','manufacturing',raw)
        wait(lambda:unit('manufacturing',raw),lambda v:v['state']=='consumed','native recipe consumes the exact imported input')
        assert row('manufacturing','SELECT count(*) n FROM production_unit_inputs WHERE batch_id=%s AND unit_id=%s',batch['id'],raw)['n']==1
        consumption=[v for v in get('manufacturing','production')['handling']['movements'] if v['unit_id']==raw and v['action']=='consume']
        assert len(consumption)==1 and consumption[0]['references']['batch_id']==str(batch['id']),consumption
        assert consumption[0]['origin']==consumption[0]['destination'] and consumption[0]['origin'].startswith('manufacturing.cell'),consumption
        assert consumption[0]['sequence']==unit('manufacturing',raw)['last_sequence'],consumption
        record['input_consumption']=consumption[0]
        close('storage','manufacturing',raw)
        output=wait(lambda:row('manufacturing','SELECT * FROM production_output_custody WHERE batch_id=%s',batch['id']),bool,'durable finish creates fresh output offer');finished=str(output['unit_id']);assert finished!=raw;record['output_unit_id']=finished
        accepted('manufacturing','storage',finished)
        # This is actual positive warehouse stock feedback, not a manufactured peer fact.
        wait(lambda:row('shipping','SELECT * FROM shipping_goods_reservations WHERE run_id=%s',run),bool,'actual finished Storage receipt resumes the waiting Shipping order')
        accepted('storage','shipping',finished)
        wait(lambda:get('shipping','shipping/orders/'+order),lambda v:v['status']=='ready','own durable goods receipt makes Shipping ready before source echo')
        command('shipping',{'action':'pack','reference':order});command('shipping',{'action':'dispatch','reference':order})
        accepted('shipping','logistics',finished)
        delivered=wait(lambda:get('shipping','shipping/orders/'+order),lambda v:v['status']=='delivered','actual Go customer receipt completes Shipping while custody receipts are lost')
        journey=row('logistics','SELECT * FROM transport_transfers WHERE run_id=%s',run);assert journey['status']=='received' and journey['custody']=='destination',journey
        assert unit('logistics',finished)['position'] is None,'Customer receipt cannot invent an in-facility location'
        shipping_version=unit('shipping',finished)['version'];close('shipping','logistics',finished);assert unit('shipping',finished)['version']==shipping_version,'Late carrier receipt retired Shipping twice'
        close('storage','shipping',finished)
        wait(lambda:row('shipping',"SELECT count(*) n FROM shipping_intents WHERE order_id=%s AND kind='receive' AND state='completed'",order),lambda v:v['n']==1,'late source business confirmation settles historical goods receipt')
        assert get('shipping','shipping/orders/'+order)['status']=='delivered' and unit('shipping',finished)['version']==shipping_version,'Late goods echo reversed onward delivery'
        storage_version=unit('storage',finished)['version'];close('manufacturing','storage',finished);assert unit('storage',finished)['version']==storage_version,'Old-generation Manufacturing acknowledgement changed onward Storage custody'
        # Contradictory, schema-valid acknowledgements traverse the real native
        # transport. Only transport outbox rows are injected, never business rows.
        quarantined={}
        for source,target in legs:
            original=row(source,"SELECT envelope FROM boundary_outbox WHERE run_id=%s AND envelope->>'type'='handling.acknowledged.v1' AND envelope->'payload'->>'destination_owner'=%s LIMIT 1",run,target)['envelope']
            invalid=json.loads(json.dumps(original));invalid['event_id']=str(uuid4());invalid['payload']['receipt_id']=str(uuid4())
            # The private adapter serializes its typed envelope (including UTC
            # timestamps) before delivery. Quarantine retains that received body.
            delivered_invalid=transport_envelope.validate_python(invalid).model_dump(mode='json')
            before=get(target,domains[target])['handling']['units']
            db[source].execute('INSERT INTO boundary_outbox(id,run_id,envelope) VALUES (%s,%s,%s::jsonb)',(str(uuid4()),run,json.dumps(invalid)))
            case=wait(lambda:get(target,domains[target])['handling']['quarantine'],lambda rows:any(v['event_id']==invalid['event_id'] for v in rows),target+' retains contradictory receipt')
            case=next(v for v in case if v['event_id']==invalid['event_id'])
            assert case['phase']=='apply' and case['endpoint']==source+'/events' and case['reason'],case
            assert case['envelope']==delivered_invalid,{'retained':case['envelope'],'delivered':delivered_invalid}
            assert get(target,domains[target])['handling']['units']==before,'Quarantine changed stock, counters or placement'
            assert get(target,'status')['run']['state']=='running','Bad proof stalled an independent native department'
            quarantined[target]={'event_id':invalid['event_id'],'reason':case['reason']}
        record['quarantined_receipts']=quarantined
        save('all four native receivers retained contradictory receipts without changing units or stopping execution')
        frames=[];drops={};snapshots={}
        for app in clients:
            snapshot=get(app,domains[app]);handling=snapshot['handling'];validate_snapshot(handling['units'],run,epoch)
            for movement in handling['movements']:validate_movement(movement,run,epoch)
            for h in handling['handoffs']:validate_handoff(h,run,epoch)
            if app=='manufacturing':
                for lineage in handling['lineage']:validate_lineage(lineage,handling['units'],run,epoch)
                assert len(handling['lineage'])==1 and handling['lineage'][0]['input_unit_ids']==[raw] and handling['lineage'][0]['output_unit_ids']==[finished]
                record['lineage']=handling['lineage']
            snapshots[app]=handling;events={}
            for r in db[app].execute("SELECT envelope FROM boundary_outbox WHERE run_id=%s AND envelope->>'type' LIKE 'handling.%%'",(run,)):
                e=r['envelope'];validate_handoff(e['payload'],run,epoch)
                if e['event_id'] in events:assert events[e['event_id']]==e,'Retry changed immutable complete envelope'
                events[e['event_id']]=e
            frames.extend(events.values());drops[app]=db[app].execute('SELECT source_owner,destination_owner,stage,dropped FROM factory_transport_gate ORDER BY source_owner,destination_owner,stage').fetchall()
        assert sum(len(v) for v in drops.values())==12 and all(g['dropped']>=1 for values in drops.values() for g in values),drops
        for app in ('manufacturing','storage','shipping','logistics'):
            v=unit(app,finished);assert v['barcode']=='HU-'+finished.replace('-','').upper() and v['quantity']==1 and v['state']=='dispatched' and v['position'] is None,(app,v)
        assert [unit(a,finished)['custody_generation'] for a in ('manufacturing','storage','shipping','logistics')]==[1,2,3,3]
        assert row('storage',"SELECT sum(on_hand) on_hand,sum(reserved) reserved FROM warehouse_stock WHERE run_id=%s",run)=={'on_hand':0,'reserved':0}
        assert row('manufacturing',"SELECT quantity FROM production_materials WHERE run_id=%s AND sku='COMPONENT'",run)['quantity']==0
        assert row('manufacturing',"SELECT count(*) n FROM production_events WHERE run_id=%s",run)['n']==1
        assert len(delivered['shipment']['confirmation_id'])>0
        # A second, operator-created batch is stocked before its customer order.
        # This preserves the shortage/retry proof above and avoids racing a
        # pending customer allocation against the finished putaway command.
        rack_raw=str(uuid4())
        rack_receipt=command('storage',{'action':'expect','sku':'COMPONENT','location':'RAW-A','quantity':2,'correlation_id':str(uuid4()),'units':[{'id':rack_raw,'quantity':2}]})
        command('storage',{'action':'receive','reference':rack_receipt})
        command('storage',{'action':'putaway','unit_id':rack_raw,'destination':'storage.raw.r01.b01.l04'})
        rack_batch=command('manufacturing',{'action':'create','product':'PRODUCT','line':'LINE-1','quantity':1,'correlation_id':str(uuid4())})
        command('manufacturing',{'action':'release','reference':rack_batch})
        wait(lambda:unit('manufacturing',rack_raw),lambda value:value and value['state']=='consumed','second native recipe consumes its exact raw input')
        rack_output=wait(lambda:row('manufacturing','SELECT * FROM production_output_custody WHERE batch_id=%s',rack_batch),bool,'second native batch offers fresh finished output')
        rack_finished=str(rack_output['unit_id'])
        assert len({raw,finished,rack_raw,rack_finished})==4,'Every production output must receive a fresh immutable identity'
        wait(lambda:row('storage','SELECT state FROM warehouse_custody_receivers WHERE unit_id=%s',rack_finished),lambda value:value and value['state']=='acknowledged','second output arrives before a customer order exists')
        wait(lambda:unit('storage',rack_finished),lambda value:value and value['state']=='available','finished stock remains available for putaway')
        rack_slot='storage.finished.r01.b01.l04'
        command('storage',{'action':'putaway','unit_id':rack_finished,'destination':rack_slot})
        racked=unit('storage',rack_finished)
        assert racked['position']==rack_slot and racked['state']=='available',racked
        record['full_rack']={'raw_unit_id':rack_raw,'batch_id':rack_batch,'output_unit_id':rack_finished,'racked_record':racked}
        save('second native output placed in the finished rack before customer allocation')
        rack_order=command('shipping',{'action':'create','customer':'RACK-CUSTOMER','destination':'CUSTOMER-A','lines':[{'sku':'PRODUCT','quantity':1}]})
        command('shipping',{'action':'fulfil','reference':rack_order})
        wait(lambda:get('shipping','shipping/orders/'+rack_order),lambda value:value['status']=='ready','racked finished unit is retrieved and received by Shipping')
        command('shipping',{'action':'pack','reference':rack_order})
        command('shipping',{'action':'dispatch','reference':rack_order})
        record['full_rack']['order_id']=rack_order
        save('second customer order retrieved the finished rack unit and requested carrier dispatch')
        rack_delivery=wait(lambda:get('shipping','shipping/orders/'+rack_order),lambda value:value['status']=='delivered','second native order reaches the customer')
        current={app:get(app,domains[app])['handling'] for app in domains}
        movements=current['storage']['movements']
        putaway=[move for move in movements if move['unit_id']==rack_finished and move['action']=='putaway' and move['destination']==rack_slot]
        retrieval=[move for move in movements if move['unit_id']==rack_finished and move['action']=='retrieve' and move['origin']==rack_slot]
        assert len(putaway)==len(retrieval)==1 and putaway[0]['sequence']<retrieval[0]['sequence'],(putaway,retrieval)
        assert retrieval[0]['destination'].startswith('storage.outbound.dock'),retrieval
        raw_moves=[move for move in movements if move['unit_id']==rack_raw]
        assert any(move['action']=='receive' and move['destination'].startswith('storage.inbound.dock') for move in raw_moves),raw_moves
        assert any(move['action']=='putaway' and move['destination']=='storage.raw.r01.b01.l04' for move in raw_moves),raw_moves
        rack_lineage=[lineage for lineage in current['manufacturing']['lineage'] if lineage['batch_id']==rack_batch]
        assert len(rack_lineage)==1 and rack_lineage[0]['input_unit_ids']==[rack_raw] and rack_lineage[0]['output_unit_ids']==[rack_finished],rack_lineage
        assert unit('manufacturing',rack_raw)['position'] is None and unit('logistics',rack_finished)['position'] is None
        assert row('storage',"SELECT sum(on_hand) on_hand,sum(reserved) reserved FROM warehouse_stock WHERE run_id=%s",run)=={'on_hand':0,'reserved':0}
        assert row('manufacturing',"SELECT count(*) n FROM production_events WHERE run_id=%s",run)['n']==2
        record['full_rack']={'raw_unit_id':rack_raw,'batch_id':rack_batch,'output_unit_id':rack_finished,'order_id':rack_order,'racked_record':racked,'putaway':putaway[0],'retrieval':retrieval[0],'lineage':rack_lineage[0],'customer_receipt':rack_delivery['shipment']['confirmation_id']}
        save('second native cycle traversed raw receipt, raw shelf, manufacturing, finished shelf, retrieval and customer delivery')

        # Validate real HTTP producer envelopes, not reconstructed test events.
        from twin.projection import validate as validate_projection
        from twin.handling_projection import reconcile_handling
        projections={app:get(app,'projection') for app in domains}
        record['projections']=projections
        save('captured complete real HTTP projections for validation and replay')
        observed=[]
        for app,projection in projections.items():
            validate_projection({'name':app},projection)
            observed.append({'name':app,'snapshot':projection['snapshot'],'status':{'run':projection['run']},'connected':True})
        canonical=reconcile_handling(observed)
        record['reconciled_handling']=canonical
        assert len(canonical['units'])==4 and all(value['status']=='confirmed' and value['position'] is None for value in canonical['units']),canonical
        save('all four real HTTP projections agree with durable movements, lineage and receipt-based terminal custody')
        record.update(status='passed',dropped_publications=drops,handling_frames=frames,handling=current,primary_handling=snapshots,customer_receipt={'journey_id':str(journey['id']),'destination':journey.get('customer_destination'),'received_at':journey['received_at']},twin_present=False);save('four native departments completed two conserved recipe/order cycles, the finished rack and all twelve first-cycle transport losses')
    except Exception as error:
        record.update(status='failed',error=str(error),diagnostics={})
        # Preserve authoritative queue and transport state before disposable
        # databases are removed, so a failed wait does not require a blind rerun.
        for app,connection in db.items():
            details={}
            for table in ('runs','jobs','boundary_outbox','boundary_inbox',
                          'transport_transfers','transport_expected_units',
                          'transport_commands','transport_vehicles'):
                try:
                    if connection.execute('SELECT to_regclass(%s) AS name',(table,)).fetchone()['name']:
                        details[table]=connection.execute(f'SELECT * FROM {table} LIMIT 500').fetchall()
                except Exception as diagnostic_error:
                    details[table]={'error':str(diagnostic_error)}
            record['diagnostics'][app]=details
        save()
        raise
    finally:
        for c in clients.values():c.close()
        for c in db.values():c.close()


if __name__=='__main__':main()
