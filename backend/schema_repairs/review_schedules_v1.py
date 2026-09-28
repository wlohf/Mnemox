"""Frozen migration helper v1. Do not change after release; add a new version."""
from collections import defaultdict
from datetime import date, datetime
import sqlalchemy as sa


def merge_duplicate_schedules(conn):
    metadata = sa.MetaData()
    table = sa.Table("review_schedule", metadata, autoload_with=conn)
    audit = sa.Table("review_schedule_merge_audit", metadata, autoload_with=conn)
    groups = defaultdict(list)
    for row in conn.execute(sa.select(table)).mappings():
        groups[(row["user_id"], row["item_type"], row["item_id"])].append(dict(row))
    for rows in groups.values():
        if len(rows) < 2:
            continue
        winner = max(rows, key=lambda r: (
            r.get("last_review_at") or r.get("completed_at") or datetime.min,
            r.get("repetitions") or 0, r["id"],
        ))
        for row in rows:
            payload = {key: value.isoformat() if isinstance(value, (date, datetime)) else value
                       for key, value in row.items()}
            conn.execute(audit.insert().values(original_id=row["id"], kept_id=winner["id"], snapshot=payload))
        conn.execute(table.update().where(table.c.id == winner["id"]).values(
            repetitions=max(r.get("repetitions") or 0 for r in rows),
            is_archived=any(r.get("is_archived") for r in rows),
        ))
        conn.execute(table.delete().where(table.c.id.in_([r["id"] for r in rows if r["id"] != winner["id"]])))
