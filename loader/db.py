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

    viral_enabled = os.environ.get("VIRAL_ENABLED", "false").lower() == "true"
    initial_points = int(os.environ.get("VIRAL_INITIAL_POINTS", 500))
    min_delta = int(os.environ.get("VIRAL_MIN_DELTA", 50))
    watch_days = int(os.environ.get("VIRAL_WATCH_DAYS", 7))

    post_data = json.dumps(post)

    with conn.cursor() as cur:
        if not viral_enabled:
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
        else:
            cur.execute(
                """
                INSERT INTO posts (post_id, subreddit, timestamp, scraped_at, data, watch_until)
                VALUES (
                    %s, %s, %s, %s, %s,
                    CASE WHEN CAST(%s::jsonb->>'points' AS INTEGER) >= %s
                         THEN NOW() + make_interval(days => %s)
                         ELSE NULL END
                )
                ON CONFLICT (post_id) DO UPDATE SET
                    subreddit  = EXCLUDED.subreddit,
                    timestamp  = EXCLUDED.timestamp,
                    scraped_at = EXCLUDED.scraped_at,
                    data       = EXCLUDED.data,
                    watch_until = CASE
                        -- not yet watched: start if above initial threshold
                        WHEN posts.watch_until IS NULL
                             AND CAST(EXCLUDED.data->>'points' AS INTEGER) >= %s
                        THEN NOW() + make_interval(days => %s)
                        -- currently watched: extend if delta is sufficient
                        WHEN posts.watch_until IS NOT NULL
                             AND (CAST(EXCLUDED.data->>'points' AS INTEGER)
                                  - CAST(posts.data->>'points' AS INTEGER)) >= %s
                        THEN NOW() + make_interval(days => %s)
                        -- currently watched but delta too small: stop watching
                        WHEN posts.watch_until IS NOT NULL
                        THEN NULL
                        -- not watched, below threshold: leave as NULL
                        ELSE NULL
                    END
                """,
                (
                    post_id, subreddit, timestamp, scraped_at, post_data,
                    post_data, initial_points, watch_days,   # INSERT watch_until
                    initial_points, watch_days,               # ON CONFLICT: start watching
                    min_delta, watch_days,                    # ON CONFLICT: extend
                ),
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
