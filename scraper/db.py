import os
import psycopg2
import structlog

log = structlog.get_logger()


def get_connection():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def get_watched_posts(conn) -> tuple[list[dict], object]:
    """Return posts where watch_until > NOW(). Reconnects if connection is lost."""
    try:
        conn.isolation_level  # cheap liveness check
    except Exception:
        log.warning("postgres connection lost, reconnecting")
        conn = get_connection()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT post_id, data FROM posts WHERE watch_until > NOW() ORDER BY watch_until ASC"
        )
        rows = cur.fetchall()

    log.info("fetched watched posts", count=len(rows))
    return [{"post_id": r[0], "data": r[1]} for r in rows], conn
