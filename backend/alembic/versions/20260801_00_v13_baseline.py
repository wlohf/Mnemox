"""Frozen v1.3.0 schema baseline.

This revision is intentionally self-contained. It was expanded from the
``v1.3.0`` tag's model declarations, including ``prompt_templates`` which was
not imported by that tag's model registry. Do not replace these declarations
with live ORM metadata: this revision must remain reproducible after models
evolve.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260801_00"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # agent_execution_logs
    op.create_table(
        'agent_execution_logs',
        sa.Column('id', sa.String(length=32), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.String(length=32)),
        sa.Column('agent', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('metadata', sa.JSON()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # agent_jobs
    op.create_table(
        'agent_jobs',
        sa.Column('id', sa.String(length=32), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('agent', sa.String(length=50), nullable=False),
        sa.Column('task', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('payload', sa.JSON()),
        sa.Column('result', sa.JSON()),
        sa.Column('summary', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # learning_events
    op.create_table(
        'learning_events',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer()),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('event_category', sa.String(length=20)),
        sa.Column('source', sa.String(length=50)),
        sa.Column('dedupe_key', sa.String(length=160)),
        sa.Column('event_data', sa.JSON()),
        sa.Column('timestamp', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('duration', sa.Integer()),
        sa.Column('material_id', sa.Integer()),
        sa.Column('chapter_id', sa.Integer()),
        sa.Column('goal_id', sa.Integer()),
        sa.Column('task_id', sa.Integer()),
        sa.Column('note_id', sa.Integer()),
        sa.Column('wrong_question_id', sa.Integer()),
        sa.Column('session_id', sa.String(length=50)),
        sa.Column('metadata', sa.JSON()),
    )

    # user_profiles
    op.create_table(
        'user_profiles',
        sa.Column('user_id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('total_study_hours', sa.Float()),
        sa.Column('total_study_days', sa.Integer()),
        sa.Column('total_pomodoros', sa.Integer()),
        sa.Column('total_questions', sa.Integer()),
        sa.Column('total_correct', sa.Integer()),
        sa.Column('correct_rate', sa.Float()),
        sa.Column('learning_style', sa.String(length=20)),
        sa.Column('avg_session_duration', sa.Integer()),
        sa.Column('avg_pomodoro_per_day', sa.Float()),
        sa.Column('preferred_time_slots', sa.JSON()),
        sa.Column('optimal_hours', sa.String(length=20)),
        sa.Column('self_control_score', sa.Float()),
        sa.Column('consistency_score', sa.Float()),
        sa.Column('planning_score', sa.Float()),
        sa.Column('focus_score', sa.Float()),
        sa.Column('recent_performance', sa.JSON()),
        sa.Column('weak_points', sa.JSON()),
        sa.Column('strong_points', sa.JSON()),
        sa.Column('learning_patterns', sa.JSON()),
        sa.Column('ai_assessment', sa.Text()),
        sa.Column('personality_analysis', sa.JSON()),
        sa.Column('coaching_suggestions', sa.JSON()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('last_updated', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('last_study_date', sa.DateTime()),
        sa.Column('stats_period_days', sa.Integer()),
    )


    # users
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('email', sa.String(length=200), nullable=False),
        sa.Column('hashed_password', sa.String(length=200), nullable=False),
        sa.Column('is_active', sa.Boolean()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # ai_provider_settings
    op.create_table(
        'ai_provider_settings',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('provider_name', sa.String(length=50), nullable=False),
        sa.Column('display_name', sa.String(length=100), nullable=False),
        sa.Column('api_key', sa.String(length=2000)),
        sa.Column('base_url', sa.String(length=500)),
        sa.Column('model', sa.String(length=100)),
        sa.Column('available_models', sa.Text()),
        sa.Column('max_context_tokens', sa.Integer()),
        sa.Column('max_output_tokens', sa.Integer()),
        sa.Column('is_active', sa.Boolean()),
        sa.Column('enabled', sa.Boolean()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # ai_search_settings
    op.create_table(
        'ai_search_settings',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('default_mode', sa.String(length=40), nullable=False),
        sa.Column('provider', sa.String(length=40), nullable=False),
        sa.Column('tavily_api_key', sa.Text(), nullable=False),
        sa.Column('tavily_search_depth', sa.String(length=20), nullable=False),
        sa.Column('tavily_max_results', sa.Integer(), nullable=False),
        sa.Column('tavily_chunks_per_source', sa.Integer(), nullable=False),
        sa.Column('tavily_include_answer', sa.Boolean(), nullable=False),
        sa.Column('tavily_include_raw_content', sa.Boolean(), nullable=False),
        sa.Column('timeout_seconds', sa.Float(), nullable=False),
        sa.Column('fallback_enabled', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # anki_cards
    op.create_table(
        'anki_cards',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('front', sa.Text(), nullable=False),
        sa.Column('back', sa.Text(), nullable=False),
        sa.Column('source', sa.String(length=20)),
        sa.Column('tags', sa.String(length=255)),
        sa.Column('note', sa.Text()),
        sa.Column('due_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('interval_days', sa.Integer(), nullable=False),
        sa.Column('ease_factor', sa.Integer(), nullable=False),
        sa.Column('repetitions', sa.Integer(), nullable=False),
        sa.Column('last_quality', sa.Integer()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )


    # chat_projects
    op.create_table(
        'chat_projects',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('default_instructions', sa.Text()),
        sa.Column('color', sa.String(length=20)),
        sa.Column('is_archived', sa.Boolean()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # coach_events
    op.create_table(
        'coach_events',
        sa.Column('id', sa.String(length=40), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('dedupe_key', sa.String(length=160)),
        sa.Column('occurred_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # coach_nudges
    op.create_table(
        'coach_nudges',
        sa.Column('id', sa.String(length=40), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('event_id', sa.String(length=40)),
        sa.Column('skill_id', sa.String(length=80), nullable=False),
        sa.Column('channel', sa.String(length=40), nullable=False),
        sa.Column('priority', sa.String(length=20), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('suggested_action', sa.JSON(), nullable=False),
        sa.Column('route', sa.String(length=200)),
        sa.Column('requires_confirmation', sa.Boolean(), nullable=False),
        sa.Column('draft', sa.JSON()),
        sa.Column('explainability', sa.JSON()),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('expires_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # coach_preferences
    op.create_table(
        'coach_preferences',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('proactive_enabled', sa.Boolean(), nullable=False),
        sa.Column('desktop_notifications_enabled', sa.Boolean(), nullable=False),
        sa.Column('quiet_hours_start', sa.String(length=5)),
        sa.Column('quiet_hours_end', sa.String(length=5)),
        sa.Column('max_nudges_per_day', sa.Integer(), nullable=False),
        sa.Column('min_minutes_between_nudges', sa.Integer(), nullable=False),
        sa.Column('allowed_channels', sa.JSON(), nullable=False),
        sa.Column('disabled_skill_ids', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


    # coach_skill_stats
    op.create_table(
        'coach_skill_stats',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('skill_id', sa.String(length=80), nullable=False),
        sa.Column('channel', sa.String(length=40), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('shown_count', sa.Integer(), nullable=False),
        sa.Column('accepted_count', sa.Integer(), nullable=False),
        sa.Column('completed_count', sa.Integer(), nullable=False),
        sa.Column('helpful_count', sa.Integer(), nullable=False),
        sa.Column('snoozed_count', sa.Integer(), nullable=False),
        sa.Column('dismissed_count', sa.Integer(), nullable=False),
        sa.Column('too_disruptive_count', sa.Integer(), nullable=False),
        sa.Column('too_hard_count', sa.Integer(), nullable=False),
        sa.Column('too_easy_count', sa.Integer(), nullable=False),
        sa.Column('irrelevant_count', sa.Integer(), nullable=False),
        sa.Column('not_my_style_count', sa.Integer(), nullable=False),
        sa.Column('recent_score', sa.Float(), nullable=False),
        sa.Column('lifetime_score', sa.Float(), nullable=False),
        sa.Column('last_shown_at', sa.DateTime()),
        sa.Column('last_positive_at', sa.DateTime()),
        sa.Column('last_negative_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('user_id', 'skill_id', 'channel', 'event_type', name='uq_coach_skill_stats_scope'),
    )

    # coach_workflows
    op.create_table(
        'coach_workflows',
        sa.Column('id', sa.String(length=40), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('workflow_type', sa.String(length=80), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('current_step', sa.String(length=80), nullable=False),
        sa.Column('state', sa.JSON(), nullable=False),
        sa.Column('pending_draft', sa.JSON()),
        sa.Column('last_event_id', sa.String(length=40)),
        sa.Column('started_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime()),
    )

    # daily_plans
    op.create_table(
        'daily_plans',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('date', sa.String(length=10), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('task_ids', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint('user_id', 'date', name='uq_dailyplan_user_date'),
    )

    # daily_stats
    op.create_table(
        'daily_stats',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('date', sa.DateTime()),
        sa.Column('study_time', sa.Integer(), nullable=False),
        sa.Column('pomodoro_count', sa.Integer(), nullable=False),
        sa.Column('questions_attempted', sa.Integer(), nullable=False),
        sa.Column('questions_correct', sa.Integer(), nullable=False),
        sa.Column('chapters_reviewed', sa.Integer(), nullable=False),
        sa.Column('new_chapters_learned', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


    # materials
    op.create_table(
        'materials',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('file_path', sa.String(length=500)),
        sa.Column('file_type', sa.String(length=20)),
        sa.Column('file_hash', sa.String(length=64)),
        sa.Column('content_hash', sa.String(length=64)),
        sa.Column('content', sa.Text()),
        sa.Column('content_status', sa.String(length=20)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # motivation_quotes
    op.create_table(
        'motivation_quotes',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('author', sa.String(length=100)),
        sa.Column('source_type', sa.String(length=20)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # prompt_templates
    op.create_table(
        'prompt_templates',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('mode_key', sa.String(length=40), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # review_schedule
    op.create_table(
        'review_schedule',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('item_type', sa.String(length=20)),
        sa.Column('item_id', sa.Integer()),
        sa.Column('scheduled_date', sa.DateTime()),
        sa.Column('interval_days', sa.Integer()),
        sa.Column('ease_factor', sa.Integer()),
        sa.Column('repetitions', sa.Integer()),
        sa.Column('last_quality', sa.Integer()),
        sa.Column('status', sa.String(length=20)),
        sa.Column('completed_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('is_archived', sa.Boolean(), nullable=False),
    )


    # web_search_cache
    op.create_table(
        'web_search_cache',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('query_hash', sa.String(length=64), nullable=False),
        sa.Column('normalized_query', sa.Text(), nullable=False),
        sa.Column('mode', sa.String(length=40), nullable=False),
        sa.Column('provider', sa.String(length=40), nullable=False),
        sa.Column('quality_key', sa.String(length=300), nullable=False),
        sa.Column('results_json', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text()),
        sa.Column('source_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
    )

    # ai_routing_settings
    op.create_table(
        'ai_routing_settings',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('scenario', sa.String(length=50), nullable=False),
        sa.Column('provider_name', sa.String(length=50)),
        sa.Column('model', sa.String(length=100)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # chapters
    op.create_table(
        'chapters',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('material_id', sa.Integer(), sa.ForeignKey('materials.id'), nullable=False),
        sa.Column('parent_id', sa.Integer(), sa.ForeignKey('chapters.id')),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('content', sa.Text()),
        sa.Column('order_index', sa.Integer()),
        sa.Column('mastery_level', sa.Float()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # chat_conversations
    op.create_table(
        'chat_conversations',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('chat_projects.id', ondelete='SET NULL')),
        sa.Column('title', sa.String(length=200)),
        sa.Column('summary', sa.Text()),
        sa.Column('is_pinned', sa.Boolean()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )


    # chat_project_materials
    op.create_table(
        'chat_project_materials',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('chat_projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('material_id', sa.Integer(), sa.ForeignKey('materials.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # material_profiles
    op.create_table(
        'material_profiles',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('material_id', sa.Integer(), sa.ForeignKey('materials.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('is_textbook', sa.Boolean()),
        sa.Column('confidence', sa.Float()),
        sa.Column('source', sa.String(length=20)),
        sa.Column('structure_json', sa.Text()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # motivation_settings
    op.create_table(
        'motivation_settings',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('display_mode', sa.String(length=20), nullable=False),
        sa.Column('selected_quote_id', sa.Integer(), sa.ForeignKey('motivation_quotes.id')),
        sa.Column('sort_mode', sa.String(length=30), nullable=False),
        sa.Column('rotation_seconds', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # chat_messages
    op.create_table(
        'chat_messages',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('conversation_id', sa.Integer(), sa.ForeignKey('chat_conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('image_data', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )


    # conversation_summaries
    op.create_table(
        'conversation_summaries',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('conversation_id', sa.Integer(), sa.ForeignKey('chat_conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('summary', sa.Text()),
        sa.Column('key_points', sa.Text()),
        sa.Column('todo_items', sa.Text()),
        sa.Column('message_count', sa.Integer()),
        sa.Column('last_message_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('questions_asked', sa.Text()),
        sa.Column('confusions', sa.Text()),
        sa.Column('misconceptions', sa.Text()),
        sa.Column('review_prompts', sa.Text()),
        sa.Column('reflection_turn_count', sa.Integer()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # goals
    op.create_table(
        'goals',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('material_id', sa.Integer(), sa.ForeignKey('materials.id')),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('target_level', sa.String(length=50)),
        sa.Column('deadline', sa.Date()),
        sa.Column('status', sa.String(length=20)),
        sa.Column('plan_total_days', sa.Integer()),
        sa.Column('plan_current_chapter_id', sa.Integer(), sa.ForeignKey('chapters.id')),
        sa.Column('plan_study_days_per_week', sa.Integer()),
        sa.Column('plan_start_date', sa.Date()),
        sa.Column('plan_last_generated_week', sa.Date()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # notes
    op.create_table(
        'notes',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('material_id', sa.Integer(), sa.ForeignKey('materials.id')),
        sa.Column('chapter_id', sa.Integer(), sa.ForeignKey('chapters.id')),
        sa.Column('title', sa.String(length=200)),
        sa.Column('content', sa.Text()),
        sa.Column('tags', sa.Text()),
        sa.Column('note_type', sa.String(length=20)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # questions
    op.create_table(
        'questions',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('chapter_id', sa.Integer(), sa.ForeignKey('chapters.id'), nullable=False),
        sa.Column('question_type', sa.String(length=20)),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('options', sa.JSON()),
        sa.Column('answer', sa.Text()),
        sa.Column('explanation', sa.Text()),
        sa.Column('difficulty', sa.Integer()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )


    # user_memories
    op.create_table(
        'user_memories',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('memory_key', sa.String(length=100), nullable=False),
        sa.Column('memory_value', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=50)),
        sa.Column('confidence', sa.Float()),
        sa.Column('status', sa.String(length=20)),
        sa.Column('is_locked', sa.Integer()),
        sa.Column('source_conversation_id', sa.Integer(), sa.ForeignKey('chat_conversations.id', ondelete='SET NULL')),
        sa.Column('source_type', sa.String(length=50)),
        sa.Column('source_id', sa.String(length=100)),
        sa.Column('evidence', sa.Text()),
        sa.Column('expires_at', sa.DateTime()),
        sa.Column('review_status', sa.String(length=20)),
        sa.Column('material_id', sa.Integer()),
        sa.Column('memory_type', sa.String(length=20)),
        sa.Column('last_seen_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # note_links
    op.create_table(
        'note_links',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('note_id', sa.Integer(), sa.ForeignKey('notes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('link_type', sa.String(length=30), nullable=False),
        sa.Column('link_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # tasks
    op.create_table(
        'tasks',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('goal_id', sa.Integer(), sa.ForeignKey('goals.id'), nullable=False),
        sa.Column('parent_task_id', sa.Integer(), sa.ForeignKey('tasks.id')),
        sa.Column('chapter_id', sa.Integer(), sa.ForeignKey('chapters.id')),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('task_type', sa.String(length=20)),
        sa.Column('planned_date', sa.Date()),
        sa.Column('status', sa.String(length=20)),
        sa.Column('completed_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # wrong_questions
    op.create_table(
        'wrong_questions',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('question_id', sa.Integer(), sa.ForeignKey('questions.id'), nullable=False, unique=True),
        sa.Column('first_wrong_at', sa.DateTime()),
        sa.Column('last_wrong_at', sa.DateTime()),
        sa.Column('wrong_count', sa.Integer()),
        sa.Column('mastery_status', sa.String(length=20)),
        sa.Column('next_review_at', sa.DateTime()),
        sa.Column('review_count', sa.Integer()),
        sa.Column('knowledge_point', sa.String(length=100)),
        sa.Column('recall_difficulty', sa.String(length=20)),
        sa.Column('mastery_score', sa.Float()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )


    # output_evaluations
    op.create_table(
        'output_evaluations',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('tasks.id', ondelete='SET NULL')),
        sa.Column('material_id', sa.Integer(), sa.ForeignKey('materials.id', ondelete='SET NULL')),
        sa.Column('score', sa.Integer()),
        sa.Column('verdict', sa.String(length=30)),
        sa.Column('strengths', sa.Text()),
        sa.Column('gaps', sa.Text()),
        sa.Column('next_actions', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # study_sessions
    op.create_table(
        'study_sessions',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('chapter_id', sa.Integer(), sa.ForeignKey('chapters.id')),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('tasks.id')),
        sa.Column('session_type', sa.String(length=20)),
        sa.Column('started_at', sa.DateTime()),
        sa.Column('ended_at', sa.DateTime()),
        sa.Column('summary', sa.Text()),
        sa.Column('ai_feedback', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # conversations
    op.create_table(
        'conversations',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('study_sessions.id'), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('message_type', sa.String(length=20)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # pomodoros
    op.create_table(
        'pomodoros',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('study_sessions.id')),
        sa.Column('chapter_id', sa.Integer(), sa.ForeignKey('chapters.id')),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('tasks.id')),
        sa.Column('started_at', sa.DateTime()),
        sa.Column('ended_at', sa.DateTime()),
        sa.Column('task_name', sa.String(length=200)),
        sa.Column('duration', sa.Float(), nullable=False),
        sa.Column('completed', sa.Boolean(), nullable=False),
        sa.Column('stop_reason', sa.String(length=20)),
        sa.Column('note', sa.Text()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


    # quiz_records
    op.create_table(
        'quiz_records',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('question_id', sa.Integer(), sa.ForeignKey('questions.id'), nullable=False),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('study_sessions.id')),
        sa.Column('user_answer', sa.Text()),
        sa.Column('is_correct', sa.Boolean()),
        sa.Column('time_spent', sa.Integer()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )


    # v1.3.0 indexes, including the unique indexes declared by users.
    op.create_index('ix_agent_execution_logs_agent', 'agent_execution_logs', ['agent'], unique=False)
    op.create_index('ix_agent_execution_logs_created_at', 'agent_execution_logs', ['created_at'], unique=False)
    op.create_index('ix_agent_execution_logs_job_id', 'agent_execution_logs', ['job_id'], unique=False)
    op.create_index('ix_agent_execution_logs_user_id', 'agent_execution_logs', ['user_id'], unique=False)
    op.create_index('ix_agent_jobs_agent', 'agent_jobs', ['agent'], unique=False)
    op.create_index('ix_agent_jobs_created_at', 'agent_jobs', ['created_at'], unique=False)
    op.create_index('ix_agent_jobs_status', 'agent_jobs', ['status'], unique=False)
    op.create_index('ix_agent_jobs_user_id', 'agent_jobs', ['user_id'], unique=False)
    op.create_index('ix_learning_events_dedupe_key', 'learning_events', ['dedupe_key'], unique=False)
    op.create_index('ix_learning_events_user_type_time', 'learning_events', ['user_id', 'event_type', 'timestamp'], unique=False)
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.create_index('ix_users_username', 'users', ['username'], unique=True)
    op.create_index('ix_anki_cards_due_at', 'anki_cards', ['due_at'], unique=False)
    op.create_index('ix_anki_cards_source', 'anki_cards', ['source'], unique=False)
    op.create_index('ix_anki_cards_user_id', 'anki_cards', ['user_id'], unique=False)
    op.create_index('ix_chat_projects_user_id', 'chat_projects', ['user_id'], unique=False)
    op.create_index('ix_coach_events_dedupe_key', 'coach_events', ['dedupe_key'], unique=False)

    op.create_index('ix_coach_events_event_type', 'coach_events', ['event_type'], unique=False)
    op.create_index('ix_coach_events_occurred_at', 'coach_events', ['occurred_at'], unique=False)
    op.create_index('ix_coach_events_user_id', 'coach_events', ['user_id'], unique=False)
    op.create_index('ix_coach_nudges_event_id', 'coach_nudges', ['event_id'], unique=False)
    op.create_index('ix_coach_nudges_skill_id', 'coach_nudges', ['skill_id'], unique=False)
    op.create_index('ix_coach_nudges_status', 'coach_nudges', ['status'], unique=False)
    op.create_index('ix_coach_nudges_user_id', 'coach_nudges', ['user_id'], unique=False)
    op.create_index('ix_coach_skill_stats_channel', 'coach_skill_stats', ['channel'], unique=False)
    op.create_index('ix_coach_skill_stats_event_type', 'coach_skill_stats', ['event_type'], unique=False)
    op.create_index('ix_coach_skill_stats_skill_id', 'coach_skill_stats', ['skill_id'], unique=False)
    op.create_index('ix_coach_skill_stats_user_id', 'coach_skill_stats', ['user_id'], unique=False)
    op.create_index('ix_coach_workflows_last_event_id', 'coach_workflows', ['last_event_id'], unique=False)
    op.create_index('ix_coach_workflows_started_at', 'coach_workflows', ['started_at'], unique=False)
    op.create_index('ix_coach_workflows_status', 'coach_workflows', ['status'], unique=False)
    op.create_index('ix_coach_workflows_user_id', 'coach_workflows', ['user_id'], unique=False)
    op.create_index('ix_coach_workflows_workflow_type', 'coach_workflows', ['workflow_type'], unique=False)
    op.create_index('ix_daily_plans_user_id', 'daily_plans', ['user_id'], unique=False)

    op.create_index('ix_daily_stats_user_id', 'daily_stats', ['user_id'], unique=False)
    op.create_index('ix_materials_content_hash', 'materials', ['content_hash'], unique=False)
    op.create_index('ix_materials_file_hash', 'materials', ['file_hash'], unique=False)
    op.create_index('ix_materials_user_id', 'materials', ['user_id'], unique=False)
    op.create_index('ix_motivation_quotes_user_id', 'motivation_quotes', ['user_id'], unique=False)
    op.create_index('ix_prompt_templates_user_id', 'prompt_templates', ['user_id'], unique=False)
    op.create_index('ix_review_schedule_scheduled_date', 'review_schedule', ['scheduled_date'], unique=False)
    op.create_index('ix_review_schedule_status', 'review_schedule', ['status'], unique=False)
    op.create_index('ix_review_schedule_user_id', 'review_schedule', ['user_id'], unique=False)
    op.create_index('ix_web_search_cache_expires_at', 'web_search_cache', ['expires_at'], unique=False)
    op.create_index('ix_web_search_cache_query_hash', 'web_search_cache', ['query_hash'], unique=False)
    op.create_index('ix_web_search_cache_user_id', 'web_search_cache', ['user_id'], unique=False)
    op.create_index('ix_chapters_material_id', 'chapters', ['material_id'], unique=False)
    op.create_index('ix_chat_conversations_project_id', 'chat_conversations', ['project_id'], unique=False)
    op.create_index('ix_chat_conversations_user_id', 'chat_conversations', ['user_id'], unique=False)
    op.create_index('ix_motivation_settings_user_id', 'motivation_settings', ['user_id'], unique=True)
    op.create_index('ix_chat_messages_conversation_id', 'chat_messages', ['conversation_id'], unique=False)

    op.create_index('ix_conversation_summaries_conversation_id', 'conversation_summaries', ['conversation_id'], unique=False)
    op.create_index('ix_conversation_summaries_user_id', 'conversation_summaries', ['user_id'], unique=False)
    op.create_index('ix_goals_status', 'goals', ['status'], unique=False)
    op.create_index('ix_goals_user_id', 'goals', ['user_id'], unique=False)
    op.create_index('ix_questions_chapter_id', 'questions', ['chapter_id'], unique=False)
    op.create_index('ix_questions_user_id', 'questions', ['user_id'], unique=False)
    op.create_index('ix_user_memories_memory_key', 'user_memories', ['memory_key'], unique=False)
    op.create_index('ix_user_memories_review_status', 'user_memories', ['review_status'], unique=False)
    op.create_index('ix_user_memories_status', 'user_memories', ['status'], unique=False)
    op.create_index('ix_user_memories_user_id', 'user_memories', ['user_id'], unique=False)
    op.create_index('ix_tasks_goal_id', 'tasks', ['goal_id'], unique=False)
    op.create_index('ix_tasks_parent_task_id', 'tasks', ['parent_task_id'], unique=False)
    op.create_index('ix_tasks_planned_date', 'tasks', ['planned_date'], unique=False)
    op.create_index('ix_tasks_status', 'tasks', ['status'], unique=False)
    op.create_index('ix_wrong_questions_next_review_at', 'wrong_questions', ['next_review_at'], unique=False)
    op.create_index('ix_wrong_questions_user_id', 'wrong_questions', ['user_id'], unique=False)
    op.create_index('ix_pomodoros_user_id', 'pomodoros', ['user_id'], unique=False)



def downgrade() -> None:
    """This compatibility baseline cannot safely distinguish legacy tables."""
    raise NotImplementedError(
        "The v1.3 baseline is intentionally irreversible because it may adopt legacy tables."
    )
