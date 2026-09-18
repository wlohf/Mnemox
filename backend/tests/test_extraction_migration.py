"""Synthetic populated pre-ledger upgrades; never use a work or production database."""
import asyncio
import json
import logging
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import _run_lightweight_migrations


def test_embedded_alembic_does_not_disable_application_loggers(tmp_path):
    logger = logging.getLogger('app.extraction_migration_probe')
    logger.disabled = False
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / 'alembic.ini'))
    config.set_main_option('script_location', str(backend / 'alembic'))
    config.set_main_option('sqlalchemy.url', f'sqlite+aiosqlite:///{tmp_path / "log-probe.sqlite"}')
    command.current(config)
    assert not logger.disabled


@pytest.mark.parametrize('mode', ['alembic', 'lightweight'])
def test_pre_ledger_runs_preserve_data_and_require_accounting_review(tmp_path, mode):
    path = tmp_path / 'legacy.sqlite'
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / 'alembic.ini'))
    config.set_main_option('script_location', str(backend / 'alembic'))
    config.set_main_option('sqlalchemy.url', f'sqlite+aiosqlite:///{path}')
    command.upgrade(config, '20260912_23')
    engine = create_engine(f'sqlite:///{path}')
    try:
        with engine.begin() as db:
            db.execute(text("INSERT INTO users (id, username, email, hashed_password) VALUES (1, 'legacy_synthetic', 'legacy@example.test', 'not-a-password')"))
            db.execute(text("INSERT INTO knowledge_sources (id, user_id, source_type, source_record_id, source_key, title_snapshot, current_revision) VALUES (1, 1, 'material', 1, 'material:1', 'Legacy synthetic', 1)"))
            db.execute(text("INSERT INTO knowledge_source_revisions (id, user_id, knowledge_source_id, revision, content_hash, title_snapshot) VALUES (1, 1, 1, 1, :hash, 'Legacy synthetic')"), {'hash': 'a' * 64})
            db.execute(text("INSERT INTO knowledge_units (id, user_id, source_revision_id, unit_type, ordinal, text, text_hash, locator) VALUES (1, 1, 1, 'chunk', 0, 'Synthetic retained source.', :hash, '{}')"), {'hash': 'b' * 64})
            for run_id, kind, usage in [(1, 'llm', {}), (2, 'llm', {'call_count': 2, 'estimated_tokens': 200}), (3, 'deterministic', {})]:
                db.execute(text("INSERT INTO knowledge_extraction_runs (id, user_id, source_revision_id, extractor_type, extractor_version, schema_version, input_hash, status, usage) VALUES (:id, 1, 1, :kind, 'legacy-test', 1, :hash, 'queued', :usage)"),
                           {'id': run_id, 'kind': kind, 'hash': str(run_id) * 64, 'usage': json.dumps(usage)})
        if mode == 'alembic':
            command.upgrade(config, 'head')
        else:
            async def lightweight():
                async_engine = create_async_engine(f'sqlite+aiosqlite:///{path}')
                try:
                    async with async_engine.begin() as db:
                        await _run_lightweight_migrations(db)
                    async with async_engine.begin() as db:
                        await _run_lightweight_migrations(db)
                finally:
                    await async_engine.dispose()
            asyncio.run(lightweight())
        with engine.begin() as db:
            rows = db.execute(text('SELECT id, usage, budget_review_required, lease_token, lease_expires_at FROM knowledge_extraction_runs ORDER BY id')).all()
            assert [row.budget_review_required for row in rows] == [1, 1, 0]
            assert json.loads(rows[1].usage) == {'call_count': 2, 'estimated_tokens': 200}
            assert all(row.lease_token is None and row.lease_expires_at is None for row in rows)
            assert db.scalar(text('SELECT text FROM knowledge_units WHERE id = 1')) == 'Synthetic retained source.'
            assert db.scalar(text('SELECT COUNT(*) FROM knowledge_extraction_calls')) == 0
            assert db.scalar(text('SELECT COUNT(*) FROM knowledge_extraction_daily_budgets')) == 0
    finally:
        engine.dispose()
