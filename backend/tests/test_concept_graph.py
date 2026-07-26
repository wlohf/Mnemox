"""概念图谱（决策 D2）测试：归一去重、结构入图、LLM 抽取、错题回填、邻域查询。"""
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.concept import Concept, ConceptLink
from app.models.material import Chapter, Material
from app.models.question import Question, WrongQuestion
from app.models.user import User
from app.services.concept_service import (
    add_edge,
    backfill_wrong_question_concepts,
    extract_chapter_concepts_llm,
    get_concept_neighborhood,
    ingest_structure_concepts,
    list_concepts,
    normalize_concept_name,
    upsert_concept,
)


class FakeExtractionProvider:
    def __init__(self, reply: str):
        self.reply = reply
        self.messages = None

    async def chat(self, messages=None, system_prompt=None, temperature=None, **kwargs):
        self.messages = messages
        return self.reply


class _ConceptTestBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "concepts.sqlite3"
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

    async def _create_material_with_chapter(self, user_id: int, chapter_title: str) -> tuple[int, int]:
        async with self.sessionmaker() as session:
            material = Material(user_id=user_id, title="概率论", content="教材内容")
            session.add(material)
            await session.flush()
            chapter = Chapter(material_id=material.id, title=chapter_title, content="条件概率与贝叶斯定理详解", order_index=1)
            session.add(chapter)
            await session.flush()
            ids = (int(material.id), int(chapter.id))
            await session.commit()
            return ids


class ConceptUpsertTests(_ConceptTestBase):
    def test_normalize_merges_whitespace_and_case(self):
        self.assertEqual(normalize_concept_name("  Bayes  Theorem "), "bayes theorem")
        self.assertEqual(normalize_concept_name("贝叶斯定理。"), "贝叶斯定理")

    async def test_same_concept_different_form_is_deduped(self):
        user_id = await self._create_user("dedupe_user")
        async with self.sessionmaker() as session:
            first = await upsert_concept(session, user_id, "贝叶斯定理")
            second = await upsert_concept(session, user_id, " 贝叶斯定理。 ")
            await session.commit()
        self.assertEqual(first.id, second.id)

    async def test_concepts_are_isolated_per_user(self):
        user_a = await self._create_user("concept_a")
        user_b = await self._create_user("concept_b")
        async with self.sessionmaker() as session:
            a = await upsert_concept(session, user_a, "条件概率")
            b = await upsert_concept(session, user_b, "条件概率")
            await session.commit()
        self.assertNotEqual(a.id, b.id)

    async def test_blank_or_too_short_name_returns_none(self):
        user_id = await self._create_user("blank_user")
        async with self.sessionmaker() as session:
            self.assertIsNone(await upsert_concept(session, user_id, "  "))
            self.assertIsNone(await upsert_concept(session, user_id, "x"))


class StructureIngestTests(_ConceptTestBase):
    async def test_key_points_become_concepts_linked_to_chapter(self):
        # Arrange
        user_id = await self._create_user("structure_user")
        _, chapter_id = await self._create_material_with_chapter(user_id, "第三章 贝叶斯")
        structure = [
            {"title": "第三章 贝叶斯", "key_points": ["条件概率", "贝叶斯定理", "全概率公式"]},
            {"title": "不存在的章节", "key_points": ["孤儿概念"]},
        ]

        # Act
        async with self.sessionmaker() as session:
            material_result = await session.execute(select(Material).where(Material.user_id == user_id))
            material_id = int(material_result.scalars().first().id)
            count = await ingest_structure_concepts(session, user_id, material_id, structure)
            await session.commit()

        # Assert：3 个概念挂到章节；孤儿概念也入库但无挂接
        self.assertEqual(count, 4)
        async with self.sessionmaker() as session:
            links = (
                await session.execute(
                    select(ConceptLink).where(
                        ConceptLink.user_id == user_id,
                        ConceptLink.target_type == "chapter",
                        ConceptLink.target_id == chapter_id,
                    )
                )
            ).scalars().all()
            self.assertEqual(len(links), 3)


