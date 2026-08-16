"""联想引擎 v1 测试：概念匹配、证据收集、价值门槛、笔记挂图。"""
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.concept import ConceptLink
from app.models.material import Chapter, Material
from app.models.note import Note
from app.models.question import Question, WrongQuestion
from app.models.user import User
from app.services.association_coach_service import create_association_recall_nudge
from app.services.association_service import (
    attach_note_to_concepts,
    find_associations,
    match_concepts_in_text,
)
from app.services.concept_service import add_edge, link_concept, upsert_concept


class _AssociationTestBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "assoc.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user(self, username: str) -> int:
        async with self.sessionmaker() as session:
            user = User(username=username, email=f"{username}@example.com", hashed_password="hash", is_active=True)
            session.add(user)
            await session.flush()
            user_id = int(user.id)
            await session.commit()
            return user_id


class ConceptMatchingTests(_AssociationTestBase):
    async def test_matches_known_concept_names_in_text(self):
        user_id = await self._create_user("match_user")
        async with self.sessionmaker() as session:
            await upsert_concept(session, user_id, "贝叶斯定理")
            await upsert_concept(session, user_id, "动态规划")
            await session.commit()

        async with self.sessionmaker() as session:
            matched = await match_concepts_in_text(
                session, user_id, "今天学了贝叶斯定理的推导，感觉理解了。"
            )

        self.assertEqual([c.name for c in matched], ["贝叶斯定理"])

    async def test_does_not_match_other_users_concepts(self):
        user_a = await self._create_user("match_a")
        user_b = await self._create_user("match_b")
        async with self.sessionmaker() as session:
            await upsert_concept(session, user_a, "贝叶斯定理")
            await session.commit()

        async with self.sessionmaker() as session:
            matched = await match_concepts_in_text(session, user_b, "学习贝叶斯定理")

        self.assertEqual(matched, [])


class FindAssociationsTests(_AssociationTestBase):
    async def _seed_graph_with_evidence(self, user_id: int) -> dict:
        """条件概率 --prerequisite_of--> 贝叶斯定理；条件概率挂 1 条旧笔记 + 1 条错题。"""
        async with self.sessionmaker() as session:
            conditional = await upsert_concept(session, user_id, "条件概率")
            bayes = await upsert_concept(session, user_id, "贝叶斯定理")
            await add_edge(session, user_id, conditional.id, bayes.id, "prerequisite_of")

            old_note = Note(user_id=user_id, title="三月的概率笔记", content="条件概率的乘法法则整理")
            session.add(old_note)
            material = Material(user_id=user_id, title="概率论", content="x")
            session.add(material)
            await session.flush()
            chapter = Chapter(material_id=material.id, title="第二章", order_index=1)
            session.add(chapter)
            await session.flush()
            question = Question(user_id=user_id, chapter_id=chapter.id, content="求P(A|B)", question_type="choice")
            session.add(question)
            await session.flush()
            wrong = WrongQuestion(user_id=user_id, question_id=question.id, knowledge_point="条件概率", wrong_count=2)
            session.add(wrong)
            await session.flush()

            await link_concept(session, user_id, conditional.id, "note", int(old_note.id), link_type="explains")
            await link_concept(session, user_id, conditional.id, "wrong_question", int(wrong.id), link_type="tests")
            await session.commit()
            return {"conditional_id": conditional.id, "bayes_id": bayes.id, "note_id": int(old_note.id)}

    async def test_new_content_links_back_to_old_knowledge_with_evidence(self):
        # Arrange
        user_id = await self._create_user("assoc_user")
        await self._seed_graph_with_evidence(user_id)

        # Act：新内容提到"贝叶斯定理"——应联想到先修"条件概率"及其证据
        async with self.sessionmaker() as session:
            associations = await find_associations(
                session, user_id, "今天开始学贝叶斯定理，公式有点绕。"
            )

        # Assert
        self.assertEqual(len(associations), 1)
        assoc = associations[0]
        self.assertEqual(assoc["concept_name"], "贝叶斯定理")
        self.assertEqual(len(assoc["prerequisites"]), 1)
        prereq = assoc["prerequisites"][0]
        self.assertEqual(prereq["name"], "条件概率")
        self.assertEqual(len(prereq["evidence"]["notes"]), 1)
        self.assertEqual(prereq["evidence"]["notes"][0]["title"], "三月的概率笔记")
        self.assertEqual(len(prereq["evidence"]["wrong_questions"]), 1)
        self.assertIn("先修知识", assoc["reason"])

    async def test_concept_without_evidence_is_filtered_by_value_gate(self):
        # Arrange：只有孤立概念，无证据、无关系
        user_id = await self._create_user("gate_user")
        async with self.sessionmaker() as session:
            await upsert_concept(session, user_id, "傅里叶变换")
            await session.commit()

        # Act
        async with self.sessionmaker() as session:
            associations = await find_associations(session, user_id, "开始学傅里叶变换")

        # Assert：低价值联想宁可不发
        self.assertEqual(associations, [])

    async def test_triggering_note_is_excluded_from_its_own_evidence(self):
        # Arrange
        user_id = await self._create_user("exclude_user")
        seeded = await self._seed_graph_with_evidence(user_id)

        # Act：把旧笔记自己作为触发者，证据里不应包含它自己
        async with self.sessionmaker() as session:
            associations = await find_associations(
                session,
                user_id,
                "条件概率的补充笔记",
                exclude_note_id=seeded["note_id"],
            )

        # Assert
        self.assertEqual(len(associations), 1)
        self.assertEqual(associations[0]["evidence"]["notes"], [])
        # 错题证据仍在
        self.assertEqual(len(associations[0]["evidence"]["wrong_questions"]), 1)


