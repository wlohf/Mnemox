"""Add fenced extraction leases and source-free execution-day call accounting.

Revision ID: 20260912_24
Revises: 20260912_23
"""
from alembic import op
import sqlalchemy as sa

revision = '20260912_24'
down_revision = '20260912_23'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('knowledge_extraction_runs', sa.Column('lease_token', sa.String(36), nullable=True))
    op.add_column('knowledge_extraction_runs', sa.Column('lease_expires_at', sa.DateTime(), nullable=True))
    op.add_column('knowledge_extraction_runs', sa.Column('budget_review_required', sa.Boolean(), nullable=False, server_default=sa.false()))
    # Legacy usage cannot identify execution days or unconfirmed in-flight calls.
    # Preserve everything; only an operator-verified accounting backfill can unblock it.
    op.execute("UPDATE knowledge_extraction_runs SET budget_review_required = true WHERE extractor_type = 'llm'")
    op.create_table(
        'knowledge_extraction_daily_budgets',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('execution_day', sa.Date(), nullable=False),
        sa.Column('charged_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'execution_day', name='uq_extraction_daily_budget_user_day'),
        sa.CheckConstraint('charged_tokens >= 0', name='ck_extraction_daily_budget_charged_tokens'),
    )
    op.create_index('ix_knowledge_extraction_daily_budgets_user_id', 'knowledge_extraction_daily_budgets', ['user_id'])
    op.create_table(
        'knowledge_extraction_calls',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('unit_id', sa.Integer(), nullable=True),
        sa.Column('lease_token', sa.String(36), nullable=False),
        sa.Column('execution_day', sa.Date(), nullable=False),
        sa.Column('estimated_tokens', sa.Integer(), nullable=False),
        sa.Column('charged_tokens', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(20), nullable=False, server_default='reserved'),
        sa.Column('usage', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('provider', sa.String(80), nullable=True),
        sa.Column('model', sa.String(120), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['run_id'], ['knowledge_extraction_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['unit_id'], ['knowledge_units.id'], ondelete='SET NULL'),
        sa.CheckConstraint('estimated_tokens > 0', name='ck_extraction_call_estimated_tokens'),
        sa.CheckConstraint('charged_tokens >= estimated_tokens', name='ck_extraction_call_charged_tokens'),
        sa.CheckConstraint("state IN ('reserved', 'succeeded', 'failed', 'unknown')", name='ck_extraction_call_state'),
    )
    op.create_index('ix_extraction_calls_run', 'knowledge_extraction_calls', ['run_id'])
    op.create_index('ix_extraction_calls_user_day', 'knowledge_extraction_calls', ['user_id', 'execution_day'])
    op.create_index('ix_knowledge_extraction_calls_user_id', 'knowledge_extraction_calls', ['user_id'])
    op.create_index('ix_knowledge_extraction_calls_unit_id', 'knowledge_extraction_calls', ['unit_id'])


def downgrade():
    op.drop_table('knowledge_extraction_calls')
    op.drop_table('knowledge_extraction_daily_budgets')
    op.drop_column('knowledge_extraction_runs', 'budget_review_required')
    op.drop_column('knowledge_extraction_runs', 'lease_expires_at')
    op.drop_column('knowledge_extraction_runs', 'lease_token')
