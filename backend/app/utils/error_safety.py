"""Bounded, secret-safe error text for logs, APIs, and persisted diagnostics."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any


REDACTED = "[REDACTED]"
DEFAULT_ERROR_CHARS = 500
_SENSITIVE_NAME = (
    r"api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|"
    r"client[_-]?secret|password|passwd|secret|token"
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?-----END [^-\r\n]*PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_URI_CREDENTIALS = re.compile(
    r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<credentials>[^/@\s]+)@",
    re.IGNORECASE,
)
_QUOTED_AUTHORIZATION = re.compile(
    r"(?i)(?P<prefix>[\"']?(?:authorization|proxy-authorization)[\"']?\s*[:=]\s*)"
    r"(?P<quote>[\"'])(?P<value>.*?)(?P=quote)"
)
_AUTHORIZATION = re.compile(
    r"(?i)(?P<name>authorization|proxy-authorization)(?P<separator>\s*[:=]\s*)"
    r"(?P<value>(?:bearer|basic)\s+[^\s,;]+|[^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{6,}")
_QUOTED_ASSIGNMENT = re.compile(
    rf"(?i)(?P<prefix>[\"']?(?:{_SENSITIVE_NAME})[\"']?\s*[:=]\s*)"
    r"(?P<quote>[\"'])(?P<value>.*?)(?P=quote)"
)
_UNQUOTED_ASSIGNMENT = re.compile(
    rf"(?i)(?P<prefix>\b(?:{_SENSITIVE_NAME})\b\s*[:=]\s*)"
    r"(?P<value>\[REDACTED\]|[^\s,;&}}\]]+)"
)
_KNOWN_TOKEN = re.compile(
    r"(?i)\b(?:sk-(?:proj-)?[a-z0-9_-]{8,}|"
    r"gh[pousr]_[a-z0-9]{16,}|xox[baprs]-[a-z0-9-]{12,}|"
    r"AIza[a-z0-9_-]{20,}|AKIA[0-9A-Z]{16})\b"
)
_JWT = re.compile(r"\beyJ[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}\b")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+")
_WHITESPACE = re.compile(r"\s+")
_INVALID_ERROR_CODE = re.compile(r"[^a-z0-9._-]+")


@dataclass(frozen=True)
class SafeErrorDiagnostic:
    """Stable, non-sensitive failure metadata safe for persistence and APIs."""

    code: str
    summary: str
    fingerprint: str

    def as_dict(self) -> dict[str, str]:
        return {
            "error_code": self.code,
            "error_summary": self.summary,
            "error_fingerprint": self.fingerprint,
        }


def redact_sensitive_text(
    value: Any,
    *,
    max_chars: int = DEFAULT_ERROR_CHARS,
    fallback: str = "operation_failed",
) -> str:
    """Return one bounded line with common credentials removed.

    Redaction runs before truncation so a credential beginning near the output
    boundary cannot be partially persisted. The function is intentionally
    suitable for arbitrary exception and upstream-response text.
    """

    limit = max(1, int(max_chars))
    text = str(value or "")
    if not text.strip():
        return str(fallback or "operation_failed")[:limit]

    # Error bodies can be unexpectedly large. Only the prefix can reach the
    # result; retain enough look-ahead to redact a long value that starts there.
    text = text[: max(16_384, limit * 16)]
    text = _PRIVATE_KEY.sub("[REDACTED PRIVATE KEY]", text)
    text = _URI_CREDENTIALS.sub(lambda match: f"{match.group('scheme')}{REDACTED}@", text)
    text = _QUOTED_AUTHORIZATION.sub(
        lambda match: f"{match.group('prefix')}{match.group('quote')}{REDACTED}{match.group('quote')}",
        text,
    )
    text = _AUTHORIZATION.sub(
        lambda match: f"{match.group('name')}{match.group('separator')}{REDACTED}",
        text,
    )
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    text = _QUOTED_ASSIGNMENT.sub(
        lambda match: f"{match.group('prefix')}{match.group('quote')}{REDACTED}{match.group('quote')}",
        text,
    )
    text = _UNQUOTED_ASSIGNMENT.sub(
        lambda match: f"{match.group('prefix')}{REDACTED}",
        text,
    )
    text = _KNOWN_TOKEN.sub(REDACTED, text)
    text = _JWT.sub(REDACTED, text)
    text = _CONTROL.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return (text or str(fallback or "operation_failed"))[:limit]


def safe_exception_summary(
    exc: BaseException,
    *,
    max_chars: int = DEFAULT_ERROR_CHARS,
    fallback: str = "operation_failed",
) -> str:
    """Return a diagnostic exception class plus a redacted, bounded message."""

    kind = type(exc).__name__ or "Exception"
    message_budget = max(1, int(max_chars) - len(kind) - 2)
    message = redact_sensitive_text(str(exc), max_chars=message_budget, fallback="")
    summary = f"{kind}: {message}" if message else kind
    return summary[: max(1, int(max_chars))] or fallback


def normalize_error_code(value: Any, *, fallback: str = "operation_failed") -> str:
    """Normalize a caller-owned category without deriving it from secret text."""

    normalized = _INVALID_ERROR_CODE.sub("_", str(value or "").strip().casefold())
    normalized = re.sub(r"[_.-]{2,}", "_", normalized).strip("_.-")[:80]
    if normalized:
        return normalized
    clean_fallback = _INVALID_ERROR_CODE.sub(
        "_", str(fallback or "operation_failed").strip().casefold()
    ).strip("_.-")[:80]
    return clean_fallback or "operation_failed"


def safe_error_diagnostic(
    value: Any,
    *,
    code: str,
    max_chars: int = DEFAULT_ERROR_CHARS,
    fallback: str = "operation_failed",
) -> SafeErrorDiagnostic:
    """Build a stable diagnostic from text only after redaction and bounding."""

    safe_code = normalize_error_code(code, fallback=fallback)
    summary = redact_sensitive_text(value, max_chars=max_chars, fallback=fallback)
    fingerprint = hashlib.sha256(
        f"{safe_code}\n{summary}".encode("utf-8")
    ).hexdigest()[:16]
    return SafeErrorDiagnostic(safe_code, summary, fingerprint)


def safe_exception_diagnostic(
    exc: BaseException,
    *,
    code: str,
    max_chars: int = DEFAULT_ERROR_CHARS,
    fallback: str = "operation_failed",
) -> SafeErrorDiagnostic:
    """Build structured metadata from an exception without retaining raw text."""

    summary = safe_exception_summary(exc, max_chars=max_chars, fallback=fallback)
    return safe_error_diagnostic(
        summary,
        code=code,
        max_chars=max_chars,
        fallback=fallback,
    )


def error_fingerprint(exc: BaseException) -> str:
    """Return a stable correlation token derived only from sanitized content."""

    summary = safe_exception_summary(exc, max_chars=1000)
    return hashlib.sha256(summary.encode("utf-8")).hexdigest()[:16]
