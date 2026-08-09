import asyncio
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.concept import Concept, ConceptLink
from app.models.note import Note
from app.models.user import User
from app.routers.notes import (
    NoteUpdate,
    _get_note_for_write,
    _note_write_scope,
    _note_write_query,
    delete_note,
    update_note,
)
from app.services.association_service import attach_note_to_concepts


class NoteConceptLinkSyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "note_concepts.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def test_update_replaces_stale_links_and_delete_removes_all_note_links(self):
        async with self.sessions() as session:
            user = User(username="notes-owner", email="notes-owner@example.com", hashed_password="hash", is_active=True)
            session.add(user)
            await session.flush()
            old_concept = Concept(
                user_id=int(user.id), name="线性代数", name_normalized="线性代数", mastery=0, source="test"
            )
            new_concept = Concept(
                user_id=int(user.id), name="概率论", name_normalized="概率论", mastery=0, source="test"
            )
            note = Note(user_id=int(user.id), title="线性代数笔记", content="线性代数的内容")
            session.add_all([old_concept, new_concept, note])
            await session.flush()
            await attach_note_to_concepts(session, int(user.id), note)
            user_id = int(user.id)
            note_id = int(note.id)
            current_user = User(
                id=user_id,
                username="notes-owner",
                email="notes-owner@example.com",
                hashed_password="hash",
                is_active=True,
            )
            await session.commit()

        async with self.sessions() as session:
            await update_note(
                note_id,
                NoteUpdate(title="概率论笔记", content="概率论的内容"),
                db=session,
                current_user=current_user,
            )
            links = (
                await session.execute(
                    select(ConceptLink).where(
                        ConceptLink.user_id == user_id,
                        ConceptLink.target_type == "note",
                        ConceptLink.target_id == note_id,
                    )
                )
            ).scalars().all()
            self.assertEqual([link.concept_id for link in links], [int(new_concept.id)])
            await session.commit()

        async with self.sessions() as session:
            await delete_note(note_id, db=session, current_user=current_user)
            await session.commit()

        async with self.sessions() as session:
            remaining_links = (
                await session.execute(
                    select(ConceptLink).where(
                        ConceptLink.user_id == user_id,
                        ConceptLink.target_type == "note",
                        ConceptLink.target_id == note_id,
                    )
                )
            ).scalars().all()
        self.assertEqual(remaining_links, [])

    def test_note_write_query_locks_the_owned_note_on_postgresql(self):
        statement = _note_write_query(note_id=42, user_id=7)

        compiled = str(statement.compile(dialect=postgresql.dialect()))

        self.assertIn("FOR UPDATE", compiled)

    async def test_sqlite_note_write_lookup_waits_for_the_current_transaction(self):
        async with self.sessions() as setup_session:
            user = User(username="note-lock-owner", email="note-lock-owner@example.com", hashed_password="hash", is_active=True)
            setup_session.add(user)
            await setup_session.flush()
            note = Note(user_id=int(user.id), title="锁定测试", content="并发写入")
            setup_session.add(note)
            await setup_session.commit()
            user_id = int(user.id)
            note_id = int(note.id)

        first_session = self.sessions()
        second_session = self.sessions()
        try:
            async with _note_write_scope(first_session, note_id, user_id):
                first_note = await _get_note_for_write(first_session, note_id, user_id)
                self.assertIsNotNone(first_note)

                second_started = asyncio.Event()

                async def load_after_first_commit():
                    second_started.set()
                    async with _note_write_scope(second_session, note_id, user_id):
                        return await _get_note_for_write(second_session, note_id, user_id)

                second_task = asyncio.create_task(load_after_first_commit())
                await second_started.wait()
                await asyncio.sleep(0.1)
                self.assertFalse(second_task.done())

                await first_session.commit()

            second_note = await asyncio.wait_for(second_task, timeout=2)
            self.assertEqual(int(second_note.id), note_id)
        finally:
            if first_session.in_transaction():
                await first_session.rollback()
            if second_session.in_transaction():
                await second_session.rollback()
            await first_session.close()
            await second_session.close()


if __name__ == "__main__":
    unittest.main()
