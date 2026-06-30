import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.user import User
from app.services.search_cache_service import search_web_with_cache
from app.services.web_search import SearchProviderSettings, WebSearchResult


class SearchCacheServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "search_cache.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user(self, suffix: str = "a") -> int:
        async with self.sessionmaker() as session:
            user = User(
                username=f"search-user-{suffix}",
                email=f"search-{suffix}@example.com",
                hashed_password="hash",
                is_active=True,
            )
            session.add(user)
            await session.flush()
            user_id = int(user.id)
            await session.commit()
            return user_id

    async def test_search_web_with_cache_reuses_cached_results(self):
        user_id = await self._create_user()
        search_func = AsyncMock(
            return_value=[
                WebSearchResult(
                    title="Official Python documentation",
                    url="https://docs.python.org/3/?utm_source=test",
                    snippet="Official docs.",
                    source_provider="duckduckgo",
                )
            ]
        )
        settings = SearchProviderSettings(enabled=True, provider="local_fallback", fallback_enabled=True)

        async with self.sessionmaker() as session:
            first = await search_web_with_cache(
                "Python docs",
                db=session,
                user_id=user_id,
                limit=5,
                settings=settings,
                mode="local_fallback",
                search_func=search_func,
            )
            await session.commit()

        async with self.sessionmaker() as session:
            second = await search_web_with_cache(
                "python   docs",
                db=session,
                user_id=user_id,
                limit=5,
                settings=settings,
                mode="local_fallback",
                search_func=search_func,
            )

        self.assertEqual(search_func.await_count, 1)
        self.assertEqual(first[0].canonical_url, "https://docs.python.org/3")
        self.assertEqual(second[0].canonical_url, "https://docs.python.org/3")
        self.assertEqual(second[0].source_domain, "docs.python.org")

    async def test_search_web_with_cache_is_user_scoped(self):
        user_a = await self._create_user("a")
        user_b = await self._create_user("b")
        search_func = AsyncMock(
            return_value=[
                WebSearchResult(
                    title="Result",
                    url="https://example.com/a",
                    snippet="summary",
                    source_provider="bing",
                )
            ]
        )

        async with self.sessionmaker() as session:
            await search_web_with_cache("same query", db=session, user_id=user_a, search_func=search_func)
            await session.commit()

        async with self.sessionmaker() as session:
            await search_web_with_cache("same query", db=session, user_id=user_b, search_func=search_func)

        self.assertEqual(search_func.await_count, 2)


if __name__ == "__main__":
    unittest.main()
