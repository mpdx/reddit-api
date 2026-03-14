CREATE TABLE IF NOT EXISTS posts (
    post_id     TEXT PRIMARY KEY,
    subreddit   TEXT NOT NULL,
    timestamp   BIGINT NOT NULL,
    scraped_at  TIMESTAMPTZ NOT NULL,
    data        JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_subreddit_timestamp
    ON posts (subreddit, timestamp DESC);

CREATE TABLE IF NOT EXISTS comments (
    post_id     TEXT PRIMARY KEY REFERENCES posts(post_id) ON DELETE CASCADE,
    data        JSONB NOT NULL
);
