"""The dialect adapter resolves sessions, connections, and engines alike."""
import unittest
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.user_profile import UserProfile
from app.utils.dialect import conflict_insert, dialect_name, is_postgresql


class DialectAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_engine_connection_and_session_report_the_same_dialect(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.addAsyncCleanup(engine.dispose)
        async with engine.connect() as connection, AsyncSession(bind=engine) as session:
            self.assertEqual(
                [dialect_name(engine), dialect_name(connection), dialect_name(session)],
                ["sqlite", "sqlite", "sqlite"],
            )

    def test_postgresql_engine_is_detected_without_a_session(self):
        # operation_lock passes the session's engine directly; a miss here
        # silently skips the cross-process advisory lock.
        engine = create_async_engine("postgresql+asyncpg://user:pass@127.0.0.1/db")
        self.assertTrue(is_postgresql(engine))
        self.assertTrue(is_postgresql(SimpleNamespace(bind=engine)))
        self.assertFalse(is_postgresql(SimpleNamespace(bind=None)))

    def test_conflict_insert_rejects_unsupported_databases(self):
        unsupported = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="mysql")))
        with self.assertRaisesRegex(RuntimeError, "SQLite or PostgreSQL"):
            conflict_insert(unsupported, UserProfile)


if __name__ == "__main__":
    unittest.main()
