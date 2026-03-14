import json
import os
import psycopg2
import psycopg2.extras
import structlog

log = structlog.get_logger()


def get_connection():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def upsert_post(conn, post: dict):
    post_id = post["id"]
    subreddit = post["subreddit"]
    timestamp = post["timestamp_millis"]
    scraped_at = post["scrapedAt"]
    comments = post.pop("comments", [])

    post_data = json.dumps(post)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO posts (post_id, subreddit, timestamp, scraped_at, data)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (post_id) DO UPDATE SET
                subreddit  = EXCLUDED.subreddit,
                timestamp  = EXCLUDED.timestamp,
                scraped_at = EXCLUDED.scraped_at,
                data       = EXCLUDED.data
            """,
            (post_id, subreddit, timestamp, scraped_at, post_data),
        )

    upsert_comments(conn, post_id, comments)
    conn.commit()
    log.info("upserted post", post_id=post_id, subreddit=subreddit)


def upsert_comments(conn, post_id: str, comments: list):
    comment_data = json.dumps(comments)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO comments (post_id, data)
            VALUES (%s, %s)
            ON CONFLICT (post_id) DO UPDATE SET data = EXCLUDED.data
            """,
            (post_id, comment_data),
        )
