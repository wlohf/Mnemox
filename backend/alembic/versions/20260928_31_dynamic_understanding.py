"""SQL authority for evidence, provisional hypotheses and episode checkpoints."""
from alembic import op
import sqlalchemy as sa
revision = '20260928_31'
down_revision = '20260928_30'
branch_labels = None
depends_on = None


def owner():
    return sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)


def upgrade():
    op.create_table('understanding_preferences',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('analysis_enabled', sa.Boolean(), nullable=False),
        sa.Column('graph_enabled', sa.Boolean(), nullable=False),
        sa.Column('consume_enabled', sa.Boolean(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False))
    op.create_table('understanding_experiences',
        sa.Column('id', sa.String(32), primary_key=True), owner(),
        sa.Column('source_key', sa.String(100), nullable=False),
        sa.Column('source_version', sa.String(64), nullable=False),
        sa.Column('evidence_group', sa.String(100), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('occurred_at', sa.DateTime()), sa.Column('recorded_at', sa.DateTime()),
        sa.Column('first_seen_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('payload', sa.JSON(), nullable=False), sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('excluded', sa.Boolean(), nullable=False), sa.Column('extraction', sa.JSON()),
        sa.Column('graph_group', sa.String(160)), sa.Column('graph_pending', sa.Boolean(), nullable=False),
        sa.UniqueConstraint('user_id', 'source_key', name='uq_understanding_source'))
    op.create_table('behavioral_hypotheses',
        sa.Column('id', sa.String(32), primary_key=True), owner(),
        sa.Column('fingerprint', sa.String(64), nullable=False), sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False), sa.Column('review_status', sa.String(30), nullable=False),
        sa.Column('statement', sa.Text(), nullable=False), sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('assessment', sa.JSON(), nullable=False), sa.Column('discovery_cutoff', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('user_id', 'fingerprint', name='uq_hypothesis_fingerprint'))
    op.create_table('hypothesis_revisions',
        sa.Column('id', sa.Integer(), primary_key=True), owner(),
        sa.Column('hypothesis_id', sa.String(32), sa.ForeignKey('behavioral_hypotheses.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False), sa.Column('reason', sa.String(100), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('hypothesis_id', 'version', name='uq_hypothesis_revision'))
    for table in ('understanding_experiences', 'behavioral_hypotheses', 'hypothesis_revisions'):
        op.create_index('ix_' + table + '_user_id', table, ['user_id'])
    op.create_index('ix_hypothesis_revisions_hypothesis_id', 'hypothesis_revisions', ['hypothesis_id'])


def downgrade():
    for table in ('hypothesis_revisions', 'behavioral_hypotheses', 'understanding_experiences', 'understanding_preferences'):
        op.drop_table(table)
