import os
import time
import pika
import structlog
import consumer
import db

log = structlog.get_logger()

RABBITMQ_HOST = os.environ["RABBITMQ_HOST"]
RABBITMQ_USER = os.environ["RABBITMQ_USER"]
RABBITMQ_PASSWORD = os.environ["RABBITMQ_PASSWORD"]
EXCHANGE = os.environ["RABBITMQ_EXCHANGE"]
QUEUE = os.environ["RABBITMQ_QUEUE"]
DEAD_LETTER_QUEUE = os.environ["RABBITMQ_DEAD_LETTER_QUEUE"]


def connect_rabbitmq():
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
    params = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        credentials=credentials,
        heartbeat=60,
        blocked_connection_timeout=300,
    )
    while True:
        try:
            conn = pika.BlockingConnection(params)
            log.info("connected to rabbitmq")
            return conn
        except Exception:
            log.warning("rabbitmq not ready, retrying in 3s")
            time.sleep(3)


def setup_channel(rmq_conn):
    channel = rmq_conn.channel()

    # Dead-letter exchange
    channel.exchange_declare(
        exchange=f"{EXCHANGE}.dlx",
        exchange_type="direct",
        durable=True,
    )
    channel.queue_declare(queue=DEAD_LETTER_QUEUE, durable=True)
    channel.queue_bind(
        queue=DEAD_LETTER_QUEUE,
        exchange=f"{EXCHANGE}.dlx",
        routing_key=QUEUE,
    )

    # Main exchange + queue
    channel.exchange_declare(exchange=EXCHANGE, exchange_type="direct", durable=True)
    channel.queue_declare(
        queue=QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": f"{EXCHANGE}.dlx",
            "x-dead-letter-routing-key": QUEUE,
        },
    )
    channel.queue_bind(queue=QUEUE, exchange=EXCHANGE, routing_key=QUEUE)
    channel.basic_qos(prefetch_count=1)
    return channel


def main():
    pg_conn = db.get_connection()
    log.info("connected to postgres")

    rmq_conn = connect_rabbitmq()
    channel = setup_channel(rmq_conn)

    def on_message(ch, method, properties, body):
        try:
            consumer.handle_message(pg_conn, body)
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception:
            log.exception("nacking message")
            try:
                pg_conn.rollback()
            except Exception:
                log.exception("rollback failed")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    channel.basic_consume(queue=QUEUE, on_message_callback=on_message)
    log.info("loader waiting for messages", queue=QUEUE)
    channel.start_consuming()


if __name__ == "__main__":
    main()
