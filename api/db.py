import json
import os
import asyncpg
import structlog

log = structlog.get_logger()

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=os.environ["POSTGRES_HOST"],
            database=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            min_size=2,
            max_size=10,
        )
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def get_posts_for_subreddit(
    subreddit: str,
    after_id: str | None = None,
    before_id: str | None = None,
    limit: int = 25,
) -> list[dict]:
    pool = await get_pool()

    # Resolve cursors to timestamps
    after_ts: int | None = None
    before_ts: int | None = None

    if after_id:
        row = await pool.fetchrow(
            "SELECT timestamp FROM posts WHERE post_id = $1", after_id
        )
        if row:
            after_ts = row["timestamp"]

    if before_id:
        row = await pool.fetchrow(
            "SELECT timestamp FROM posts WHERE post_id = $1", before_id
        )
        if row:
            before_ts = row["timestamp"]

    if after_ts is not None and before_ts is not None:
        rows = await pool.fetch(
            """
            SELECT data FROM posts
            WHERE subreddit = $1 AND timestamp < $2 AND timestamp > $3
            ORDER BY timestamp DESC
            LIMIT $4
            """,
            subreddit, after_ts, before_ts, limit,
        )
    elif after_ts is not None:
        # "after" in Reddit = older posts (timestamp < cursor)
        rows = await pool.fetch(
            """
            SELECT data FROM posts
            WHERE subreddit = $1 AND timestamp < $2
            ORDER BY timestamp DESC
            LIMIT $3
            """,
            subreddit, after_ts, limit,
        )
    elif before_ts is not None:
        # "before" in Reddit = newer posts (timestamp > cursor), maintain DESC order
        rows = await pool.fetch(
            """
            SELECT data FROM posts
            WHERE subreddit = $1 AND timestamp > $2
            ORDER BY timestamp ASC
            LIMIT $3
            """,
            subreddit, before_ts, limit,
        )
        rows = list(reversed(rows))
    else:
        rows = await pool.fetch(
            """
            SELECT data FROM posts
            WHERE subreddit = $1
            ORDER BY timestamp DESC
            LIMIT $2
            """,
            subreddit, limit,
        )

    return [json.loads(r["data"]) for r in rows]


async def get_post_with_comments(post_id: str) -> dict | None:
    pool = await get_pool()

    row = await pool.fetchrow(
        "SELECT data FROM posts WHERE post_id = $1", post_id
    )
    if not row:
        return None

    post = json.loads(row["data"])

    comment_row = await pool.fetchrow(
        "SELECT data FROM comments WHERE post_id = $1", post_id
    )
    post["comments"] = json.loads(comment_row["data"]) if comment_row else []

    return post
