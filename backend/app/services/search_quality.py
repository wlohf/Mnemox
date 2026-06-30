"""Search result quality helpers: canonical URLs, dedupe, scoring, and ranking."""
from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
import re


TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "dclid",
    "gbraid",
    "wbraid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "ref",
    "ref_src",
    "spm",
}

OFFICIAL_DOMAINS = {
    "openai.com",
    "python.org",
    "docs.python.org",
    "react.dev",
    "developer.mozilla.org",
    "microsoft.com",
    "learn.microsoft.com",
    "google.com",
    "cloud.google.com",
    "anthropic.com",
    "docs.anthropic.com",
    "tavily.com",
    "docs.tavily.com",
    "w3.org",
    "ietf.org",
    "nist.gov",
    "who.int",
    "nih.gov",
    "ncbi.nlm.nih.gov",
}

REPUTABLE_NEWS_DOMAINS = {
    "apnews.com",
    "reuters.com",
    "bbc.com",
    "bbc.co.uk",
    "nytimes.com",
    "wsj.com",
    "bloomberg.com",
    "theguardian.com",
    "ft.com",
}

DEVELOPER_COMMUNITY_DOMAINS = {
    "github.com",
    "gitlab.com",
    "stackoverflow.com",
    "stackexchange.com",
    "developer.android.com",
}

LOW_QUALITY_DOMAIN_MARKERS = (
    "download",
    "crack",
    "coupon",
    "casino",
    "apkcombo",
    "softonic",
)

GENERIC_SNIPPET_MARKERS = (
    "click here",
    "enable javascript",
    "all rights reserved",
    "cookie",
)


def source_domain(url: str) -> str:
    """Return a compact display domain for a URL."""
    try:
        host = (urlparse(url).hostname or "").lower().strip(".")
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m.") and host.count(".") >= 2:
        host = host[2:]
    return host


