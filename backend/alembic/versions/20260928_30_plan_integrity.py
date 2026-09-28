"""Version daily plans and retain recoverable user-authored revisions."""
from alembic import op
import sqlalchemy as sa

revision = "20260928_30"
down_revision = "20260928_29"
branch_labels = depends_on = None


def upgrade():
    op.add_column("daily_plans", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.create_table("daily_plan_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("daily_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("plan_id", "version", name="uq_plan_revision"))
    op.create_index("ix_daily_plan_revisions_plan_id", "daily_plan_revisions", ["plan_id"])
    op.create_index("ix_daily_plan_revisions_user_id", "daily_plan_revisions", ["user_id"])


def downgrade():
    op.drop_table("daily_plan_revisions")
    op.drop_column("daily_plans", "version")
