import json
import structlog
import db

log = structlog.get_logger()


def handle_message(conn, body: bytes):
    try:
        post = json.loads(body)
        db.upsert_post(conn, post)
    except Exception:
        log.exception("failed to handle message")
        raise
