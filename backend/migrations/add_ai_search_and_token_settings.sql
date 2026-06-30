-- Add Tavily/local web search settings and per-provider AI token budgets.

CREATE TABLE IF NOT EXISTS ai_search_settings (
    user_id INTEGER PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT false,
    default_mode VARCHAR(40) NOT NULL DEFAULT 'auto',
    provider VARCHAR(40) NOT NULL DEFAULT 'auto',
    tavily_api_key TEXT NOT NULL DEFAULT '',
    tavily_search_depth VARCHAR(20) NOT NULL DEFAULT 'advanced',
    tavily_max_results INTEGER NOT NULL DEFAULT 8,
    tavily_chunks_per_source INTEGER NOT NULL DEFAULT 3,
    tavily_include_answer BOOLEAN NOT NULL DEFAULT false,
    tavily_include_raw_content BOOLEAN NOT NULL DEFAULT false,
    timeout_seconds REAL NOT NULL DEFAULT 12.0,
    fallback_enabled BOOLEAN NOT NULL DEFAULT true,
    updated_at TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

ALTER TABLE ai_provider_settings ADD COLUMN IF NOT EXISTS max_context_tokens INTEGER;
ALTER TABLE ai_provider_settings ADD COLUMN IF NOT EXISTS max_output_tokens INTEGER;
