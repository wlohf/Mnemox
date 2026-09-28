"""Quarantine credentials whose ownership predates explicit provenance."""
from alembic import op
import sqlalchemy as sa

revision = "20260925_25"
down_revision = "20260912_24"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ai_provider_settings", sa.Column(
        "credential_source", sa.String(20), nullable=False, server_default="legacy",
    ))


def downgrade():
    # Quarantined values must never become callable through an older release.
    op.execute("UPDATE ai_provider_settings SET api_key = '' WHERE credential_source <> 'user'")
    op.drop_column("ai_provider_settings", "credential_source")
