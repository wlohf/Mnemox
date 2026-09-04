#!/usr/bin/env python3
"""Preview or apply secret-safe cleanup of historical diagnostic columns.

Examples:
    python sanitize_diagnostics.py
    python sanitize_diagnostics.py --apply --batch-size 500
"""
from __future__ import annotations

import argparse
import asyncio
import json

from app.database import async_session_maker
from app.services.diagnostic_maintenance_service import sanitize_persisted_diagnostics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="提交清理结果；省略时仅预览统计并回滚",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=250,
        help="每批读取和 flush 的最大行数（1-5000，默认 250）",
    )
    return parser


async def run(*, apply: bool, batch_size: int) -> dict:
    async with async_session_maker() as db:
        report = await sanitize_persisted_diagnostics(
            db,
            dry_run=not apply,
            batch_size=batch_size,
        )
        if apply:
            await db.commit()
        else:
            await db.rollback()
        return report.as_dict()


def main() -> None:
    args = build_parser().parse_args()
    report = asyncio.run(run(apply=bool(args.apply), batch_size=int(args.batch_size)))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
