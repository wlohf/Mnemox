"""Auditable SQL memory-declaration regression coverage."""
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.memory import MemoryDeclaration
from app.models.user import User
from app.services.agent_long_memory_service import upsert_agent_memory
from app.routers.memory import (
    MemoryCreateRequest,
    MemoryUpdateRequest,
    create_memory,
    delete_memory,
    get_memory_declarations,
    update_memory,
)


class MemoryDeclarationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "memory_declarations.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user(self, username: str) -> User:
        async with self.sessionmaker() as session:
            user = User(
                username=username,
                email=f"{username}@example.com",
                hashed_password="hash",
                is_active=True,
            )
            session.add(user)
            await session.flush()
            user_id = int(user.id)
            await session.commit()
        return User(
            id=user_id,
            username=username,
            email=f"{username}@example.com",
            hashed_password="hash",
            is_active=True,
        )

    async def test_manual_create_records_a_confirmed_declaration_with_provenance(self):
        owner = await self._create_user("memory_declaration_owner")
        async with self.sessionmaker() as session:
            created = await create_memory(
                MemoryCreateRequest(
                    memory_key="preferred_style",
                    memory_value="先给出短步骤，再展开说明。",
                    category="style",
                    confidence=0.9,
                ),
                db=session,
                current_user=owner,
            )
            await session.commit()

        async with self.sessionmaker() as session:
            declarations = await get_memory_declarations(
                int(created["id"]),
                db=session,
                current_user=owner,
            )

        self.assertEqual(len(declarations), 1)
        declaration = declarations[0]
        self.assertEqual(declaration["subject"], f"user:{owner.id}")
        self.assertEqual(declaration["predicate"], "style")
        self.assertEqual(declaration["value"], "先给出短步骤，再展开说明。")
        self.assertEqual(declaration["review_status"], "confirmed")
        self.assertEqual(declaration["created_by"], "user")
        self.assertEqual(declaration["source_type"], "manual")
        self.assertIsNotNone(declaration["observed_at"])
        self.assertIsNotNone(declaration["valid_from"])

    async def test_manual_correction_supersedes_prior_declaration_and_locks_memory(self):
        owner = await self._create_user("memory_declaration_correction")
        async with self.sessionmaker() as session:
            created = await create_memory(
                MemoryCreateRequest(
                    memory_key="learning_goal",
                    memory_value="本周完成线性代数第一章。",
                    category="goal",
                ),
                db=session,
                current_user=owner,
            )
            await session.commit()

        async with self.sessionmaker() as session:
            updated = await update_memory(
                int(created["id"]),
                MemoryUpdateRequest(
                    memory_value="本周先完成线性代数向量空间部分。",
                    category="goal",
                    confidence=0.95,
                ),
                db=session,
                current_user=owner,
            )
            await session.commit()

        self.assertEqual(updated["is_locked"], 1)
        async with self.sessionmaker() as session:
            rows = (
                await session.execute(
                    select(MemoryDeclaration)
                    .where(MemoryDeclaration.memory_id == int(created["id"]))
                    .order_by(MemoryDeclaration.id.asc())
                )
            ).scalars().all()

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].value, "本周完成线性代数第一章。")
        self.assertEqual(rows[0].review_status, "superseded")
        self.assertIsNotNone(rows[0].valid_to)
        self.assertEqual(rows[1].value, "本周先完成线性代数向量空间部分。")
        self.assertEqual(rows[1].review_status, "confirmed")
        self.assertEqual(rows[1].supersedes_id, rows[0].id)

    async def test_manual_declaration_cannot_be_overwritten_by_background_memory_write(self):
        owner = await self._create_user("memory_declaration_lock")
        async with self.sessionmaker() as session:
            created = await create_memory(
                MemoryCreateRequest(
                    memory_key="preferred_explanation_style",
                    memory_value="先给出结论和两步行动。",
                    category="style",
                ),
                db=session,
                current_user=owner,
            )
            await session.commit()

        async with self.sessionmaker() as session:
            updated = await upsert_agent_memory(
                session,
                owner.id,
                memory_key="preferred_explanation_style",
                memory_value="改为输出冗长解释。",
                category="style",
                source_type="background_extract",
                source_id="test-background-write",
            )
            await session.commit()

        self.assertEqual(updated.id, int(created["id"]))
        self.assertEqual(updated.memory_value, "先给出结论和两步行动。")
        self.assertEqual(updated.is_locked, 1)

    async def test_delete_removes_only_the_owners_memory_declarations(self):
        owner = await self._create_user("memory_declaration_delete_owner")
        other = await self._create_user("memory_declaration_delete_other")
        async with self.sessionmaker() as session:
            owned = await create_memory(
                MemoryCreateRequest(memory_key="owned", memory_value="owner memory"),
                db=session,
                current_user=owner,
            )
            other_memory = await create_memory(
                MemoryCreateRequest(memory_key="other", memory_value="other memory"),
                db=session,
                current_user=other,
            )
            await session.commit()

        async with self.sessionmaker() as session:
            await delete_memory(int(owned["id"]), db=session, current_user=owner)
            await session.commit()

        async with self.sessionmaker() as session:
            rows = (
                await session.execute(select(MemoryDeclaration).order_by(MemoryDeclaration.id))
            ).scalars().all()

        self.assertEqual([(row.user_id, row.memory_id) for row in rows], [(other.id, int(other_memory["id"]))])


if __name__ == "__main__":
    unittest.main()
