"""Stable identity for online/offline timers and explicit historical time provenance."""
from alembic import op
import sqlalchemy as sa

revision = "20260925_26"
down_revision = "20260925_25"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pomodoros", sa.Column("client_record_id", sa.String(100), nullable=True))
    op.add_column("pomodoros", sa.Column("time_basis", sa.String(20), nullable=False, server_default="legacy"))
    op.create_index("uq_pomodoro_user_client", "pomodoros", ["user_id", "client_record_id"], unique=True)


def downgrade():
    op.drop_index("uq_pomodoro_user_client", table_name="pomodoros")
    op.drop_column("pomodoros", "time_basis")
    op.drop_column("pomodoros", "client_record_id")
