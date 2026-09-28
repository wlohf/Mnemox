"""A review attempt, its state changes and its response commit together."""
import hashlib
import json
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from app.models.sync import SyncReceipt
from app.utils.sync import begin_idempotent_operation, complete_idempotent_operation, _canonical_json
from app.utils.mutation_lock import lock_user_mutation


async def replay_review_attempt(db, user_id, path, body):
    receipt = await db.scalar(select(SyncReceipt).where(
        SyncReceipt.user_id == user_id, SyncReceipt.idempotency_key == str(body.attempt_id)))
    if receipt is None:
        return None
    fingerprint = hashlib.sha256(_canonical_json({"method": "POST", "path": path,
        "body": body.model_dump(mode="json"), "if_match": None}).encode()).hexdigest()
    if receipt.fingerprint != fingerprint:
        raise HTTPException(status_code=409, detail="同一次复习不能提交不同答案或评分")
    if receipt.response_body is not None:
        return JSONResponse(status_code=receipt.status_code, content=json.loads(receipt.response_body))
    return None


async def reserve_review_attempt(db, user_id, path, body):
    operation = await begin_idempotent_operation(db, user_id=user_id, idempotency_key=str(body.attempt_id),
        method="POST", path=path, body=body.model_dump(mode="json"))
    if operation.replay is None:
        await lock_user_mutation(db, user_id)
    return operation


async def finish_review_attempt(db, operation, response):
    await complete_idempotent_operation(db, operation, response)
    return response
