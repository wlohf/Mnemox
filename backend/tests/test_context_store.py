"""ContextStore 接口契约测试（决策 D3）：保底关键词实现必须满足的行为。"""
import tempfile
import unittest
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.material import Material
from app.models.note import Note
from app.models.user import User
from app.services.context_store import (
    L0,
    L1,
    L2,
    KeywordContextStore,
    get_context_store,
    set_context_store,
)


class ContextStoreContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "ctx.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)
        self.store = KeywordContextStore()

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()
        set_context_store(None)

    async def _create_user(self, username: str) -> int:
        async with self.sessionmaker() as session:
            user = User(username=username, email=f"{username}@example.com", hashed_password="hash", is_active=True)
            session.add(user)
            await session.flush()
            user_id = int(user.id)
            await session.commit()
            return user_id

    async def _seed_content(self, user_id: int) -> tuple[int, int]:
        async with self.sessionmaker() as session:
            material = Material(user_id=user_id, title="概率论教材", content="贝叶斯定理是概率论的核心内容之一。" * 20)
            note = Note(user_id=user_id, title="学习心得", content="坚持复习贝叶斯定理，先理解条件概率。")
            session.add_all([material, note])
            await session.flush()
            ids = (int(material.id), int(note.id))
            await session.commit()
            return ids

    async def test_retrieve_finds_matching_material_and_note(self):
        # Arrange
        user_id = await self._create_user("ctx_user")
        await self._seed_content(user_id)

        # Act
        async with self.sessionmaker() as session:
            items = await self.store.retrieve(session, user_id, "贝叶斯", top_k=5)

        # Assert
        source_types = {item.source_type for item in items}
        self.assertIn("material", source_types)
        self.assertIn("note", source_types)
        for item in items:
            self.assertTrue(item.excerpt)
            self.assertGreater(item.score, 0)

    async def test_retrieve_respects_source_type_filter(self):
        user_id = await self._create_user("ctx_filter_user")
        await self._seed_content(user_id)

        async with self.sessionmaker() as session:
            items = await self.store.retrieve(session, user_id, "贝叶斯", source_types=("note",))

        self.assertTrue(items)
        self.assertTrue(all(item.source_type == "note" for item in items))

    async def test_retrieve_is_user_isolated(self):
        owner = await self._create_user("ctx_owner")
        outsider = await self._create_user("ctx_outsider")
        await self._seed_content(owner)

        async with self.sessionmaker() as session:
            items = await self.store.retrieve(session, outsider, "贝叶斯")

        self.assertEqual(items, [])

    async def test_load_tiered_returns_increasing_detail(self):
        # Arrange
        user_id = await self._create_user("ctx_tier_user")
        material_id, _ = await self._seed_content(user_id)

        # Act
        async with self.sessionmaker() as session:
            l0 = await self.store.load_tiered(session, user_id, "material", material_id, L0)
            l1 = await self.store.load_tiered(session, user_id, "material", material_id, L1)
            l2 = await self.store.load_tiered(session, user_id, "material", material_id, L2)

        # Assert: L0 标题最短，L2 全文最长
        self.assertEqual(l0, "概率论教材")
        self.assertLess(len(l0), len(l1))
        self.assertLess(len(l1), len(l2))

    async def test_load_tiered_denies_other_users_content(self):
        owner = await self._create_user("ctx_tier_owner")
        outsider = await self._create_user("ctx_tier_outsider")
        material_id, _ = await self._seed_content(owner)

        async with self.sessionmaker() as session:
            content = await self.store.load_tiered(session, outsider, "material", material_id, L2)

        self.assertEqual(content, "")

    async def test_factory_returns_singleton_and_supports_override(self):
        default_store = get_context_store()
        self.assertIs(get_context_store(), default_store)

        replacement = KeywordContextStore()
        set_context_store(replacement)
        self.assertIs(get_context_store(), replacement)


if __name__ == "__main__":
    unittest.main()
