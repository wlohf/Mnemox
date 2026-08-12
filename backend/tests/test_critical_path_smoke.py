"""关键路径 API 冒烟测试（P0）。

通过 ASGI 内存传输直连真实 FastAPI 应用：真实注册/登录鉴权、真实路由与依赖，
只有数据库被替换为独立 SQLite 测试库。

覆盖链路：注册登录 → 资料上传/创建 → 会话 → 目标与任务 → 笔记 → 复习 → Agent 简报与写入草案。
可靠性要求（需求基线 5.2）：未配置 AI Key 时，以上核心链路不得返回 5xx。
"""
import tempfile
import unittest
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app


class CriticalPathSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "smoke.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

        sessionmaker = self.sessionmaker

        async def _override_get_db():
            async with sessionmaker() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        app.dependency_overrides[get_db] = _override_get_db
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.pop(get_db, None)
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _register_and_login(self, username: str) -> dict:
        register = await self.client.post(
            "/api/auth/register",
            json={"username": username, "email": f"{username}@example.com", "password": "smoke-pass-123"},
        )
        self.assertEqual(register.status_code, 200, register.text)

        login = await self.client.post(
            "/api/auth/login",
            data={"username": username, "password": "smoke-pass-123"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        token = login.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    async def test_full_critical_path_returns_no_server_errors(self):
        headers = await self._register_and_login("smoke_user")

        # 登录态
        me = await self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(me.status_code, 200, me.text)

        # 资料：文本创建 + 文件上传（无 AI/Embedding Key 时必须降级成功而不是 500）
        created_material = await self.client.post(
            "/api/materials/create",
            json={"title": "冒烟资料", "content": "# 第一章\n条件概率是贝叶斯定理的基础。"},
            headers=headers,
        )
        self.assertEqual(created_material.status_code, 200, created_material.text)

        uploaded = await self.client.post(
            "/api/materials/upload",
            data={"title": "冒烟上传"},
            files={"file": ("smoke.md", "# 冒烟上传\n间隔复习基于遗忘曲线。".encode("utf-8"), "text/markdown")},
            headers=headers,
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)

        # 会话：创建 + 详情
        conversation = await self.client.post("/api/conversations", json={}, headers=headers)
        self.assertEqual(conversation.status_code, 200, conversation.text)
        conversation_id = conversation.json().get("id")
        detail = await self.client.get(f"/api/conversations/{conversation_id}", headers=headers)
        self.assertEqual(detail.status_code, 200, detail.text)

        # 目标与任务
        goal = await self.client.post("/api/goals", json={"title": "冒烟目标"}, headers=headers)
        self.assertEqual(goal.status_code, 200, goal.text)
        goal_id = goal.json().get("id")
        task = await self.client.post(
            f"/api/goals/{goal_id}/tasks", json={"title": "冒烟任务"}, headers=headers
        )
        self.assertEqual(task.status_code, 200, task.text)
        daily = await self.client.get(
            "/api/goals/tasks/daily",
            params={"day": __import__("datetime").date.today().isoformat()},
            headers=headers,
        )
        self.assertEqual(daily.status_code, 200, daily.text)

        # 笔记
        note = await self.client.post(
            "/api/notes",
            json={"title": "冒烟笔记", "content": "坚持从来不是想做才做。"},
            headers=headers,
        )
        self.assertEqual(note.status_code, 200, note.text)
        notes = await self.client.get("/api/notes", headers=headers)
        self.assertEqual(notes.status_code, 200, notes.text)

        # 复习
        due = await self.client.get("/api/review/due-count", headers=headers)
        self.assertEqual(due.status_code, 200, due.text)
        review_tasks = await self.client.get("/api/review/tasks", headers=headers)
        self.assertEqual(review_tasks.status_code, 200, review_tasks.text)

        # Agent：简报（规则 Planner，无 AI Key 必须可用）
        brief = await self.client.get("/api/agent/brief", headers=headers)
        self.assertEqual(brief.status_code, 200, brief.text)
        status = await self.client.get("/api/agent/status", headers=headers)
        self.assertEqual(status.status_code, 200, status.text)

        # Agent 写入草案：无 AI Key 时允许降级（4xx），但不允许 5xx
        draft = await self.client.post(
            "/api/agent/write/draft",
            json={"message": "帮我记一条笔记：明天先复习条件概率"},
            headers=headers,
        )
        self.assertLess(draft.status_code, 500, draft.text)

    async def test_protected_route_rejects_anonymous_access(self):
        response = await self.client.get("/api/notes")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
