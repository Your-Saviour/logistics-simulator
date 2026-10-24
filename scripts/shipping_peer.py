"""Controlled native HELICS wire peer; PHP alone owns shipping business state.

This fixture supplies typed stock/carrier records, without running the real C#,
Java or Go departments. Files only gate native requests/confirmations for QA.
"""
import json
import os
from pathlib import Path
import signal
import time
from uuid import uuid4

import helics as h
from simulator.clocks import HelicsClock

CONTROL = Path('/control')


def main():
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    clock = HelicsClock(os.environ['HELICS_CONFIG'])
    run = os.environ['FEDERATION_RUN_ID']
    epoch = os.environ['FEDERATION_EPOCH']
    state = {'order_event_id': str(uuid4()), 'received': [], 'sent': [], 'reserve_counts': {}, 'planned_etas': []}
    reservations, transfers, carriers = {}, {}, {}
    reserved = set()
    arrival_queue = []
    order = None
    grant = 0

    def save():
        temporary = CONTROL / 'peer-state.tmp'
        temporary.write_text(json.dumps(state))
        temporary.replace(CONTROL / 'peer-state.json')

    def envelope(kind, payload, source, correlation, causation, aggregate, effective, version=1):
        return {'schema_version': '1.0', 'type': kind, 'event_id': str(uuid4()),
                'federation_id': os.environ['FEDERATION_ID'], 'run_id': run, 'epoch': epoch,
                'correlation_id': correlation, 'causation_id': causation, 'aggregate_id': aggregate,
                'aggregate_version': version, 'source': source, 'destination': 'shipping',
                'boundary': 'orders' if source == 'external-orders' else ('carrier' if source == 'logistics' else 'goods'),
                'effective_time': effective, 'wall_time': '2026-10-24T00:00:00Z', 'quantity_unit': 'item', 'payload': payload}

    def send(event, rogue=False):
        if rogue:
            endpoint = h.helicsFederateGetEndpointByIndex(clock.federate, 1)
            h.helicsEndpointSendBytesTo(endpoint, json.dumps(event), 'shipping/events')
        else:
            clock.send(event, 'shipping/events')
        state['sent'].append({'type': event['type'], 'event_id': event['event_id'], 'effective_time': event['effective_time']})
        save()

    def stock_fact(kind, record, incoming, effective=None):
        send(envelope('storage.' + kind + '.completed.v1', record, 'storage', incoming['correlation_id'],
                      incoming['event_id'], record['id'], effective if effective is not None else grant + 1, record['version']))

    try:
        clock.initialize()
        deadline = time.monotonic() + 600
        while not clock.initialized():
            if stopping:
                return
            assert time.monotonic() < deadline, 'Controlled peer initialization timed out'
            time.sleep(.02)
        order = envelope('shipping.order.v1', {'customer': 'NATIVE-CUSTOMER', 'destination': 'CUSTOMER-A',
                         'lines': [{'sku': 'PRODUCT', 'quantity': 3}, {'sku': 'SECONDARY', 'quantity': 2}]},
                         'external-orders', str(uuid4()), str(uuid4()), str(uuid4()), 20)
        order['event_id'] = state['order_event_id']
        state['order_correlation_id'] = order['correlation_id']
        send(order)
        save()
        target = 1
        replayed = False
        delivery_stage = 0
        rogue_sent = False
        while not stopping:
            clock.request(target)
            grant = None
            while grant is None and not stopping:
                grant = clock.poll()
                time.sleep(.02)
            if grant is None:
                break
            state['granted'] = grant
            for source, incoming in clock.receive():
                assert source == 'shipping/events', source
                assert incoming['source'] == 'shipping' and incoming['run_id'] == run and incoming['epoch'] == epoch
                assert incoming['aggregate_id'] == incoming['event_id'] and incoming['aggregate_version'] == 1
                state['received'].append({'type': incoming['type'], 'event_id': incoming['event_id'], 'time': grant})
                payload, kind = incoming['payload'], incoming['type']
                state['correlation_id'] = incoming['correlation_id']
                if kind == 'storage.request.v1':
                    sku = payload['sku']
                    state['reserve_counts'][sku] = state['reserve_counts'].get(sku, 0) + 1
                    if sku == 'PRODUCT' and state['reserve_counts'][sku] == 1:
                        command = {'action': 'reserve', **payload, 'run_id': run, 'epoch': epoch,
                                   'due_at': incoming['effective_time'], 'correlation_id': incoming['correlation_id']}
                        send(envelope('storage.command.rejected.v1', {'action': 'reserve',
                             'reason': 'Insufficient available stock; complete quantities required', 'request': command},
                             'storage', incoming['correlation_id'], incoming['event_id'], incoming['event_id'], grant + 1))
                    else:
                        record = {**payload, 'id': str(uuid4()), 'run_id': run, 'correlation_id': incoming['correlation_id'],
                                  'status': 'reserved', 'version': 1}
                        reservations[record['id']] = record
                        reserved.add(sku)
                        stock_fact('reserve', record, incoming)
                elif kind == 'manufacturing.demand.v1':
                    record = {'id': str(uuid4()), 'run_id': run, 'sku': payload['product'], 'location': 'FINISHED-A',
                              'quantity': payload['quantity'], 'correlation_id': incoming['correlation_id'], 'status': 'received', 'version': 2}
                    stock_fact('receive', record, incoming)
                elif kind == 'storage.pick.v1':
                    assert reserved == {'PRODUCT', 'SECONDARY'}, 'Shipping picked before reserving every complete line'
                    record = {**reservations[payload['reference']], 'status': 'picked', 'version': 2}
                    stock_fact('pick', record, incoming)
                elif kind == 'storage.transfer.v1':
                    reservation = reservations[payload['reference']]
                    record = {'id': str(uuid4()), 'run_id': run, 'reservation_id': reservation['id'],
                              'sku': reservation['sku'], 'origin': reservation['location'], 'destination': payload['destination'],
                              'quantity': reservation['quantity'], 'correlation_id': incoming['correlation_id'],
                              'status': 'in_transit', 'version': 1}
                    transfers[record['id']] = record
                    stock_fact('transfer', record, incoming)
                    arrival_queue.append((grant + 2, {**record, 'status': 'received', 'version': 2}, incoming))
                elif kind == 'logistics.request.v1':
                    record = {'id': str(uuid4()), 'run_id': run, 'epoch': epoch, 'correlation_id': incoming['correlation_id'],
                              'external_reference': payload['external_reference'], 'route': payload['route'], 'origin': 'DISPATCH',
                              'destination': 'CUSTOMER-A', 'journey_seconds': 2.0, 'sku': payload['sku'], 'quantity': payload['quantity'],
                              'vehicle': 'TRUCK-1', 'status': 'in_transit', 'custody': 'vehicle', 'provider': True, 'version': 4,
                              'planned_eta': grant + 2, 'departed_at': grant, 'arrived_at': None, 'unloaded_at': None, 'received_at': None}
                    carriers[record['id']] = (record, incoming)
                    state['planned_etas'].append(record['planned_eta'])
                    send(envelope('logistics.depart.completed.v1', record, 'logistics', incoming['correlation_id'],
                                  incoming['event_id'], record['id'], grant + 1, 4))
                else:
                    raise AssertionError('Unexpected shipping output: ' + kind)
            for due, record, incoming in list(arrival_queue):
                if grant >= due:
                    stock_fact('arrive', record, incoming)
                    arrival_queue.remove((due, record, incoming))
            delivery_gate = 'delivery.release' if delivery_stage == 0 else 'delivery.final'
            if carriers and delivery_stage < 2 and (CONTROL / delivery_gate).exists():
                assert len(carriers) == 2, 'Expected one confirmed carrier departure per line'
                record, incoming = list(carriers.values())[delivery_stage]
                received = {**record, 'status': 'received', 'custody': 'destination', 'version': 7,
                            'arrived_at': grant, 'unloaded_at': grant, 'received_at': grant}
                send(envelope('logistics.receive.completed.v1', received, 'logistics', incoming['correlation_id'],
                              incoming['event_id'], record['id'], grant + 1, 7))
                delivery_stage += 1
                state['destination_receipts'] = delivery_stage
            if (CONTROL / 'inject-owner').exists() and not rogue_sent:
                bad = {**order, 'event_id': str(uuid4()), 'aggregate_id': str(uuid4()), 'effective_time': grant + 1}
                send(bad, rogue=True)
                state['rogue_event_id'] = bad['event_id']
                rogue_sent = True
            save()
            if grant == 1:
                while not stopping and not (CONTROL / 'future.release').exists():
                    time.sleep(.02)
                if not stopping and not replayed:
                    # Repeat after the verifier observed durable acceptance/ACK, before due_at.
                    send(order)
                    replayed = True
            target = grant + 1
            time.sleep(.02)
    finally:
        clock.finalize()


if __name__ == '__main__':
    main()
