"""RabbitMQ carries internal job IDs only. Boundary events use HELICS."""
import json

import pika

QUEUE = 'sample.jobs.v1'
DEAD_QUEUE = 'sample.jobs.dead.v1'


def connect(url):
    params = pika.URLParameters(url)
    params.socket_timeout = 3
    params.blocked_connection_timeout = 5
    params.heartbeat = 30
    return pika.BlockingConnection(params)


def channel_for(connection):
    channel = connection.channel()
    channel.exchange_declare('sample.dead.v1', exchange_type='direct', durable=True)
    channel.queue_declare(DEAD_QUEUE, durable=True)
    channel.queue_bind(DEAD_QUEUE, 'sample.dead.v1', routing_key='dead')
    channel.queue_declare(QUEUE, durable=True, arguments={'x-dead-letter-exchange': 'sample.dead.v1', 'x-dead-letter-routing-key': 'dead'})
    channel.basic_qos(prefetch_count=1)
    channel.confirm_delivery()
    return channel


def broker_ready(url):
    try:
        connection = connect(url)
        connection.close()
        return True
    except pika.exceptions.AMQPError:
        return False


def relay(store, channel):
    for row in store.dispatchable():
        channel.basic_publish(exchange='', routing_key=QUEUE, body=json.dumps({'job_id': str(row['job_id'])}),
                              properties=pika.BasicProperties(delivery_mode=2, content_type='application/json', message_id=str(row['id'])), mandatory=True)
        store.published(row['id'])
