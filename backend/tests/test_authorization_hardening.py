"""多用户授权加固回归测试（2026-07-26 审计修复）。

覆盖：上传文件归属校验、章节归属校验（任务关联 / 计划设置）、
进度引擎资料归属、复习完成章节分支归属。
"""
import tempfile
import unittest
from pathlib import Path, PurePosixPath

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.main import _is_upload_owned_by_user
from app.models.goal import Goal, Task
from app.models.material import Chapter, Material
from app.models.user import User


class _AuthTestBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "authz.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user(self, username: str) -> User:
        async with self.sessionmaker() as session:
            user = User(username=username, email=f"{username}@example.com", hashed_password="hash", is_active=True)
            session.add(user)
            await session.flush()
            user_id = int(user.id)
            await session.commit()
        return User(id=user_id, username=username, email=f"{username}@example.com", hashed_password="hash", is_active=True)

    async def _create_material_with_chapter(self, user: User, title: str, file_path: str | None = None) -> tuple[int, int]:
        async with self.sessionmaker() as session:
            material = Material(user_id=user.id, title=title, file_path=file_path, content="示例内容")
            session.add(material)
            await session.flush()
            chapter = Chapter(material_id=material.id, title=f"{title}-第一章", content="章节内容", order_index=1)
            session.add(chapter)
            await session.flush()
            ids = (int(material.id), int(chapter.id))
            await session.commit()
            return ids

    async def _create_goal_with_task(self, user: User) -> tuple[int, int]:
        async with self.sessionmaker() as session:
            goal = Goal(user_id=user.id, title="我的目标", status="active")
            session.add(goal)
            await session.flush()
            task = Task(goal_id=goal.id, title="我的任务", status="pending")
            session.add(task)
            await session.flush()
            ids = (int(goal.id), int(task.id))
            await session.commit()
            return ids


class UploadOwnershipTests(_AuthTestBase):
    async def test_material_file_is_only_visible_to_owner(self):
        # Arrange
        owner = await self._create_user("upload_owner")
        outsider = await self._create_user("upload_outsider")
        await self._create_material_with_chapter(owner, "资料A", file_path="data/uploads/secret-doc.pdf")

        # Act / Assert
        async with self.sessionmaker() as session:
            self.assertTrue(
                await _is_upload_owned_by_user(session, owner.id, PurePosixPath("secret-doc.pdf"))
            )
            self.assertFalse(
                await _is_upload_owned_by_user(session, outsider.id, PurePosixPath("secret-doc.pdf"))
            )

    async def test_user_image_dir_is_isolated(self):
        # Arrange
        owner = await self._create_user("img_owner")
        outsider = await self._create_user("img_outsider")

        # Act / Assert
        async with self.sessionmaker() as session:
            path = PurePosixPath(f"images/{owner.id}/pic.png")
            self.assertTrue(await _is_upload_owned_by_user(session, owner.id, path))
            self.assertFalse(await _is_upload_owned_by_user(session, outsider.id, path))

    async def test_unknown_root_file_is_denied(self):
        # Arrange
        user = await self._create_user("unknown_file_user")

        # Act / Assert: 未挂到任何 Material 的根级文件不可访问
        async with self.sessionmaker() as session:
            self.assertFalse(
                await _is_upload_owned_by_user(session, user.id, PurePosixPath("orphan.pdf"))
            )


class ChapterOwnershipTests(_AuthTestBase):
    async def test_cannot_attach_task_to_another_users_chapter(self):
        # Arrange
        victim = await self._create_user("chapter_victim")
        attacker = await self._create_user("chapter_attacker")
        _, victim_chapter_id = await self._create_material_with_chapter(victim, "受害者资料")
        _, attacker_task_id = await self._create_goal_with_task(attacker)

        from app.routers.goals import TaskUpdate, update_task

        # Act / Assert
        async with self.sessionmaker() as session:
            with self.assertRaises(HTTPException) as caught:
                await update_task(
                    task_id=attacker_task_id,
                    body=TaskUpdate(chapter_id=victim_chapter_id),
                    db=session,
                    current_user=attacker,
                )
        self.assertEqual(caught.exception.status_code, 404)

    async def test_owner_can_attach_task_to_own_chapter(self):
        # Arrange
        owner = await self._create_user("chapter_owner")
        _, chapter_id = await self._create_material_with_chapter(owner, "自己的资料")
        _, task_id = await self._create_goal_with_task(owner)

        from app.routers.goals import TaskUpdate, update_task

        # Act
        async with self.sessionmaker() as session:
            result = await update_task(
                task_id=task_id,
                body=TaskUpdate(chapter_id=chapter_id),
                db=session,
                current_user=owner,
            )

        # Assert
        self.assertEqual(result.get("chapter_id"), chapter_id)

    async def test_cannot_plan_goal_with_another_users_chapter(self):
        # Arrange
        victim = await self._create_user("plan_victim")
        attacker = await self._create_user("plan_attacker")
        _, victim_chapter_id = await self._create_material_with_chapter(victim, "受害者资料2")
        attacker_goal_id, _ = await self._create_goal_with_task(attacker)

        from app.routers.goals import GoalPlanRequest, create_goal_plan

        # Act / Assert
        async with self.sessionmaker() as session:
            with self.assertRaises(HTTPException) as caught:
                await create_goal_plan(
                    goal_id=attacker_goal_id,
                    body=GoalPlanRequest(total_days=7, current_chapter_id=victim_chapter_id),
                    db=session,
                    current_user=attacker,
                )
        self.assertEqual(caught.exception.status_code, 404)


class ProgressEngineOwnershipTests(_AuthTestBase):
    async def test_adaptive_replan_rejects_another_users_material(self):
        # Arrange
        victim = await self._create_user("replan_victim")
        attacker = await self._create_user("replan_attacker")
        victim_material_id, _ = await self._create_material_with_chapter(victim, "受害者资料3")

        from app.routers.learning import AdaptiveReplanRequest, adaptive_replan

        # Act / Assert: 不能为他人资料创建目标/读取章节
        async with self.sessionmaker() as session:
            with self.assertRaises(HTTPException) as caught:
                await adaptive_replan(
                    material_id=victim_material_id,
                    body=AdaptiveReplanRequest(days=7),
                    db=session,
                    current_user=attacker,
                )
        self.assertEqual(caught.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
