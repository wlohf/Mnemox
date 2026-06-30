-- Add per-user web search result cache for app-layer search quality optimization.

CREATE TABLE IF NOT EXISTS web_search_cache (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    query_hash VARCHAR(64) NOT NULL,
    normalized_query TEXT NOT NULL,
    mode VARCHAR(40) NOT NULL DEFAULT 'auto',
    provider VARCHAR(40) NOT NULL DEFAULT 'auto',
    quality_key VARCHAR(300) NOT NULL DEFAULT '',
    results_json TEXT NOT NULL DEFAULT '[]',
    summary TEXT,
    source_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS ix_web_search_cache_user_id ON web_search_cache(user_id);
CREATE INDEX IF NOT EXISTS ix_web_search_cache_query_hash ON web_search_cache(query_hash);
CREATE INDEX IF NOT EXISTS ix_web_search_cache_expires_at ON web_search_cache(expires_at);
