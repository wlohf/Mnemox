"""数据模型"""
from app.models.user import User  # noqa: F401
from app.models.chat import ChatProject, ChatProjectMaterial, ChatConversation, ChatMessage  # noqa: F401
from app.models.material import Material, Chapter  # noqa: F401
from app.models.goal import Goal, Task  # noqa: F401
from app.models.session import StudySession, Conversation  # noqa: F401
from app.models.question import Question, QuizRecord, WrongQuestion, ReviewSchedule  # noqa: F401
from app.models.note import Note, NoteLink  # noqa: F401
from app.models.pomodoro import Pomodoro  # noqa: F401
from app.models.daily_plan import DailyPlan  # noqa: F401
from app.models.ai_settings import AIProviderSetting  # noqa: F401
from app.models.search_settings import AISearchSettings  # noqa: F401
from app.models.search_cache import WebSearchCache  # noqa: F401
from app.models.ai_routing import AIRoutingSetting  # noqa: F401
from app.models.memory import ConversationSummary, MemoryDeclaration, UserMemory  # noqa: F401
from app.models.progress import MaterialProfile, OutputEvaluation  # noqa: F401
from app.models.motivation import MotivationQuote, MotivationSettings  # noqa: F401
from app.models.user_profile import UserProfile  # noqa: F401
from app.models.learning_event import LearningEvent  # noqa: F401
from app.models.anki import AnkiCard  # noqa: F401
from app.models.sync import SyncReceipt  # noqa: F401
from app.models.agent import AgentActionConfirmation, AgentJob, AgentExecutionLog  # noqa: F401
from app.models.coach import CoachActionAttempt, CoachEvent, CoachNudge, CoachPreference, CoachSkillStats, CoachWorkflow  # noqa: F401
from app.models.note_quote import NoteQuoteUsage  # noqa: F401
from app.models.concept import (  # noqa: F401
    Concept,
    ConceptAlias,
    ConceptAuditEvent,
    ConceptEdge,
    ConceptLink,
    ConceptSourceEvidence,
)
from app.models.prompt_template import PromptTemplate  # noqa: F401
from app.models.retrieval import RetrievalProjection, RetrievalProjectionChunk  # noqa: F401
from app.models.knowledge import (  # noqa: F401
    Claim,
    ClaimConceptLink,
    ClaimEvidence,
    ClaimRelation,
    EntityResolutionCandidate,
    KnowledgeEmbeddingProjection,
    KnowledgeExtractionRun,
    KnowledgeProjectionOutbox,
    KnowledgeSource,
    KnowledgeSourceRevision,
    KnowledgeUnit,
)
from app.models.extraction_budget import ExtractionCall, ExtractionDailyBudget  # noqa: F401
from app.models.learner_model import (  # noqa: F401
    LearnerEvidence,
    ProjectionOutbox,
    ProjectionOutboxRetryPolicy,
    ProjectionOutboxWorkerHeartbeat,
    UserConceptState,
)

from sqlalchemy import event as _event
from sqlalchemy.orm import Session as _Session

# Owner-scoped rows that once fell back to user 1. Older SQLite files still
# carry a column-level DEFAULT 1, so an omitted owner must fail before INSERT
# instead of silently attributing the row to another account.
OWNER_REQUIRED_MODELS = (
    AIProviderSetting, AIRoutingSetting, AnkiCard, ChatConversation, ChatProject,
    ConversationSummary, DailyPlan, Goal, LearningEvent, Material, MotivationQuote,
    Note, Question, ReviewSchedule, StudySession, UserMemory, WrongQuestion,
)


@_event.listens_for(_Session, "before_flush")
def _require_row_owner(session, _flush_context, _instances) -> None:
    for instance in session.new:
        if isinstance(instance, OWNER_REQUIRED_MODELS) and instance.user_id is None:
            raise ValueError(f"{type(instance).__name__}.user_id is required")

from app.models.understanding import UnderstandingPreference, Experience, BehavioralHypothesis, HypothesisRevision  # noqa: F401
