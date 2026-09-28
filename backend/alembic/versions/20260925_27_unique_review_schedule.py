"""Audit and consolidate duplicate review schedules before enforcing identity."""
from alembic import op
import sqlalchemy as sa

revision = "20260925_27"
down_revision = "20260925_26"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("review_schedule_merge_audit",
        sa.Column("original_id", sa.Integer(), primary_key=True),
        sa.Column("kept_id", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False))
    if op.get_context().as_sql:
        # Offline PostgreSQL upgrades must retain the same historical audit.
        op.execute("""INSERT INTO review_schedule_merge_audit (original_id, kept_id, snapshot)
            SELECT id, kept_id, snapshot FROM (
              SELECT id, to_jsonb(r) AS snapshot,
                first_value(id) OVER w AS kept_id, count(*) OVER (PARTITION BY user_id,item_type,item_id) AS n
              FROM review_schedule r WINDOW w AS (PARTITION BY user_id,item_type,item_id
                ORDER BY COALESCE(last_review_at,completed_at,'0001-01-01'::timestamp) DESC,
                         COALESCE(repetitions,0) DESC,id DESC)
            ) ranked WHERE n > 1""")
        op.execute("""UPDATE review_schedule r SET repetitions=g.repetitions,is_archived=g.archived
            FROM (SELECT kept_id,MAX(COALESCE((snapshot->>'repetitions')::integer,0)) AS repetitions,
                         bool_or(COALESCE((snapshot->>'is_archived')::boolean,false)) AS archived
                  FROM review_schedule_merge_audit GROUP BY kept_id) g WHERE r.id=g.kept_id""")
        op.execute("DELETE FROM review_schedule WHERE id IN (SELECT original_id FROM review_schedule_merge_audit WHERE original_id<>kept_id)")
    else:
        from schema_repairs.review_schedules_v1 import merge_duplicate_schedules
        merge_duplicate_schedules(op.get_bind())
    op.create_index("uq_review_schedule_user_item", "review_schedule", ["user_id", "item_type", "item_id"], unique=True)


def downgrade():
    raise RuntimeError("Review schedule consolidation is forward-only; restore a pre-upgrade backup to downgrade safely.")
