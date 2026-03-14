# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A self-hosted Reddit scraper and REST API running entirely in Docker Compose. Scrapes configured subreddits hourly and exposes posts and comments via a REST API.

## Architecture

Three Python services communicate through RabbitMQ and PostgreSQL:

```
APScheduler (hourly) → Scraper (Playwright) → RabbitMQ → Loader → PostgreSQL → API (FastAPI)
```

- **`scraper/`** — Playwright scrapes old.reddit.com. `main.py` runs APScheduler (fires immediately + every hour). `scraper.py` contains all scraping logic. `config_loader.py` reads `config/subreddits.yaml` and hot-reloads it via watchdog. `publisher.py` maintains a lazy singleton RabbitMQ connection and publishes each scraped post as JSON.
- **`loader/`** — Blocking pika consumer. `main.py` connects to RabbitMQ and PostgreSQL, then calls `consumer.handle_message` per message. `db.py` upserts posts (with `timestamp_millis` as the sort key) and replaces the full comment tree per post. Failed messages are nacked to a dead-letter queue.
- **`api/`** — FastAPI app. `main.py` owns all response transformation: `format_post()` and `format_comment()` clean up raw stored JSON (strip prefixes, rename fields). `db.py` uses asyncpg with cursor-based pagination via timestamp resolution.

## Key Data Flow Detail

The scraper stores raw Reddit data including Reddit's `t3_`/`t1_` ID prefixes and field names like `timestamp_millis`, `text`, `points`, `dataURL`. The API layer (`api/main.py`) transforms all of this at response time — the database is never updated to match the API shape.

The loader's `db.py:upsert_post` uses `post["timestamp_millis"]` as the `timestamp` column (used for pagination ordering) and strips `comments` out of the post blob before storing.

## Running Locally

```bash
docker compose up -d          # start all services
docker compose logs -f scraper # watch scraper
docker compose logs -f api     # watch API
```

The API is available at `http://localhost:8080`.

To rebuild after code changes:
```bash
docker compose up -d --build api
docker compose up -d --build scraper
```

## Subreddit Configuration

Edit `config/subreddits.yaml` — the scraper hot-reloads it without restart:

```yaml
subreddits:
  - programming
lookback_hours: 72
```

The `SUBREDDITS` env var (comma-separated) overrides the YAML entirely.

## Database

PostgreSQL. Schema in `db/init.sql`. Two tables:
- `posts` — PK `post_id`, indexed on `(subreddit, timestamp DESC)`. `data` is JSONB containing the raw scraper output minus `comments`.
- `comments` — PK `post_id` (FK to posts). `data` is JSONB containing the full recursive comment tree as scraped.

Pagination in `api/db.py` resolves cursor IDs to timestamps first, then queries by timestamp range.

## API Response Transformation

All field renaming and cleanup happens in `api/main.py`, not in the scraper or loader:
- IDs: `t3_xxx` → `xxx`, `t1_xxx` → `xxx`, `r/sub` → `sub`
- Fields: `text`→`body`, `points`→`score`, `timestamp`→`createdAt`, `dataURL`→`linkUrl`, `dataType`→`postType`
- Removed: `timestamp_millis`, `isCollapsed`
- Added: `permalink`
- Comments: handles both `children` (Python scraper) and `replies` (old JS scraper) as the nested comment key
