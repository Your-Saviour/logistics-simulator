import json
import logging
import signal
import time
from uuid import UUID

import pika
import psycopg

from .config import Settings
from .messaging import connect, channel_for, relay, QUEUE
from .store import Store

log = logging.getLogger(__name__)


def process_delivery(store, channel, method, body):
    try:
        message = json.loads(body)
        job_id = UUID(str(message['job_id']))
    except (ValueError, KeyError, TypeError):
        channel.basic_nack(method.delivery_tag, requeue=False)
        return
    try:
        result = store.execute(job_id)
    except psycopg.Error:
        # A DB outage is not a business failure and must not burn retry budget.
        # Close/reconnect without ACK; the broker retains the delivery.
        raise
    except Exception as exc:
        log.exception('Job failed')
        result = store.fail_job(job_id, str(exc))
    if result == 'dead':
        channel.basic_nack(method.delivery_tag, requeue=False)
    else:
        # Waiting/retry jobs remain in PostgreSQL and the relay resends them.
        channel.basic_ack(method.delivery_tag)


def main():
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    store = Store(settings.database_url, settings.mode, settings.run_id, settings.epoch)
    store.migrate()
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        connection = None
        try:
            connection = connect(settings.amqp_url)
            channel = channel_for(connection)
            while not stopping:
                relay(store, channel)
                method, _, body = channel.basic_get(QUEUE, auto_ack=False)
                if method:
                    process_delivery(store, channel, method, body)
                store.heartbeat('worker')
                connection.process_data_events(time_limit=0.1)
                if not method:
                    time.sleep(0.15)
        except (pika.exceptions.AMQPError, psycopg.Error, OSError):
            log.exception('Dependency unavailable; durable work retained')
            time.sleep(2)
        finally:
            if connection and connection.is_open:
                connection.close()


if __name__ == '__main__':
    main()
