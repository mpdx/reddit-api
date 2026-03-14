import json
import os
import time
import pika
import structlog

log = structlog.get_logger()

RABBITMQ_HOST = os.environ["RABBITMQ_HOST"]
RABBITMQ_USER = os.environ["RABBITMQ_USER"]
RABBITMQ_PASSWORD = os.environ["RABBITMQ_PASSWORD"]
EXCHANGE = os.environ["RABBITMQ_EXCHANGE"]
QUEUE = os.environ["RABBITMQ_QUEUE"]

_connection: pika.BlockingConnection | None = None
_channel: pika.adapters.blocking_connection.BlockingChannel | None = None


def _connect():
    global _connection, _channel
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
    params = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        credentials=credentials,
        heartbeat=60,
        blocked_connection_timeout=300,
    )
    while True:
        try:
            _connection = pika.BlockingConnection(params)
            _channel = _connection.channel()
            _channel.exchange_declare(
                exchange=EXCHANGE, exchange_type="direct", durable=True
            )
            _channel.queue_declare(
                queue=QUEUE,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": f"{EXCHANGE}.dlx",
                    "x-dead-letter-routing-key": QUEUE,
                },
            )
            _channel.queue_bind(queue=QUEUE, exchange=EXCHANGE, routing_key=QUEUE)
            log.info("connected to rabbitmq")
            return
        except Exception:
            log.warning("rabbitmq not ready, retrying in 3s")
            time.sleep(3)


def _ensure_connected():
    global _connection, _channel
    if _connection is None or _connection.is_closed:
        _connect()


def publish_one(post: dict):
    _ensure_connected()
    body = json.dumps(post, default=str).encode()
    _channel.basic_publish(
        exchange=EXCHANGE,
        routing_key=QUEUE,
        body=body,
        properties=pika.BasicProperties(
            delivery_mode=pika.DeliveryMode.Persistent,
            content_type="application/json",
        ),
    )
    log.info("published post", post_id=post.get("id"))
