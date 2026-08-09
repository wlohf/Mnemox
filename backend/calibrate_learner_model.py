"""Generate an aggregate offline learner-model version comparison report."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.database import async_session_maker
from app.services.learner_model_calibration_service import build_database_calibration_report


async def _run(output: Path | None, minimum_cases: int) -> None:
    async with async_session_maker() as session:
        report = await build_database_calibration_report(session, minimum_cases=minimum_cases)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        print(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text + "\n", encoding="utf-8")
    print(f"Calibration report written to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    parser.add_argument("--minimum-cases", type=int, default=50)
    args = parser.parse_args()
    if args.minimum_cases < 1:
        parser.error("--minimum-cases must be positive")
    asyncio.run(_run(args.output, args.minimum_cases))


if __name__ == "__main__":
    main()
