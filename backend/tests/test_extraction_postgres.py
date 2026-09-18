"""Opt-in disposable PostgreSQL acceptance; includes independent worker processes.

Requires MNEMOX_EXTRACTION_TEST_POSTGRES_URL, a loopback mnemox_phase3_* database,
and MNEMOX_EXTRACTION_TEST_ALLOW_SYNTHETIC_WRITES=1. The operator must verify the
server is disposable; URL checks cannot prove a local proxy's database isolation.
"""
import asyncio
import os
import sys
import unittest
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

import test_knowledge_extraction_budget as ledger_tests
import test_knowledge_extraction_runtime as runtime_tests
from app.models.extraction_budget import ExtractionDailyBudget

URL = os.environ.get('MNEMOX_EXTRACTION_TEST_POSTGRES_URL', '')
ENABLED = bool(URL) and os.environ.get('MNEMOX_EXTRACTION_TEST_ALLOW_SYNTHETIC_WRITES') == '1'


class PostgresFixture:
    async def _test_engine(self):
        parsed = urlparse(URL)
        if parsed.scheme != 'postgresql+asyncpg' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or not parsed.path.startswith('/mnemox_phase3_'):
            raise RuntimeError('Use an explicitly disposable loopback mnemox_phase3_* PostgreSQL database')
        self.pg_schema = 'extraction_test_' + uuid4().hex
        self.admin_engine = create_async_engine(URL)
        async with self.admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{self.pg_schema}"'))
        return create_async_engine(URL, connect_args={'server_settings': {
            'search_path': self.pg_schema, 'timezone': 'UTC', 'statement_timeout': '10000', 'lock_timeout': '5000',
        }})

    async def asyncTearDown(self):
        try:
            await super().asyncTearDown()
        finally:
            async with self.admin_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{self.pg_schema}" CASCADE'))
            await self.admin_engine.dispose()


@unittest.skipUnless(ENABLED, 'Requires explicitly authorized disposable PostgreSQL')
class PostgresExtractionRuntimeTests(PostgresFixture, runtime_tests.ExtractionRuntimeTests):
    pass


@unittest.skipUnless(ENABLED, 'Requires explicitly authorized disposable PostgreSQL')
class PostgresExtractionBudgetTests(PostgresFixture, ledger_tests.ExtractionBudgetLedgerTests):
    async def test_independent_processes_cannot_overspend_the_same_day(self):
        async with self.sessions() as db:
            second = await self._add_run(db, 'process')
            await db.commit()
        code = '''
import asyncio, os, sys
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.services.extraction_budget_service import reserve_extraction_call, ExtractionBudgetExceeded
async def main():
    engine = create_async_engine(os.environ['PG_TEST_URL'], connect_args={'server_settings': {'search_path': os.environ['PG_TEST_SCHEMA'], 'timezone': 'UTC', 'lock_timeout': '5000'}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            try:
                await reserve_extraction_call(db, call_id=sys.argv[1], user_id=int(sys.argv[2]), run_id=int(sys.argv[3]), unit_id=int(sys.argv[4]), lease_token=sys.argv[5], estimated_tokens=1500, now=datetime(2030, 6, 2, 12))
                await db.commit()
                print('reserved')
            except ExtractionBudgetExceeded:
                await db.rollback()
                print('blocked')
    finally:
        await engine.dispose()
asyncio.run(main())
'''
        env = {
            'PATH': os.environ.get('PATH', ''), 'HOME': '/tmp', 'LANG': 'C.UTF-8',
            'SECRET_KEY': 'synthetic-postgres-subprocess-only-secret',
            'ENVIRONMENT': 'development', 'RAG_ENABLED': 'false',
            'PG_TEST_URL': URL, 'PG_TEST_SCHEMA': self.pg_schema,
            'KNOWLEDGE_LLM_DAILY_ESTIMATED_TOKENS_PER_USER': '2000',
            'PYTHONDONTWRITEBYTECODE': '1',
        }

        async def attempt(identity):
            run_id, unit_id, token = identity
            process = await asyncio.create_subprocess_exec(
                sys.executable, '-c', code, str(uuid4()), str(self.user_id), str(run_id), str(unit_id), token,
                env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), 20)
            except BaseException:
                process.kill()
                await process.wait()
                raise
            self.assertEqual(process.returncode, 0, stderr.decode())
            return stdout.decode().strip()
        results = await asyncio.gather(attempt((self.run_id, self.unit_id, self.lease_token)), attempt(second))
        self.assertEqual(sorted(results), ['blocked', 'reserved'])
        async with self.sessions() as db:
            self.assertEqual((await db.scalar(select(ExtractionDailyBudget))).charged_tokens, 1500)
