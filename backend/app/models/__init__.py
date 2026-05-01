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
from app.models.ai_routing import AIRoutingSetting  # noqa: F401
from app.models.memory import ConversationSummary, UserMemory  # noqa: F401
from app.models.progress import MaterialProfile, OutputEvaluation  # noqa: F401
from app.models.motivation import MotivationQuote, MotivationSettings  # noqa: F401
from app.models.user_profile import UserProfile  # noqa: F401
from app.models.learning_event import LearningEvent  # noqa: F401
from app.models.anki import AnkiCard  # noqa: F401
from app.models.agent import AgentJob, AgentExecutionLog  # noqa: F401
