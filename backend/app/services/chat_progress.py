"""Short independent transactions for resumable reading of streamed replies."""
import hashlib
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.models.chat import ChatConversation, ChatMessage, ChatTurn
from app.models.session import StudySession, Conversation
from app.utils.mutation_lock import lock_user_mutation


def chat_request_hash(body) -> str:
    """Identity of one turn request; stable across retries of the same turn."""
    return hashlib.sha256(json.dumps(body.model_dump(mode="json"), sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


async def save_chat_progress(*, body, user_id: int, content=None, status="streaming", sessionmaker=None,
                             request_hash: str | None = None):
    if not (body.conversation_id or body.study_session_id):
        return None
    if sessionmaker is None:
        from app.database import async_session_maker
        sessionmaker = async_session_maker
    turn_id = str(body.turn_id)
    # The body may carry base64 images; streaming callers hash it once per turn.
    digest = request_hash or chat_request_hash(body)
    async with sessionmaker() as db:
        await lock_user_mutation(db, user_id)
        parents = []
        if body.conversation_id:
            conv = await db.scalar(select(ChatConversation).where(
                ChatConversation.id == body.conversation_id, ChatConversation.user_id == user_id))
            if conv is None:
                raise HTTPException(404, "对话不存在")
            parents.append((ChatMessage, "conversation_id", conv.id))
        if body.study_session_id:
            sess = await db.scalar(select(StudySession).where(
                StudySession.id == body.study_session_id, StudySession.user_id == user_id))
            if sess is None:
                raise HTTPException(404, "学习会话不存在")
            parents.append((Conversation, "session_id", sess.id))
        turn = await db.get(ChatTurn, turn_id)
        existed = turn is not None
        if turn and (turn.user_id != user_id or turn.request_hash != digest):
            raise HTTPException(409, "本次消息标识已用于其他请求")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if not turn:
            turn = ChatTurn(id=turn_id, user_id=user_id, conversation_id=body.conversation_id,
                            study_session_id=body.study_session_id, request_hash=digest,
                            status="streaming", updated_at=now)
            db.add(turn)
            for model, parent, parent_id in parents:
                extra = ({"image_data": json.dumps(body.image_data, ensure_ascii=False) if body.image_data else None}
                         if model is ChatMessage else {"message_type": "chat"})
                db.add(model(**{parent: parent_id}, turn_id=turn_id, role="user", content=body.message,
                             status="completed", **extra))
                db.add(model(**{parent: parent_id}, turn_id=turn_id, role="assistant", content="",
                             status="streaming"))
            await db.flush()
        reply = ""
        for model, parent, parent_id in parents:
            message = await db.scalar(select(model).where(
                getattr(model, parent) == parent_id, model.turn_id == turn_id, model.role == "assistant"))
            # An explicit history edit may remove this turn while generation is active.
            if message is None:
                raise HTTPException(409, "对话历史已改变，生成已停止")
            if content is not None and turn.status == "streaming":
                message.content = content
                message.status = status
            reply = message.content
        if content is not None and turn.status == "streaming":
            turn.status, turn.updated_at = status, now
        # Intermediate checkpoints only touch the reply; the conversation row is
        # updated when the turn starts and when it reaches a terminal status.
        if body.conversation_id and (not existed or (content is not None and status != "streaming")):
            if conv.title == "新对话":
                conv.title = body.message[:50]
            conv.updated_at = now
        await db.commit()
        return {"existed": existed, "content": reply, "status": turn.status}
