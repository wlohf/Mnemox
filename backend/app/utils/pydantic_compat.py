"""Small compatibility helpers for supported Pydantic model generations."""
from __future__ import annotations

from typing import Any


def provided_model_fields(model: Any) -> set[str]:
    """Return explicitly supplied fields without touching deprecated v2 APIs."""

    fields = getattr(model, "model_fields_set", None)
    if fields is not None:
        return set(fields)
    # Pydantic v1 has no ``model_fields_set``. This branch is intentionally
    # unreachable on v2 so its deprecated compatibility property is not read.
    return set(getattr(model, "__fields_set__", set()))

