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
    q: str | None = None,
    flair: str | None = None,
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

    # Build WHERE clause dynamically
    conditions = ["subreddit = $1"]
    params: list = [subreddit]

    def p(value) -> str:
        params.append(value)
        return f"${len(params)}"

    if after_ts is not None:
        conditions.append(f"timestamp < {p(after_ts)}")
    if before_ts is not None:
        # "before" = newer posts when used alone; combined with after it's a range
        op = ">" if after_ts is None else ">"
        conditions.append(f"timestamp {op} {p(before_ts)}")

    if q:
        pn = p(f"%{q}%")
        conditions.append(f"(data->>'title' ILIKE {pn} OR data->>'text' ILIKE {pn})")

    if flair:
        conditions.append(f"data->>'flair' ILIKE {p(flair)}")

    where = " AND ".join(conditions)
    # "before" alone = newer posts → ASC so we can reverse to get DESC output
    order = "ASC" if (before_ts is not None and after_ts is None) else "DESC"
    limit_pn = p(limit)

    rows = await pool.fetch(
        f"SELECT data FROM posts WHERE {where} ORDER BY timestamp {order} LIMIT {limit_pn}",
        *params,
    )

    if before_ts is not None and after_ts is None:
        rows = list(reversed(rows))

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