class NoteAttachTests(_AssociationTestBase):
    async def test_saving_note_attaches_explains_links(self):
        # Arrange
        user_id = await self._create_user("attach_user")
        async with self.sessionmaker() as session:
            concept = await upsert_concept(session, user_id, "条件概率")
            note = Note(user_id=user_id, title="新笔记", content="今天复盘了条件概率的定义")
            session.add(note)
            await session.flush()

            # Act
            matched = await attach_note_to_concepts(session, user_id, note)
            await session.commit()
            concept_id = concept.id
            note_id = int(note.id)

        # Assert
        self.assertEqual([c.name for c in matched], ["条件概率"])
        async with self.sessionmaker() as session:
            link = (
                await session.execute(
                    select(ConceptLink).where(
                        ConceptLink.user_id == user_id,
                        ConceptLink.concept_id == concept_id,
                        ConceptLink.target_type == "note",
                        ConceptLink.target_id == note_id,
                    )
                )
            ).scalar_one_or_none()
        self.assertIsNotNone(link)
        self.assertEqual(link.link_type, "explains")


class AssociationCoachAttributionTests(_AssociationTestBase):
    async def test_explicit_association_request_creates_traceable_nudge(self):
        user_id = await self._create_user("association_coach")
        seeded = await FindAssociationsTests._seed_graph_with_evidence(self, user_id)

        async with self.sessionmaker() as session:
            associations = await find_associations(
                session,
                user_id,
                "今天开始学贝叶斯定理，公式有点绕。",
            )
            result = await create_association_recall_nudge(
                session,
                user_id,
                query_text="今天开始学贝叶斯定理，公式有点绕。",
                associations=associations,
            )
            await session.commit()

        self.assertIsNotNone(result["event"])
        self.assertIsNotNone(result["nudge"])
        nudge = result["nudge"]
        self.assertEqual(nudge["skill_id"], "association_recall")
        self.assertEqual(nudge["channel"], "agent_panel")
        self.assertEqual(nudge["route"], "/agent")
        self.assertEqual(
            nudge["explainability"]["source"]["type"],
            "association_engine",
        )
        self.assertEqual(
            nudge["explainability"]["association_ids"],
            [seeded["bayes_id"]],
        )
        self.assertEqual(
            nudge["explainability"]["associations"][0]["evidence"]["notes"],
            [],
        )
        self.assertEqual(
            nudge["explainability"]["associations"][0]["prerequisites"][0]["evidence"]["notes"][0]["id"],
            seeded["note_id"],
        )

    async def test_explicit_association_request_is_deduplicated_for_recent_same_query(self):
        user_id = await self._create_user("association_coach_dedupe")
        await FindAssociationsTests._seed_graph_with_evidence(self, user_id)

        async with self.sessionmaker() as session:
            associations = await find_associations(session, user_id, "开始学贝叶斯定理")
            first = await create_association_recall_nudge(
                session,
                user_id,
                query_text="开始学贝叶斯定理",
                associations=associations,
            )
            second = await create_association_recall_nudge(
                session,
                user_id,
                query_text="开始学贝叶斯定理",
                associations=associations,
            )
            await session.commit()

            from app.models.coach import CoachEvent, CoachNudge

            event_count = (
                await session.execute(
                    select(CoachEvent).where(
                        CoachEvent.user_id == user_id,
                        CoachEvent.event_type == "association.recalled",
                    )
                )
            ).scalars().all()
            nudge_count = (
                await session.execute(
                    select(CoachNudge).where(
                        CoachNudge.user_id == user_id,
                        CoachNudge.skill_id == "association_recall",
                    )
                )
            ).scalars().all()

        self.assertEqual(first["event"]["id"], second["event"]["id"])
        self.assertEqual(first["nudge"]["id"], second["nudge"]["id"])
        self.assertEqual(len(event_count), 1)
        self.assertEqual(len(nudge_count), 1)


if __name__ == "__main__":
    unittest.main()
