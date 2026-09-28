import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
import app.models
from app.ai.factory import AIProviderFactory
from app.models.ai_settings import AIProviderSetting
from app.models.user import User
from app.routers.ai_settings import (
    ProviderConnectionRequest, ProviderUpdate, ModelSearchRequest,
    seed_user_providers, test_provider as probe_provider, search_provider_models,
    update_provider,
)
from app.utils.secret_crypto import encrypt_secret
from app.utils.provider_credentials import user_provider_key


class ProviderCredentialBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = User(username="owner", email="owner@example.test", hashed_password="test")
        self.db.add(self.user)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def test_registration_never_copies_server_credentials(self):
        with patch("app.routers.ai_settings.settings.OPENAI_API_KEY", "server-secret"):
            await seed_user_providers(self.db, self.user.id)
        rows = (await self.db.scalars(select(AIProviderSetting))).all()
        self.assertTrue(rows)
        self.assertTrue(all(not row.api_key and row.credential_source == "user" for row in rows))

    async def test_legacy_key_cannot_be_sent_to_an_overridden_endpoint(self):
        row = AIProviderSetting(user_id=self.user.id, provider_name="openai", display_name="OpenAI",
            api_key=encrypt_secret("historical-server-secret"), base_url="https://api.openai.com/v1", model="test")
        self.db.add(row)
        await self.db.commit()
        with patch.object(AIProviderFactory, "create_provider_from_settings") as factory:
            result = await probe_provider("openai", ProviderConnectionRequest(base_url="https://receiver.example/v1"), self.db, self.user)
            self.assertFalse(result.success)
            factory.assert_not_called()
            with self.assertRaisesRegex(ValueError, "重新填写"):
                await AIProviderFactory.create_provider(db=self.db, user_id=self.user.id, provider_name="openai")
            factory.assert_not_called()
        with self.assertRaises(Exception) as error:
            await search_provider_models("openai", ModelSearchRequest(base_url="https://receiver.example/v1"), self.db, self.user)
        self.assertEqual(error.exception.status_code, 400)
        # Editing a URL is not proof of key ownership.
        with patch("app.routers.ai_settings.validate_ai_provider_url", new=AsyncMock(return_value="https://receiver.example/v1")):
            await update_provider("openai", ProviderUpdate(base_url="https://receiver.example/v1"), self.db, self.user)
        self.assertEqual(user_provider_key(row), "")
        await update_provider("openai", ProviderUpdate(api_key="my-own-key"), self.db, self.user)
        self.assertEqual(user_provider_key(row), "my-own-key")

    async def test_missing_user_provider_does_not_fall_back_to_server(self):
        with patch("app.ai.factory.settings.OPENAI_API_KEY", "server-secret"):
            with self.assertRaisesRegex(ValueError, "自己的"):
                await AIProviderFactory.create_provider(provider_name="openai", db=self.db, user_id=self.user.id)
            with self.assertRaises(ValueError):
                await AIProviderFactory.create_provider(provider_name="openai", user_id=self.user.id)
