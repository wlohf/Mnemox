"""Persist chat progress and distinguish completed from interrupted replies."""
from alembic import op
import sqlalchemy as sa

revision = "20260925_28"
down_revision = "20260925_27"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("chat_turns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("chat_conversations.id", ondelete="CASCADE")),
        sa.Column("study_session_id", sa.Integer(), sa.ForeignKey("study_sessions.id", ondelete="CASCADE")),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    for table, parent, index in (("chat_messages", "conversation_id", "uq_chat_message_turn_role"),
                                  ("conversations", "session_id", "uq_study_message_turn_role")):
        op.add_column(table, sa.Column("turn_id", sa.String(36)))
        op.add_column(table, sa.Column("status", sa.String(20), nullable=False, server_default="completed"))
        op.create_index(index, table, [parent, "turn_id", "role"], unique=True)


def downgrade():
    for table, index in (("chat_messages", "uq_chat_message_turn_role"),
                         ("conversations", "uq_study_message_turn_role")):
        op.drop_index(index, table_name=table)
        op.drop_column(table, "status")
        op.drop_column(table, "turn_id")
    op.drop_table("chat_turns")
