"""Synthetic external HELICS warehouse peer for isolated contract acceptance.

This replaces configured supply/request boundaries; it never executes warehouse
business state. Every stock effect remains in the C# worker.
"""
import json
import os
import signal
import time
from uuid import uuid4
from simulator.clocks import HelicsClock


def main():
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop)
    clock=HelicsClock(os.environ['HELICS_CONFIG'])
    correlation=str(uuid4())
    def send(kind,payload,boundary,now):
        event={'schema_version':'1.0','type':kind,'event_id':str(uuid4()),'federation_id':os.environ['FEDERATION_ID'],
               'run_id':os.environ['FEDERATION_RUN_ID'],'epoch':os.environ['FEDERATION_EPOCH'],
               'correlation_id':correlation,'causation_id':str(uuid4()),'aggregate_id':str(uuid4()),'aggregate_version':1,
               'source':'warehouse-peer','destination':'storage','boundary':boundary,'effective_time':now+1,
               'wall_time':'2026-10-24T00:00:00Z','quantity_unit':'item','payload':payload}
        clock.send(event,'storage/events')
        clock.send(event,'storage/events')  # Actual native duplicate delivery.
    try:
        clock.initialize()
        while not clock.initialized():
            if stopping:return
            time.sleep(.02)
        for sku,location in [('COMPONENT','RAW-A'),('PRODUCT','FINISHED-A')]:
            send('storage.receipt.v1',{'sku':sku,'location':location,'quantity':8},'supply',0)
        target=1
        requested=set();arrived=set()
        while not stopping:
            clock.request(target);grant=None
            while grant is None and not stopping:
                grant=clock.poll();time.sleep(.02)
            if grant is None:break
            for _,event in clock.receive():
                print('peer received '+event['type'],flush=True)
                assert event['correlation_id']==correlation
                record=event['payload']
                assert event['aggregate_version']==record['version']
                if event['type']=='storage.receive.completed.v1' and record['sku'] not in requested:
                    requested.add(record['sku'])
                    send('storage.request.v1',{'sku':record['sku'],'location':record['location'],'quantity':5,
                         'purpose':'production' if record['sku']=='COMPONENT' else 'customer'},'requests',grant)
                if event['type']=='storage.transfer.completed.v1' and record['id'] not in arrived:
                    arrived.add(record['id'])
                    send('storage.transfer.arrived.v1',{'reference':record['id']},'requests',grant)
            target=grant+1;time.sleep(.02)
    finally:clock.finalize()


if __name__=='__main__':main()
