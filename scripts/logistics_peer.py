"""Native reference peer impersonates configured storage/shipping boundary providers only."""
import os,json,signal,time
from uuid import uuid4
from simulator.clocks import HelicsClock

def main():
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    clock=HelicsClock(os.environ['HELICS_CONFIG']);correlation=str(uuid4());external=str(uuid4());receipts=set();handoff=False
    def send(kind,payload,boundary,now,source,aggregate=None,version=1):
        event=dict(schema_version='1.0',type=kind,event_id=str(uuid4()),federation_id=os.environ['FEDERATION_ID'],
            run_id=os.environ['FEDERATION_RUN_ID'],epoch=os.environ['FEDERATION_EPOCH'],correlation_id=correlation,
            causation_id=str(uuid4()),aggregate_id=aggregate or str(uuid4()),aggregate_version=version,
            source=source,destination='logistics',boundary=boundary,effective_time=now+1,wall_time='2026-10-24T00:00:00Z',quantity_unit='item',payload=payload)
        clock.send(event,'logistics/events');clock.send(event,'logistics/events')
    try:
        clock.initialize()
        while not clock.initialized():
            if stopping:return
            time.sleep(.02)
        send('storage.transfer.completed.v1',dict(id=external,run_id=os.environ['FEDERATION_RUN_ID'],reservation_id=str(uuid4()),sku='PRODUCT',
            origin='WAREHOUSE',destination='DISPATCH',quantity=5,correlation_id=correlation,status='in_transit',version=2),'transport',0,'storage',external,2)
        target=1
        while not stopping:
            clock.request(target);grant=None
            while grant is None and not stopping:grant=clock.poll();time.sleep(.02)
            if grant is None:break
            for _,event in clock.receive():
                assert event['correlation_id']==correlation
                print('peer received '+event['type'],flush=True)
                if event['type']=='logistics.depart.completed.v1' and os.environ.get('LOGISTICS_PEER_LOSS')=='true':os._exit(0)
                if event['type']=='storage.transfer.arrived.v1':
                    assert event['payload']['reference']==external;handoff=True
                else:
                    tr=event['payload'];assert event['aggregate_version']==tr['version'];assert tr['external_reference']==external
                    if event['type']=='logistics.unload.completed.v1' and tr['id'] not in receipts:
                        assert tr['arrived_at']>=tr['planned_eta'];assert tr['received_at'] is None
                        receipts.add(tr['id']);send('logistics.receipt.v1',{'reference':tr['id']},'destinations',grant,'shipping')
                    if event['type']=='logistics.receive.completed.v1':
                        assert handoff;assert tr['status']=='received';print('STORAGE_SHIPPING_HANDOFF_CONFIRMED',flush=True)
            target=grant+1;time.sleep(.02)
    finally:clock.finalize()
if __name__=='__main__':main()
