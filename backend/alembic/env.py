"""Alembic env.py - async migration environment."""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.database import Base

# Import ALL models so Base.metadata picks them up
from app.models.user import User  # noqa
from app.models.material import Material, Chapter  # noqa
from app.models.goal import Goal, Task  # noqa
from app.models.session import StudySession, Conversation  # noqa
from app.models.question import Question, QuizRecord, WrongQuestion, ReviewSchedule  # noqa
from app.models.pomodoro import Pomodoro, DailyStat  # noqa
from app.models.note import Note, NoteLink  # noqa
from app.models.chat import ChatProject, ChatProjectMaterial, ChatConversation, ChatMessage  # noqa
from app.models.ai_settings import AIProviderSetting  # noqa
from app.models.ai_routing import AIRoutingSetting  # noqa
from app.models.memory import ConversationSummary, UserMemory  # noqa
from app.models.progress import MaterialProfile, OutputEvaluation  # noqa
from app.models.daily_plan import DailyPlan  # noqa

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Override sqlalchemy.url from app settings
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
