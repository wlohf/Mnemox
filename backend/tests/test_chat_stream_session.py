import unittest
from unittest.mock import AsyncMock, patch

from app.models.user import User
from app.routers.chat import ChatRequest, chat_send


class _FakeScalarResult:
    def scalar_one_or_none(self):
        return object()


class _FakeDb:
    def __init__(self):
        self.rollback = AsyncMock()

    async def execute(self, *_args, **_kwargs):
        return _FakeScalarResult()


class _FakeProvider:
    async def chat_stream(self, **_kwargs):
        yield "ok"


class ChatStreamSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_send_releases_request_db_session_before_streaming(self):
        db = _FakeDb()
        current_user = User(id=1, username="u", email="u@example.com", hashed_password="x")
        body = ChatRequest(message="hello", conversation_id=1, history=[])

        with (
            patch("app.routers.chat._resolve_materials_and_build_prompt", AsyncMock(return_value=("", [], []))),
            patch("app.routers.chat.get_relevant_memories", AsyncMock(return_value=[])),
            patch("app.routers.chat.AIProviderFactory.create_provider", AsyncMock(return_value=_FakeProvider())),
        ):
            response = await chat_send(body, db=db, current_user=current_user)

        self.assertEqual(response.media_type, "text/event-stream")
        db.rollback.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
