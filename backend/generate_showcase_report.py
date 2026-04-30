"""一键生成合成用户展示报告（无需逐个手动登录）

功能：
- 自动发现 synthetic_* 用户
- 调用真实后端接口（通过 TestClient）获取 EDA 报告与干预建议
- 输出 Markdown / CSV / JSON 三份文件，便于简历与面试展示

用法：
    python generate_showcase_report.py --days 60
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.main import app

DB_PATH = "E:/xyleisure/StudyAssitant/data/study.db"
OUTPUT_DIR = Path("E:/xyleisure/StudyAssitant/backend/demo_outputs")


def fetch_synthetic_users(limit: int = 12) -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT username FROM users WHERE username LIKE 'synthetic_%' ORDER BY username LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [str(r[0]) for r in rows]


def login_token(client: TestClient, username: str, password: str = "test123") -> str | None:
    resp = client.post("/api/auth/login", data={"username": username, "password": password})
    if resp.status_code != 200:
        return None
    return resp.json().get("access_token")


def summarize_user_payload(username: str, eda: dict[str, Any], intervention: dict[str, Any]) -> dict[str, Any]:
    summary = eda.get("summary", {}) or {}
    profile = eda.get("profile", {}) or {}
    recommendations = eda.get("recommendations", []) or []

    return {
        "username": username,
        "profile_type": profile.get("profile_type", "未知"),
        "profile_confidence": round(float(profile.get("confidence", 0.0)) * 100, 1),
        "best_study_window": profile.get("best_study_window", "-"),
        "total_minutes": summary.get("total_minutes", 0),
        "avg_daily_minutes": summary.get("avg_daily_minutes", 0),
        "completion_rate": summary.get("completion_rate", 0),
        "active_days": summary.get("active_days", 0),
        "task_progress": f"{summary.get('completed_tasks', 0)}/{summary.get('total_tasks', 0)}",
        "risk_level": intervention.get("risk_level", "unknown"),
        "should_push": intervention.get("should_push", False),
        "intervention_title": intervention.get("push_title", ""),
        "recommendation_top1": recommendations[0] if recommendations else "",
    }


def generate(days: int, limit: int) -> tuple[Path, Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = OUTPUT_DIR / f"showcase_{ts}.md"
    csv_path = OUTPUT_DIR / f"showcase_{ts}.csv"
    json_path = OUTPUT_DIR / f"showcase_{ts}.json"

    users = fetch_synthetic_users(limit=limit)
    if not users:
        raise RuntimeError("未找到 synthetic_* 用户，请先执行 seed_data.py")

    rows: list[dict[str, Any]] = []
    raw_payloads: list[dict[str, Any]] = []
    client = TestClient(app)

    for username in users:
        token = login_token(client, username)
        if not token:
            continue
        headers = {"Authorization": f"Bearer {token}"}
        eda_resp = client.get(f"/api/analytics/eda-report?days={days}", headers=headers)
        intervention_resp = client.get("/api/interventions/daily", headers=headers)
        if eda_resp.status_code != 200 or intervention_resp.status_code != 200:
            continue

        eda = eda_resp.json()
        intervention = intervention_resp.json()
        rows.append(summarize_user_payload(username, eda, intervention))
        raw_payloads.append({
            "username": username,
            "eda": eda,
            "intervention": intervention,
        })

    if not rows:
        raise RuntimeError("没有可用展示数据，请确认 synthetic 用户可登录且接口可访问")

    # CSV
    fieldnames = list(rows[0].keys())
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # JSON
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(raw_payloads, f, ensure_ascii=False, indent=2)

    # Markdown（适合直接截图）
    lines: list[str] = []
    lines.append(f"# 学习系统多用户画像展示（{days}天）")
    lines.append("")
    lines.append(f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"- 用户数：{len(rows)}")
    lines.append("")
    lines.append("## 用户画像对比总览")
    lines.append("")
    lines.append("| 用户 | 画像类型 | 置信度 | 最佳窗口 | 日均分钟 | 完成率 | 活跃天数 | 风险等级 |")
    lines.append("|---|---|---:|---|---:|---:|---:|---|")
    for r in rows:
        lines.append(
            f"| {r['username']} | {r['profile_type']} | {r['profile_confidence']}% | {r['best_study_window']} | {r['avg_daily_minutes']} | {r['completion_rate']}% | {r['active_days']} | {r['risk_level']} |"
        )

    lines.append("")
    lines.append("## 个性化建议样例")
    lines.append("")
    for r in rows:
        lines.append(f"- **{r['username']}**（{r['profile_type']}）: {r['recommendation_top1']}")

    lines.append("")
    lines.append("## 系统独特性可展示点")
    lines.append("")
    lines.append("- 能识别不同学习节律（晨间高效/夜间高效/间歇突击等）")
    lines.append("- 能按用户行为给出差异化干预建议（不同风险等级、不同动作）")
    lines.append("- 支持从原始行为数据到可视化报告的一键闭环")

    md_path.write_text("\n".join(lines), encoding="utf-8")

    return md_path, csv_path, json_path


def main() -> None:
    parser = argparse.ArgumentParser(description="生成多用户画像展示报告")
    parser.add_argument("--days", type=int, default=60, help="统计天数，默认60")
    parser.add_argument("--limit", type=int, default=10, help="最多读取多少 synthetic 用户")
    args = parser.parse_args()

    days = max(30, args.days)
    limit = max(1, min(20, args.limit))

    md_path, csv_path, json_path = generate(days=days, limit=limit)
    print("\n✅ 展示报告已生成：")
    print(f"- Markdown: {md_path}")
    print(f"- CSV:      {csv_path}")
    print(f"- JSON:     {json_path}")


if __name__ == "__main__":
    main()