def canonicalize_url(url: str) -> str:
    """Normalize a URL enough for search result dedupe without changing meaning."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return raw.rstrip("/")

    scheme = parsed.scheme.lower()
    host = source_domain(raw)
    if not host:
        return raw.rstrip("/")

    netloc = host
    if parsed.port and not (
        (scheme == "http" and parsed.port == 80)
        or (scheme == "https" and parsed.port == 443)
    ):
        netloc = f"{host}:{parsed.port}"

    path = re.sub(r"/{2,}", "/", parsed.path or "")
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    clean_pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lower_key = key.lower()
        if lower_key in TRACKING_QUERY_KEYS:
            continue
        if any(lower_key.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        clean_pairs.append((key, value))
    clean_pairs.sort(key=lambda item: (item[0].lower(), item[1]))
    query = urlencode(clean_pairs, doseq=True)

    return urlunparse((scheme, netloc, path, "", query, ""))


def score_source_credibility(url: str) -> float:
    """Heuristic 0-1 source credibility score for public web results."""
    domain = source_domain(url)
    if not domain:
        return 0.2
    if any(marker in domain for marker in LOW_QUALITY_DOMAIN_MARKERS):
        return 0.35
    if domain.endswith(".gov") or domain.endswith(".edu") or ".edu." in domain:
        return 0.95
    if domain in OFFICIAL_DOMAINS:
        return 0.95
    if any(domain.endswith(f".{item}") for item in OFFICIAL_DOMAINS):
        return 0.9
    if domain.startswith(("docs.", "developer.", "developers.", "learn.", "support.")):
        return 0.9
    if domain in REPUTABLE_NEWS_DOMAINS or any(domain.endswith(f".{item}") for item in REPUTABLE_NEWS_DOMAINS):
        return 0.82
    if domain in DEVELOPER_COMMUNITY_DOMAINS or any(domain.endswith(f".{item}") for item in DEVELOPER_COMMUNITY_DOMAINS):
        return 0.7
    if domain.endswith((".org", ".ac.uk")):
        return 0.68
    return 0.55


def _normalize_title(title: str) -> str:
    text = " ".join((title or "").lower().split())
    for separator in (" | ", " - ", " – ", " — "):
        if separator in text:
            first = text.split(separator, 1)[0].strip()
            if len(first) >= 8:
                text = first
                break
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    return " ".join(text.split())


def _title_similarity(left: str, right: str) -> float:
    left_key = _normalize_title(left)
    right_key = _normalize_title(right)
    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0
    return SequenceMatcher(None, left_key, right_key).ratio()


def _score_relevance(result: Any, position: int) -> float:
    score = getattr(result, "score", None)
    try:
        if score is not None:
            value = float(score)
            if value > 1.0 and value <= 100.0:
                value = value / 100.0
            return max(0.0, min(1.0, value))
    except (TypeError, ValueError):
        pass
    return max(0.2, 1.0 - (position * 0.08))


def _score_snippet_quality(snippet: str) -> float:
    text = " ".join((snippet or "").split())
    if not text:
        return 0.2
    lower = text.lower()
    if any(marker in lower for marker in GENERIC_SNIPPET_MARKERS):
        return 0.3
    length = len(text)
    if length < 60:
        return 0.45
    if length < 180:
        return 0.72
    if length < 500:
        return 0.9
    return 0.82


def _score_freshness(published_date: str | None) -> float:
    if not published_date:
        return 0.5
    text = str(published_date).strip()
    if not text:
        return 0.5
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return 0.5
    age_days = max(0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).days)
    if age_days <= 30:
        return 1.0
    if age_days <= 365:
        return 0.8
    if age_days <= 1095:
        return 0.65
    return 0.5


def _provider_bonus(provider: str) -> float:
    provider = (provider or "").lower()
    if provider == "tavily":
        return 0.03
    if provider in {"duckduckgo", "provider_hosted"}:
        return 0.01
    return 0.0


def _decorate_result(result: Any, position: int) -> Any:
    canonical_url = canonicalize_url(getattr(result, "url", ""))
    domain = source_domain(canonical_url or getattr(result, "url", ""))
    credibility = score_source_credibility(canonical_url or getattr(result, "url", ""))
    relevance = _score_relevance(result, position)
    snippet_quality = _score_snippet_quality(getattr(result, "snippet", ""))
    freshness = _score_freshness(getattr(result, "published_date", None))
    provider = getattr(result, "source_provider", "local") or "local"
    rank_score = (
        0.36 * relevance
        + 0.40 * credibility
        + 0.14 * snippet_quality
        + 0.10 * freshness
        + _provider_bonus(provider)
    )

    setattr(result, "canonical_url", canonical_url)
    setattr(result, "source_domain", domain)
    setattr(result, "credibility_score", round(credibility, 4))
    setattr(result, "rank_score", round(min(1.0, rank_score), 4))
    providers = getattr(result, "merged_from_providers", None) or []
    if provider and provider not in providers:
        providers = [*providers, provider]
    setattr(result, "merged_from_providers", providers)
    return result


def _quality_tuple(result: Any) -> tuple[float, float, int, float]:
    return (
        float(getattr(result, "rank_score", 0.0) or 0.0),
        float(getattr(result, "credibility_score", 0.0) or 0.0),
        len(getattr(result, "snippet", "") or ""),
        _provider_bonus(getattr(result, "source_provider", "")),
    )


def _merge_into(existing: Any, incoming: Any) -> Any:
    providers = list(getattr(existing, "merged_from_providers", None) or [])
    for provider in getattr(incoming, "merged_from_providers", None) or []:
        if provider not in providers:
            providers.append(provider)

    chosen, other = (incoming, existing) if _quality_tuple(incoming) > _quality_tuple(existing) else (existing, incoming)
    for attr in (
        "title",
        "url",
        "snippet",
        "source_provider",
        "score",
        "published_date",
        "canonical_url",
        "source_domain",
        "credibility_score",
        "rank_score",
    ):
        setattr(existing, attr, getattr(chosen, attr, getattr(existing, attr, None)))

    if not getattr(existing, "snippet", "") and getattr(other, "snippet", ""):
        setattr(existing, "snippet", getattr(other, "snippet"))
    setattr(existing, "merged_from_providers", providers)
    return existing


def enhance_search_results(results: Iterable[Any], *, limit: int | None = None) -> list[Any]:
    """Decorate, dedupe, merge, and rank search results."""
    merged: list[Any] = []
    by_key: dict[str, Any] = {}

    for position, raw in enumerate(results):
        url = str(getattr(raw, "url", "") or "").strip()
        title = str(getattr(raw, "title", "") or "").strip()
        if not title or not url.startswith(("http://", "https://")):
            continue
        result = _decorate_result(raw, position)
        key = getattr(result, "canonical_url", "") or url.rstrip("/")

        target = by_key.get(key)
        if target is None:
            for existing in merged:
                same_domain = getattr(existing, "source_domain", "") == getattr(result, "source_domain", "")
                if same_domain and _title_similarity(getattr(existing, "title", ""), title) >= 0.94:
                    target = existing
                    break

        if target is None:
            by_key[key] = result
            merged.append(result)
            continue

        _merge_into(target, result)
        by_key[key] = target

    merged.sort(key=lambda item: _quality_tuple(item), reverse=True)
    return merged[:limit] if limit is not None else merged
