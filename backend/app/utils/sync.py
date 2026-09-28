"""Transactional request receipts and optimistic concurrency for offline CRUD."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.models.sync import SyncReceipt
from app.utils.dialect import conflict_insert


@dataclass(frozen=True)
class IdempotencyOperation:
    receipt: SyncReceipt | None
    replay: JSONResponse | None


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": code, "message": message})


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


async def begin_idempotent_operation(
    db: AsyncSession, *, user_id: int, idempotency_key: str | None,
    method: str, path: str, body: Any, if_match: str | None = None,
) -> IdempotencyOperation:
    if not isinstance(idempotency_key, str) or not idempotency_key:
        return IdempotencyOperation(None, None)
    try:
        key = str(uuid.UUID(idempotency_key))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Idempotency-Key 必须是 UUID")
    fingerprint = hashlib.sha256(_canonical_json({
        "method": method.upper(), "path": path, "body": body,
        "if_match": if_match if isinstance(if_match, str) else None,
    }).encode()).hexdigest()
    # A real DML reservation starts SQLite's physical outer transaction. A first
    # SAVEPOINT followed by RELEASE could otherwise commit the receipt alone in
    # sqlite3 legacy transaction mode. Unique insertion serializes all workers;
    # conflict losers wait for the winner's complete domain+receipt transaction.
    result = await db.execute(
        conflict_insert(db, SyncReceipt).values(user_id=user_id, idempotency_key=key,
            method=method.upper(), path=path, fingerprint=fingerprint)
        .on_conflict_do_nothing(index_elements=["user_id", "idempotency_key"])
        .returning(SyncReceipt.id)
    )
    inserted = result.scalar_one_or_none()
    receipt = await db.scalar(select(SyncReceipt).where(
        SyncReceipt.user_id == user_id, SyncReceipt.idempotency_key == key,
    ).execution_options(populate_existing=True))
    if receipt is None:
        raise _conflict("IDEMPOTENCY_KEY_IN_PROGRESS", "请求正在处理中，请使用相同幂等键重试")
    if receipt.fingerprint != fingerprint:
        raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键不能用于不同请求或版本")
    if inserted is not None:
        return IdempotencyOperation(receipt, None)
    if receipt.status_code is None or receipt.response_body is None:
        raise _conflict("IDEMPOTENCY_KEY_IN_PROGRESS", "请求正在处理中，请使用相同幂等键重试")
    return IdempotencyOperation(None, JSONResponse(status_code=receipt.status_code, content=json.loads(receipt.response_body)))


async def complete_idempotent_operation(
    db: AsyncSession, operation: IdempotencyOperation, payload: dict[str, Any], *, status_code: int = 200,
) -> None:
    if operation.receipt is not None:
        operation.receipt.status_code = status_code
        operation.receipt.response_body = _canonical_json(payload)
        await db.flush()


def require_matching_version(current_version: int, if_match: str | None) -> None:
    if not isinstance(if_match, str):
        return  # Backward-compatible direct callers / legacy API clients.
    raw = if_match.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        raw = raw[1:-1]
    try:
        expected = int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="If-Match 必须是带引号的数字版本")
    if expected != int(current_version):
        raise _conflict("SYNC_CONFLICT", "资源已被其他设备修改")


async def flush_sync_mutation(db: AsyncSession) -> None:
    try:
        await db.flush()
    except StaleDataError as exc:
        raise _conflict("SYNC_CONFLICT", "资源已被其他设备修改") from exc