class LlmExtractionTests(_ConceptTestBase):
    async def test_extraction_creates_concepts_and_prerequisite_edges(self):
        # Arrange
        user_id = await self._create_user("extract_user")
        _, chapter_id = await self._create_material_with_chapter(user_id, "第三章")
        reply = (
            '{"concepts":[{"name":"条件概率","description":"P(A|B)"},'
            '{"name":"贝叶斯定理","description":"由条件概率推出"}],'
            '"edges":[{"from":"条件概率","to":"贝叶斯定理","type":"prerequisite_of"}]}'
        )
        provider = FakeExtractionProvider(reply)

        # Act
        async with self.sessionmaker() as session:
            chapter = (
                await session.execute(select(Chapter).where(Chapter.id == chapter_id))
            ).scalar_one()
            stats = await extract_chapter_concepts_llm(session, user_id, chapter, provider)
            await session.commit()

        # Assert
        self.assertEqual(stats, {"concepts": 2, "edges": 1})
        # 章节内容进入了不可信上下文包装
        self.assertIn("untrusted_context", provider.messages[0]["content"])

        async with self.sessionmaker() as session:
            neighborhood = await get_concept_neighborhood(
                session,
                user_id,
                (
                    await session.execute(
                        select(Concept).where(Concept.user_id == user_id, Concept.name == "贝叶斯定理")
                    )
                ).scalar_one().id,
            )
        edge = neighborhood["edges"][0]
        self.assertEqual(edge["type"], "prerequisite_of")

    async def test_malformed_llm_output_creates_nothing_and_does_not_raise(self):
        user_id = await self._create_user("bad_output_user")
        _, chapter_id = await self._create_material_with_chapter(user_id, "第四章")
        provider = FakeExtractionProvider("抱歉，我无法完成这个任务")

        async with self.sessionmaker() as session:
            chapter = (
                await session.execute(select(Chapter).where(Chapter.id == chapter_id))
            ).scalar_one()
            stats = await extract_chapter_concepts_llm(session, user_id, chapter, provider)

        self.assertEqual(stats, {"concepts": 0, "edges": 0})


class WrongQuestionBackfillTests(_ConceptTestBase):
    async def test_knowledge_point_strings_become_concepts_with_tests_links(self):
        # Arrange
        user_id = await self._create_user("backfill_user")
        _, chapter_id = await self._create_material_with_chapter(user_id, "第五章")
        async with self.sessionmaker() as session:
            question = Question(user_id=user_id, chapter_id=chapter_id, content="求条件概率", question_type="short_answer")
            session.add(question)
            await session.flush()
            session.add(
                WrongQuestion(user_id=user_id, question_id=question.id, knowledge_point="条件概率")
            )
            await session.commit()

        # Act
        async with self.sessionmaker() as session:
            stats = await backfill_wrong_question_concepts(session, user_id)
            await session.commit()

        # Assert
        self.assertEqual(stats["updated_wrong_questions"], 1)
        self.assertEqual(stats["created_links"], 1)
        async with self.sessionmaker() as session:
            wrong = (
                await session.execute(select(WrongQuestion).where(WrongQuestion.user_id == user_id))
            ).scalar_one()
            self.assertIsNotNone(wrong.concept_id)

        # 幂等：再跑一次不重复回填
        async with self.sessionmaker() as session:
            second = await backfill_wrong_question_concepts(session, user_id)
        self.assertEqual(second["updated_wrong_questions"], 0)


class NeighborhoodTests(_ConceptTestBase):
    async def test_two_hop_neighborhood_reaches_indirect_prerequisites(self):
        # Arrange: 集合论 -> 条件概率 -> 贝叶斯定理 的先修链
        user_id = await self._create_user("hop_user")
        async with self.sessionmaker() as session:
            set_theory = await upsert_concept(session, user_id, "集合论")
            conditional = await upsert_concept(session, user_id, "条件概率")
            bayes = await upsert_concept(session, user_id, "贝叶斯定理")
            await add_edge(session, user_id, set_theory.id, conditional.id, "prerequisite_of")
            await add_edge(session, user_id, conditional.id, bayes.id, "prerequisite_of")
            await session.commit()
            bayes_id = bayes.id

        # Act
        async with self.sessionmaker() as session:
            one_hop = await get_concept_neighborhood(session, user_id, bayes_id, depth=1)
            two_hop = await get_concept_neighborhood(session, user_id, bayes_id, depth=2)

        # Assert
        one_hop_names = {n["name"] for n in one_hop["nodes"]}
        two_hop_names = {n["name"] for n in two_hop["nodes"]}
        self.assertNotIn("集合论", one_hop_names)
        self.assertIn("集合论", two_hop_names)

    async def test_neighborhood_is_user_scoped(self):
        user_a = await self._create_user("hop_a")
        user_b = await self._create_user("hop_b")
        async with self.sessionmaker() as session:
            concept_a = await upsert_concept(session, user_a, "条件概率")
            await session.commit()
            concept_a_id = concept_a.id

        async with self.sessionmaker() as session:
            self.assertIsNone(await get_concept_neighborhood(session, user_b, concept_a_id))

    async def test_list_concepts_orders_by_link_count(self):
        user_id = await self._create_user("list_user")
        _, chapter_id = await self._create_material_with_chapter(user_id, "第六章")
        async with self.sessionmaker() as session:
            hot = await upsert_concept(session, user_id, "热门概念")
            cold = await upsert_concept(session, user_id, "冷门概念")
            from app.services.concept_service import link_concept

            await link_concept(session, user_id, hot.id, "chapter", chapter_id, link_type="covers")
            await session.commit()

        async with self.sessionmaker() as session:
            concepts = await list_concepts(session, user_id)
        self.assertEqual(concepts[0]["name"], "热门概念")
        self.assertEqual(concepts[0]["link_count"], 1)


if __name__ == "__main__":
    unittest.main()
