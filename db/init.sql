CREATE TABLE IF NOT EXISTS posts (
    post_id     TEXT PRIMARY KEY,
    subreddit   TEXT NOT NULL,
    timestamp   BIGINT NOT NULL,
    scraped_at  TIMESTAMPTZ NOT NULL,
    data        JSONB NOT NULL,
    watch_until TIMESTAMPTZ DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_subreddit_timestamp
    ON posts (subreddit, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_posts_watch_until
    ON posts (watch_until)
    WHERE watch_until IS NOT NULL;

CREATE TABLE IF NOT EXISTS comments (
    post_id     TEXT PRIMARY KEY REFERENCES posts(post_id) ON DELETE CASCADE,
    data        JSONB NOT NULL
);
