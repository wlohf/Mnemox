# Tavily Search And AI Token Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent Tavily web search settings with DuckDuckGo/Bing fallback, plus provider-level context and output token settings.

**Architecture:** Keep search provider configuration separate from model provider configuration. Chat uses a unified app-search service that prefers Tavily when enabled, then falls back to DuckDuckGo/Bing when configured paths fail. AI provider settings gain context/output token budgets and provider implementations use the output limit where supported.

**Tech Stack:** FastAPI, SQLAlchemy, httpx, React, Ant Design, Vitest/Pytest.

---

### Task 1: Backend tests for search settings and Tavily fallback

**Files:**
- Create: `backend/tests/test_search_settings.py`
- Modify: `backend/tests/test_web_search_service.py`

- [x] Add failing tests for default search settings, Tavily-first search, and Tavily failure falling back to local search.
- [x] Run targeted pytest and confirm failures are due to missing settings/provider support.

### Task 2: Backend search settings and provider implementation

**Files:**
- Create: `backend/app/models/search_settings.py`
- Create: `backend/migrations/add_ai_search_and_token_settings.sql`
- Create: `backend/app/services/search_settings_service.py`
- Modify: `backend/app/services/web_search.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/routers/ai_settings.py`

- [x] Add encrypted persistent search settings API.
- [x] Add Tavily search support.
- [x] Preserve DuckDuckGo/Bing as final fallback.
- [x] Add search settings test endpoint.
- [x] Run targeted pytest.

### Task 3: AI token budget backend

**Files:**
- Modify: `backend/app/models/ai_settings.py`
- Modify: `backend/app/routers/ai_settings.py`
- Modify: `backend/app/ai/base.py`
- Modify: `backend/app/ai/openai_provider.py`
- Modify: `backend/app/ai/claude_provider.py`
- Modify: `backend/app/ai/gemini_provider.py`
- Modify: `backend/app/ai/factory.py`

- [x] Add max_context_tokens and max_output_tokens to provider settings.
- [x] Pass output token limits to supported providers.
- [x] Apply context budget trimming before provider requests.
- [x] Run provider tests.

### Task 4: Chat integration

**Files:**
- Modify: `backend/app/routers/chat.py`
- Modify: `backend/tests/test_chat_stream_session.py`

- [x] Use persistent search settings for app-level web search.
- [x] Make auto mode prefer Tavily when configured before hosted search.
- [x] Emit provider info in web search SSE result payload.
- [x] Run chat tests.

### Task 5: Frontend settings UI

**Files:**
- Modify: `frontend/src/services/aiSettingsApi.ts`
- Modify: `frontend/src/components/AISettingsDrawer.tsx`

- [x] Add search settings API client and types.
- [x] Add Web Search settings section with Tavily key, quality preset, fallback toggle, and test button.
- [x] Add provider token budget fields.
- [x] Run frontend tests or type/build check if available.

### Task 6: Verification

- [x] Run backend targeted tests.
- [x] Run frontend targeted tests/build.
- [x] Summarize remaining risks and any skipped checks.
