"""Native HELICS behind HTTP: grants, ACK barriers, replay and native-loss fencing.

Run inside the adapter container; no listener is published to the host.
"""
import json
import multiprocessing as mp
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4
from wsgiref.simple_server import make_server, WSGIRequestHandler

import helics as h
from simulator.adapter import Adapter, create_app
from simulator.clocks import HelicsClock
from simulator.federation_config import config

TOKEN='isolated-adapter-fixture'

class Quiet(WSGIRequestHandler):
    def log_message(self,*args): pass


def server(name,port,journal,broker,run,epoch):
    target='shipping' if name=='storage' else 'storage'
    adapter=Adapter(journal,run,epoch,lambda:HelicsClock(config(name,broker)),name,'adapter-reference',
                    outputs=[{'endpoint':target+'/events','destination':target,'boundary':'goods'}])
    with make_server('127.0.0.1',port,create_app(adapter,TOKEN),handler_class=Quiet) as http:
        http.serve_forever()


def external(broker,proceed):
    clock=HelicsClock(config('external-power',broker,power=True))
    try:
        clock.initialize()
        deadline=time.monotonic()+30
        while not clock.initialized():
            assert time.monotonic()<deadline
            time.sleep(.01)
        clock.publish_value(25)
        assert proceed.wait(20)
        for target in (1,2):
            clock.request(target)
            while clock.poll() is None:
                assert time.monotonic()<deadline
                time.sleep(.01)
        # Retain native state until parent has inspected both business grants.
        time.sleep(2)
    finally: clock.finalize()


class Client:
    def __init__(self,port,run,epoch):
        self.url=f'http://127.0.0.1:{port}'
        self.context=dict(version='1.0',run_id=run,epoch=epoch,session_id=str(uuid4()))
    def health(self): return self.call('GET','/v1/health')
    def call(self,method,path,body=None):
        request=Request(self.url+path,data=json.dumps(body).encode() if body else None,method=method,
                        headers={'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json'})
        try:
            with urlopen(request,timeout=5) as response: return response.status,json.load(response)
        except HTTPError as exc: return exc.code,json.load(exc)
    def body(self,operation,payload=None):
        return {**self.context,'request_id':str(uuid4()),'operation':operation,'payload':payload or {}}
    def send(self,body): return self.call('POST','/v1/commands',body)
    def command(self,operation,payload=None):
        code,value=self.send(self.body(operation,payload))
        assert code==200,(code,value)
        return value['result']


def wait_for(fn,condition):
    deadline=time.monotonic()+25
    while time.monotonic()<deadline:
        try:
            value=fn()
            if condition(value): return value
        except URLError: pass
        time.sleep(.02)
    raise AssertionError('Native HTTP adapter fixture timed out')


def main():
    ctx=mp.get_context('spawn')
    run,epoch=str(uuid4()),str(uuid4())
    broker=h.helicsCreateBroker('tcp_ss','adapter-'+uuid4().hex[:8],'-f3 --port=24910 --loglevel=warning')
    address=h.helicsBrokerGetAddress(broker)
    processes=[]
    with tempfile.TemporaryDirectory() as tmp:
        try:
            clients=[]
            for i,name in enumerate(('storage','shipping')):
                port=8110+i
                process=ctx.Process(target=server,args=(name,port,str(Path(tmp)/(name+'.sqlite')),address,run,epoch))
                process.start();processes.append(process)
                client=Client(port,run,epoch);clients.append(client)
                wait_for(client.health,lambda v:v[0]==200)
            proceed=ctx.Event()
            power=ctx.Process(target=external,args=(address,proceed))
            power.start();processes.append(power)
            for client in clients: client.command('initialize')
            for client in clients: wait_for(lambda:client.command('poll'),lambda v:v['state']=='executing')
            for client in clients: client.command('request_time',dict(target=1,committed=0,pending_work=0,pending_outputs=0))
            time.sleep(.2)
            for client in clients:
                state=client.command('poll')
                assert state['pending'] is True and state['granted']==0
            proceed.set()
            for client in clients:
                state=wait_for(lambda:client.command('poll'),lambda v:v['granted']==1)
                assert state['values']['external-power/available_power_kw']==25
            for i,client in enumerate(clients):
                source,target=(('storage','shipping') if i==0 else ('shipping','storage'))
                body=dict(schema_version='1.0',type='sample.completed.v1',event_id=str(uuid4()),
                          federation_id='adapter-reference',run_id=run,epoch=epoch,
                          correlation_id=str(uuid4()),causation_id=str(uuid4()),aggregate_id=str(uuid4()),
                          aggregate_version=1,source=source,destination=target,boundary='goods',effective_time=2,
                          wall_time='2026-10-24T00:00:00Z',quantity_unit='item',payload={'quantity':2})
                command=client.body('publish',{'endpoint':target+'/events','envelope':body})
                first=client.send(command)
                assert first[0]==200 and client.send(command)==first
            for client in clients: client.command('request_time',dict(target=5,committed=1,pending_work=0,pending_outputs=0))
            for client in clients:
                state=wait_for(lambda:client.command('poll'),lambda v:v['granted']==2)
                assert state['requested']==5 and len(state['messages'])==1
                assert len(client.command('poll')['messages'])==1
                code,_=client.send(client.body('request_time',dict(target=6,committed=2,pending_work=0,pending_outputs=0)))
                assert code==409
                event=state['messages'][0]['envelope']['event_id']
                client.command('receive_ack',{'event_ids':[event]})
                assert client.command('poll')['messages']==[]
                assert client.command('checkpoint')['recoverable'] is False
            # Kill an actual HTTP/native owner, restart against its existing journal.
            processes[0].terminate();processes[0].join(3)
            replacement=ctx.Process(target=server,args=('storage',8110,str(Path(tmp)/'storage.sqlite'),address,run,epoch))
            replacement.start();processes.append(replacement)
            wait_for(clients[0].health,lambda v:v[1]['state']=='stalled')
            code,_=clients[0].send(clients[0].body('initialize'))
            assert code==409
            print('Adapter HTTP/native smoke passed: delayed grant, requested 5/granted 2, 25 kW, publication replay, durable receive ACK barrier, killed-owner restart fenced.',flush=True)
        finally:
            for process in processes:
                if process.is_alive(): process.terminate()
                process.join(3)
            h.helicsBrokerDisconnect(broker)
            h.helicsBrokerFree(broker)

if __name__=='__main__': main()
