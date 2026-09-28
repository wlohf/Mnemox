"""Preserve planned/actual focus duration and synthetic-record provenance.

Historical duration is deliberately not copied into actual_duration: it may
still be the timer's original plan. No historical timestamps are rewritten.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260928_29"
down_revision = "20260925_28"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pomodoros", sa.Column("planned_duration", sa.Float(), nullable=True))
    op.add_column("pomodoros", sa.Column("actual_duration", sa.Float(), nullable=True))
    op.add_column("pomodoros", sa.Column("record_origin", sa.String(20), nullable=False, server_default="legacy"))


def downgrade():
    op.drop_column("pomodoros", "record_origin")
    op.drop_column("pomodoros", "actual_duration")
    op.drop_column("pomodoros", "planned_duration")
