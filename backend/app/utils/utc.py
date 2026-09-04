"""Canonical UTC conversion helpers.

Mnemox currently stores database timestamps as *naive UTC* for SQLite and
PostgreSQL compatibility.  Naive inputs to this module are therefore always
interpreted as UTC, never as the host machine's local time.  API/log
boundaries should use RFC 3339 strings ending in ``Z``.
"""
from __future__ import annotations

from datetime import date, datetime, timezone


UTC = timezone.utc


def to_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime; naive values are assumed to be UTC."""

    if not isinstance(value, datetime):
        raise TypeError("value must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_db_utc(value: datetime) -> datetime:
    """Return the canonical naive-UTC representation used by SQL columns."""

    return to_utc(value).replace(tzinfo=None)


def utc_now_db() -> datetime:
    """Return the current time in canonical naive-UTC database form."""

    return datetime.now(UTC).replace(tzinfo=None)


def utc_today() -> date:
    """Return the current UTC calendar date without consulting host locale."""

    return datetime.now(UTC).date()


def to_utc_iso(value: datetime) -> str:
    """Serialize a datetime as RFC 3339 UTC with one unambiguous ``Z``."""

    return to_utc(value).isoformat().replace("+00:00", "Z")


def utc_now_iso() -> str:
    """Return the current time as an RFC 3339 UTC string."""

    return to_utc_iso(datetime.now(UTC))
