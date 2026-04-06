import os
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

import db

log = structlog.get_logger()

VALID_SORTS = {"hot", "new", "top", "rising", "controversial", "best"}
VALID_TIME_FILTERS = {"hour", "day", "week", "month", "year", "all"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.get_pool()
    log.info("database pool ready")
    yield
    await db.close_pool()
    log.info("database pool closed")


app = FastAPI(lifespan=lifespan)


def strip_prefix(fullname: str) -> str:
    for prefix in ("t3_", "t1_", "t2_"):
        if fullname.startswith(prefix):
            return fullname[len(prefix):]
    return fullname


def format_post(post: dict) -> dict:
    p = dict(post)
    raw_id = strip_prefix(p.pop("id", ""))
    subreddit = p.pop("subreddit", "")
    if subreddit.startswith("r/"):
        subreddit = subreddit[2:]
    return {
        "id": raw_id,
        "subreddit": subreddit,
        "title": p.get("title", ""),
        "body": p.get("text", ""),
        "author": p.get("author", ""),
        "score": p.get("points", 0),
        "postType": p.get("dataType", ""),
        "linkUrl": p.get("dataURL", ""),
        "isGallery": p.get("isGallery", False),
        "isPromoted": p.get("isPromoted", False),
        "flair": p.get("flair"),
        "createdAt": p.get("timestamp", ""),
        "scrapedAt": p.get("scrapedAt", ""),
        "permalink": f"/r/{subreddit}/comments/{raw_id}",
        "url": p.get("url", ""),
    }


def format_comment(comment: dict) -> dict:
    c = dict(comment)
    replies = c.pop("children", None) or c.pop("replies", None) or []
    c.pop("isCollapsed", None)
    return {
        "id": strip_prefix(c.get("id", "")),
        "author": c.get("author", ""),
        "body": c.get("comment", ""),
        "score": c.get("points", 0),
        "createdAt": c.get("time", ""),
        "isDeleted": c.get("isDeleted", False),
        "replies": [format_comment(r) for r in replies],
    }


def make_post_list_response(posts: list, after: str | None, before: str | None) -> dict:
    return {
        "posts": [format_post(p) for p in posts],
        "pagination": {
            "after": after,
            "before": before,
            "count": len(posts),
        },
    }


@app.get("/")
async def health():
    return "OK"


@app.get("/r/{subreddit}/comments/{article}")
@app.get("/comments/{article}")
async def get_comments(article: str, subreddit: str = ""):
    article_id = article if article.startswith("t3_") else f"t3_{article}"
    post = await db.get_post_with_comments(article_id)
    if post is None:
        raise HTTPException(status_code=404, detail="post not found")

    comments = post.pop("comments", []) or []

    return JSONResponse(content={
        "post": format_post(post),
        "comments": [format_comment(c) for c in comments],
    })


@app.get("/r/{subreddit}")
@app.get("/r/{subreddit}/{sort}")
async def get_subreddit(
    subreddit: str,
    sort: str = "hot",
    after: str = Query(default=""),
    before: str = Query(default=""),
    limit: int = Query(default=25, ge=1, le=100),
    t: str = Query(default="all"),
    q: str = Query(default=""),
    flair: str = Query(default=""),
):
    if sort not in VALID_SORTS:
        raise HTTPException(status_code=404, detail="invalid sort")
    if t not in VALID_TIME_FILTERS:
        raise HTTPException(status_code=400, detail="invalid time filter")

    prefixed = f"r/{subreddit}"
    # Restore t3_ prefix for DB lookup (DB stores IDs with prefix)
    after_id = f"t3_{strip_prefix(after)}" if after else None
    before_id = f"t3_{strip_prefix(before)}" if before else None

    posts = await db.get_posts_for_subreddit(
        prefixed,
        after_id=after_id,
        before_id=before_id,
        limit=limit,
        q=q or None,
        flair=flair or None,
    )

    next_after = strip_prefix(posts[-1]["id"]) if posts else None
    next_before = strip_prefix(posts[0]["id"]) if posts else None

    return JSONResponse(content=make_post_list_response(posts, next_after, next_before))


if __name__ == "__main__":
    port = int(os.environ.get("API_PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
