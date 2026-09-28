"""Synthetic HTTP/SQL tests of protocol v1 across all five offline resources."""
import asyncio
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.auth import get_current_user
from app.database import Base, get_db, _configure_sqlite_connection
from app.models.user import User
from app.models.sync import SyncReceipt
from app.models.anki import AnkiCard
from app.utils.sync import begin_idempotent_operation


class SyncProtocolAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f'sqlite+aiosqlite:///{Path(self.tmp.name) / "sync.sqlite"}', connect_args={'timeout': 10})
        event.listen(self.engine.sync_engine, 'connect', _configure_sqlite_connection)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as db:
            users = [User(username=f'sync-{i}', email=f'sync-{i}@example.test', hashed_password='unused', is_active=True) for i in range(2)]
            db.add_all(users); await db.commit()
        self.owner, self.other = users
        self.current_user = self.owner
        async def current_user():
            return self.current_user
        async def database():
            async with self.sessions() as db:
                try:
                    yield db
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
        self.overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_current_user] = current_user
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url='http://synthetic.test')
        self.patches = [
            patch('app.services.association_service.attach_note_to_concepts', new=AsyncMock()),
            patch('app.services.association_service.find_associations', new=AsyncMock(return_value=[])),
        ]
        for patcher in self.patches:
            patcher.start()

    async def asyncTearDown(self):
        for patcher in self.patches:
            patcher.stop()
        await self.client.aclose()
        app.dependency_overrides.clear(); app.dependency_overrides.update(self.overrides)
        await self.engine.dispose(); self.tmp.cleanup()

    def headers(self, version=None, key=None):
        result = {'Idempotency-Key': key or str(uuid.uuid4())}
        if version is not None:
            result['If-Match'] = f'"{version}"'
        return result

    async def resources(self):
        parent = await self.client.post('/api/goals', json={'title': 'parent'})
        self.assertEqual(parent.status_code, 200, parent.text)
        return [
            ('notes', '/api/notes', '/api/notes', {'title': 'note', 'content': 'content'}, {'title': 'changed'}, {'title': 'second'}),
            ('goals', '/api/goals', '/api/goals', {'title': 'goal'}, {'description': 'changed'}, {'description': 'second'}),
            ('goalTasks', f'/api/goals/{parent.json()["id"]}/tasks', '/api/goals/tasks', {'title': 'task'}, {'title': 'changed'}, {'title': 'second'}),
            ('ankiCards', '/api/anki/cards', '/api/anki/cards', {'front': 'front', 'back': 'back'}, {'note': 'changed'}, {'note': 'second'}),
            ('wrongQuestions', '/api/wrong-questions', '/api/wrong-questions', {'content': 'question'}, {'mastery_status': 'mastered'}, {'mastery_status': 'not_mastered'}),
        ]

    async def test_capabilities_and_entire_crud_replay_contract(self):
        self.assertEqual((await self.client.get('/api/sync/capabilities')).json(),
            {'protocol_version': 1, 'review_attempts': True, 'keyset_collections': True})
        for module, collection, item_path, body, first_edit, second_edit in await self.resources():
            with self.subTest(module=module):
                create_headers = self.headers()
                created = await self.client.post(collection, json=body, headers=create_headers)
                self.assertEqual(created.status_code, 200, created.text)
                original = created.json(); version = original['sync_version']; record_id = original['id']
                self.assertGreaterEqual(version, 1)
                self.assertTrue(original['created_at'].endswith('Z'))
                replay = await self.client.post(collection, json=body, headers=create_headers)
                self.assertEqual(replay.json(), original)
                path = f'{item_path}/{record_id}'
                preview = f'/api/sync/{module}/{record_id}'
                self.assertEqual((await self.client.get(preview)).json()['sync_version'], version)
                self.current_user = self.other
                self.assertEqual((await self.client.get(preview)).status_code, 404)
                denied = await self.client.put(path, json=first_edit, headers=self.headers(0))
                self.assertEqual(denied.status_code, 404, denied.text)
                self.current_user = self.owner
                legacy = await self.client.put(path, json=first_edit)
                self.assertEqual(legacy.status_code, 200, legacy.text)
                new_version = legacy.json()['sync_version']
                self.assertGreater(new_version, version)
                stale = await self.client.put(path, json=second_edit, headers=self.headers(version))
                self.assertEqual(stale.status_code, 409, stale.text)
                self.assertEqual(stale.json()['detail']['code'], 'SYNC_CONFLICT')
                update_headers = self.headers(new_version)
                updated = await self.client.put(path, json=second_edit, headers=update_headers)
                self.assertEqual(updated.status_code, 200, updated.text)
                self.assertEqual((await self.client.put(path, json=second_edit, headers=update_headers)).json(), updated.json())
                bad_headers = {**update_headers, 'If-Match': f'"{updated.json()["sync_version"]}"'}
                reused = await self.client.put(path, json=second_edit, headers=bad_headers)
                self.assertEqual(reused.status_code, 409)
                self.assertEqual(reused.json()['detail']['code'], 'IDEMPOTENCY_KEY_REUSED')
                delete_headers = self.headers(updated.json()['sync_version'])
                deleted = await self.client.delete(path, headers=delete_headers)
                self.assertEqual(deleted.status_code, 200, deleted.text)
                self.assertEqual((await self.client.delete(path, headers=delete_headers)).json(), deleted.json())
                self.assertEqual((await self.client.post(collection, json=body, headers=create_headers)).json(), original)
                self.assertEqual((await self.client.get(preview)).status_code, 404)

    async def test_concurrent_create_and_cas_writers(self):
        for module, collection, item_path, body, first_edit, second_edit in await self.resources():
            with self.subTest(module=module):
                headers = self.headers()
                created = await asyncio.gather(*[self.client.post(collection, json=body, headers=headers) for _ in range(2)])
                self.assertEqual([res.status_code for res in created], [200, 200], [res.text for res in created])
                self.assertEqual(created[0].json(), created[1].json())
                record = created[0].json()
                path = f'{item_path}/{record["id"]}'
                edits = await asyncio.gather(
                    self.client.put(path, json=first_edit, headers=self.headers(record['sync_version'])),
                    self.client.put(path, json=second_edit, headers=self.headers(record['sync_version'])),
                )
                # One update is a no-op for wrongQuestions ('not_mastered'), so use
                # two actual changes for that resource in its dedicated test below.
                if module != 'wrongQuestions':
                    self.assertEqual(sorted(res.status_code for res in edits), [200, 409], [res.text for res in edits])

    async def test_receipt_reservation_rolls_back_with_outer_transaction(self):
        key = str(uuid.uuid4())
        async with self.sessions() as db:
            await begin_idempotent_operation(db, user_id=self.owner.id, idempotency_key=key, method='POST', path='/test', body={})
            await db.rollback()
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count(SyncReceipt.id))), 0)

    async def test_response_finalization_failure_rolls_back_domain_and_receipt(self):
        headers = self.headers()
        with patch('app.routers.anki.complete_idempotent_operation', new=AsyncMock(side_effect=RuntimeError('injected finalization failure'))):
            failed = await self.client.post('/api/anki/cards', json={'front': 'f', 'back': 'b'}, headers=headers)
        self.assertEqual(failed.status_code, 500)
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count(AnkiCard.id))), 0)
            self.assertEqual(await db.scalar(select(func.count(SyncReceipt.id))), 0)
        retried = await self.client.post('/api/anki/cards', json={'front': 'f', 'back': 'b'}, headers=headers)
        self.assertEqual(retried.status_code, 200, retried.text)

    async def test_nullable_fields_are_cleared_not_silently_ignored(self):
        goal = (await self.client.post('/api/goals', json={'title': 'g', 'description': 'clear me', 'deadline': '2026-12-01'})).json()
        result = await self.client.put(f'/api/goals/{goal["id"]}', json={'description': None, 'deadline': None}, headers=self.headers(goal['sync_version']))
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIsNone(result.json()['description'])
        self.assertIsNone(result.json()['deadline'])
        task = (await self.client.post(f'/api/goals/{goal["id"]}/tasks', json={'title': 't', 'planned_date': '2026-12-01'})).json()
        result = await self.client.put(f'/api/goals/tasks/{task["id"]}', json={'planned_date': None}, headers=self.headers(task['sync_version']))
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIsNone(result.json()['planned_date'])

    async def test_links_only_note_update_advances_revision_and_replays_once(self):
        goal = (await self.client.post('/api/goals', json={'title': 'link target'})).json()
        note = (await self.client.post('/api/notes', json={'title': 'note', 'content': 'text'})).json()
        headers = self.headers(note['sync_version'])
        body = {'links': [{'link_type': 'goal', 'link_id': goal['id']}]}
        updated = await self.client.put(f'/api/notes/{note["id"]}', json=body, headers=headers)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertGreater(updated.json()['sync_version'], note['sync_version'])
        self.assertEqual(len(updated.json()['links']), 1)
        replay = await self.client.put(f'/api/notes/{note["id"]}', json=body, headers=headers)
        self.assertEqual(replay.json(), updated.json())

    async def test_wrong_question_concurrent_changes_have_one_winner(self):
        row = (await self.client.post('/api/wrong-questions', json={'content': 'q'})).json()
        results = await asyncio.gather(*[
            self.client.put(f'/api/wrong-questions/{row["id"]}', json={'mastery_status': status}, headers=self.headers(row['sync_version']))
            for status in ('mastered', 'reviewing')
        ])
        self.assertEqual(sorted(res.status_code for res in results), [200, 409], [res.text for res in results])
