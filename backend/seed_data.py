"""多用户学习行为测试数据生成脚本

目标：
- 生成 5~10 个测试用户（默认 8 个）
- 每个用户生成 >= 30 天数据（默认 60 天）
- 用户行为风格可区分（晨型/夜型/周末冲刺/间歇突击等）
- 覆盖 pomodoros / goals / tasks / review_schedule，便于端到端验证 EDA 与个性化建议

使用方式：
    python seed_data.py --users 8 --days 60
"""

from __future__ import annotations

import argparse
import random
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import bcrypt

DB_PATH = "E:/xyleisure/StudyAssitant/data/study.db"


@dataclass
class ProfileSpec:
    key: str
    display_name: str
    hour_weights: dict[int, float]
    study_day_ratio: float
    peak_completion: float
    off_completion: float
    daily_sessions_min: int
    daily_sessions_max: int
    task_completion_base: float
    review_due_pressure: float


PROFILES: list[ProfileSpec] = [
    ProfileSpec(
        key="morning_strategist",
        display_name="晨间规划型",
        hour_weights={6: 1.5, 7: 2.4, 8: 3.8, 9: 5.2, 10: 5.0, 11: 3.8, 14: 1.2, 15: 1.1, 20: 0.4},
        study_day_ratio=0.84,
        peak_completion=0.93,
        off_completion=0.72,
        daily_sessions_min=4,
        daily_sessions_max=8,
        task_completion_base=0.76,
        review_due_pressure=0.35,
    ),
    ProfileSpec(
        key="night_owl",
        display_name="夜间高效型",
        hour_weights={8: 0.6, 10: 0.9, 14: 1.1, 19: 2.4, 20: 3.4, 21: 4.8, 22: 5.3, 23: 4.2},
        study_day_ratio=0.72,
        peak_completion=0.91,
        off_completion=0.60,
        daily_sessions_min=3,
        daily_sessions_max=7,
        task_completion_base=0.62,
        review_due_pressure=0.48,
    ),
    ProfileSpec(
        key="daytime_steady",
        display_name="白天稳态型",
        hour_weights={8: 1.2, 9: 2.0, 10: 2.6, 11: 2.4, 13: 2.3, 14: 2.5, 15: 2.2, 16: 1.9, 20: 0.7},
        study_day_ratio=0.80,
        peak_completion=0.88,
        off_completion=0.70,
        daily_sessions_min=4,
        daily_sessions_max=7,
        task_completion_base=0.70,
        review_due_pressure=0.40,
    ),
    ProfileSpec(
        key="weekend_sprinter",
        display_name="周末冲刺型",
        hour_weights={9: 0.8, 11: 0.9, 14: 1.2, 16: 1.0, 19: 1.4, 21: 1.8},
        study_day_ratio=0.58,
        peak_completion=0.85,
        off_completion=0.55,
        daily_sessions_min=2,
        daily_sessions_max=6,
        task_completion_base=0.52,
        review_due_pressure=0.70,
    ),
    ProfileSpec(
        key="fragmented",
        display_name="间歇突击型",
        hour_weights={7: 0.9, 10: 1.2, 13: 1.0, 15: 1.4, 18: 1.5, 20: 1.6, 22: 1.2},
        study_day_ratio=0.45,
        peak_completion=0.72,
        off_completion=0.46,
        daily_sessions_min=1,
        daily_sessions_max=5,
        task_completion_base=0.40,
        review_due_pressure=0.78,
    ),
    ProfileSpec(
        key="high_intensity",
        display_name="高强度稳定型",
        hour_weights={6: 0.8, 8: 2.2, 9: 2.6, 10: 2.5, 14: 2.0, 15: 2.1, 19: 1.8, 21: 1.2},
        study_day_ratio=0.88,
        peak_completion=0.94,
        off_completion=0.78,
        daily_sessions_min=5,
        daily_sessions_max=10,
        task_completion_base=0.80,
        review_due_pressure=0.30,
    ),
    ProfileSpec(
        key="exam_crammer",
        display_name="考前爆发型",
        hour_weights={9: 0.7, 11: 0.8, 13: 1.0, 16: 1.3, 20: 2.2, 21: 2.8, 22: 2.6},
        study_day_ratio=0.60,
        peak_completion=0.86,
        off_completion=0.52,
        daily_sessions_min=2,
        daily_sessions_max=7,
        task_completion_base=0.56,
        review_due_pressure=0.64,
    ),
    ProfileSpec(
        key="balanced_explorer",
        display_name="均衡探索型",
        hour_weights={7: 1.0, 9: 1.6, 11: 1.5, 14: 1.7, 16: 1.6, 19: 1.5, 21: 1.4},
        study_day_ratio=0.75,
        peak_completion=0.87,
        off_completion=0.68,
        daily_sessions_min=3,
        daily_sessions_max=7,
        task_completion_base=0.66,
        review_due_pressure=0.44,
    ),
]


def pick_hour(weights: dict[int, float]) -> int:
    hours = list(weights.keys())
    probs = [weights[h] for h in hours]
    return random.choices(hours, weights=probs, k=1)[0]


def peak_hours_from_weights(weights: dict[int, float]) -> set[int]:
    sorted_items = sorted(weights.items(), key=lambda x: x[1], reverse=True)
    return {h for h, _ in sorted_items[:4]}


def build_profiles(target_users: int) -> list[ProfileSpec]:
    if target_users <= len(PROFILES):
        return PROFILES[:target_users]
    out = PROFILES.copy()
    while len(out) < target_users:
        out.append(PROFILES[len(out) % len(PROFILES)])
    return out


def ensure_user(cur: sqlite3.Cursor, username: str, email: str, hashed_pw: str, created_at: str) -> int:
    row = cur.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if row:
        user_id = int(row[0])
        cur.execute(
            "UPDATE users SET email = ?, hashed_password = ?, is_active = 1 WHERE id = ?",
            (email, hashed_pw, user_id),
        )
        return user_id
    cur.execute(
        "INSERT INTO users (username, email, hashed_password, is_active, created_at) VALUES (?, ?, ?, 1, ?)",
        (username, email, hashed_pw, created_at),
    )
    new_id = cur.lastrowid
    if new_id is None:
        raise RuntimeError("创建用户失败：lastrowid 为空")
    return int(new_id)


def cleanup_user_data(cur: sqlite3.Cursor, user_id: int) -> None:
    goal_rows = cur.execute("SELECT id FROM goals WHERE user_id = ?", (user_id,)).fetchall()
    goal_ids = [int(r[0]) for r in goal_rows]
    if goal_ids:
        placeholders = ",".join("?" for _ in goal_ids)
        cur.execute(f"DELETE FROM tasks WHERE goal_id IN ({placeholders})", tuple(goal_ids))
    cur.execute("DELETE FROM goals WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM pomodoros WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM review_schedule WHERE user_id = ?", (user_id,))


def create_goals(cur: sqlite3.Cursor, user_id: int, today: date) -> list[int]:
    goals = [
        ("阶段一：核心知识巩固", "打牢核心概念并构建知识图谱", "active", today + timedelta(days=45)),
        ("阶段二：应用与真题训练", "通过高频题型提升输出能力", "active", today + timedelta(days=75)),
    ]
    goal_ids: list[int] = []
    for title, desc, status, deadline in goals:
        cur.execute(
            """INSERT INTO goals (user_id, title, description, status, deadline, plan_total_days, plan_study_days_per_week, plan_start_date, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                title,
                desc,
                status,
                deadline.isoformat(),
                90,
                5,
                (today - timedelta(days=30)).isoformat(),
                datetime.now().isoformat(),
                datetime.now().isoformat(),
            ),
        )
        goal_id = cur.lastrowid
        if goal_id is None:
            raise RuntimeError("创建目标失败：lastrowid 为空")
        goal_ids.append(int(goal_id))
    return goal_ids


def seed_tasks_and_reviews(
    cur: sqlite3.Cursor,
    *,
    user_id: int,
    goal_ids: list[int],
    start_date: date,
    days: int,
    task_completion_base: float,
    review_due_pressure: float,
) -> tuple[int, int, int]:
    task_types = ["learn", "review", "practice", "summarize"]
    task_templates = [
        "完成章节精读",
        "做 10 题练习",
        "输出费曼笔记",
        "整理错题并复盘",
        "复习记忆卡片",
    ]

    task_count = 0
    completed_task_count = 0
    review_count = 0

    for i in range(days):
        d = start_date + timedelta(days=i)
        daily_task_num = random.randint(2, 4)
        for _ in range(daily_task_num):
            goal_id = random.choice(goal_ids)
            task_type = random.choice(task_types)
            title = f"{random.choice(task_templates)}（{d.isoformat()}）"
            status = "completed" if random.random() < task_completion_base else random.choice(["pending", "in_progress"])
            completed_at = (
                datetime(d.year, d.month, d.day, random.randint(19, 23), random.randint(0, 59)).isoformat()
                if status == "completed" else None
            )
            cur.execute(
                """INSERT INTO tasks (goal_id, title, description, task_type, planned_date, status, completed_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    goal_id,
                    title,
                    f"自动生成的测试任务，用户{user_id}，类型{task_type}",
                    task_type,
                    d.isoformat(),
                    status,
                    completed_at,
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ),
            )
            task_count += 1
            if status == "completed":
                completed_task_count += 1

        # 复习计划：控制一部分 overdue 来触发干预分析
        if random.random() < 0.72:
            scheduled = datetime(d.year, d.month, d.day, random.randint(7, 22), random.randint(0, 59))
            overdue_bias = random.random() < review_due_pressure
            if overdue_bias:
                scheduled = scheduled - timedelta(days=random.randint(1, 5))
            status = "pending" if random.random() < 0.65 else random.choice(["completed", "skipped"])
            cur.execute(
                """INSERT INTO review_schedule (user_id, item_type, item_id, scheduled_date, interval_days, ease_factor, repetitions, last_quality, status, completed_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    random.choice(["chapter", "question"]),
                    random.randint(1, 300),
                    scheduled.isoformat(),
                    random.choice([1, 2, 3, 5, 7]),
                    random.choice([2, 3, 4]),
                    random.randint(0, 8),
                    random.randint(1, 5),
                    status,
                    datetime.now().isoformat() if status == "completed" else None,
                    datetime.now().isoformat(),
                ),
            )
            review_count += 1

    return task_count, completed_task_count, review_count


def seed_pomodoros(
    cur: sqlite3.Cursor,
    *,
    user_id: int,
    profile: ProfileSpec,
    start_date: date,
    days: int,
) -> tuple[int, int, int]:
    peak_hours = peak_hours_from_weights(profile.hour_weights)
    study_days_target = max(30, int(days * profile.study_day_ratio))
    all_days = [start_date + timedelta(days=i) for i in range(days)]
    study_days = sorted(random.sample(all_days, min(study_days_target, len(all_days))))

    pomodoro_count = 0
    completed_count = 0
    distracted_count = 0

    for d in study_days:
        # 周末冲刺型：周末学习密度更高
        if profile.key == "weekend_sprinter":
            if d.weekday() >= 5:
                daily_sessions = random.randint(profile.daily_sessions_max - 1, profile.daily_sessions_max + 2)
            else:
                daily_sessions = random.randint(1, max(2, profile.daily_sessions_min))
        # 考前爆发型：最后 10 天学习密度大增
        elif profile.key == "exam_crammer":
            if d >= (start_date + timedelta(days=days - 10)):
                daily_sessions = random.randint(profile.daily_sessions_max, profile.daily_sessions_max + 3)
            else:
                daily_sessions = random.randint(max(1, profile.daily_sessions_min - 1), profile.daily_sessions_max - 2)
        else:
            daily_sessions = random.randint(profile.daily_sessions_min, profile.daily_sessions_max)

        for _ in range(max(1, daily_sessions)):
            hour = pick_hour(profile.hour_weights)
            minute = random.randint(0, 55)
            started = datetime(d.year, d.month, d.day, hour, minute)

            duration = random.choice([20, 25, 25, 25, 30, 35, 45, 50])
            is_peak = hour in peak_hours
            completion_prob = profile.peak_completion if is_peak else profile.off_completion
            if profile.key == "fragmented":
                completion_prob *= 0.82
            if profile.key == "high_intensity" and is_peak:
                completion_prob = min(0.97, completion_prob + 0.03)

            completed = random.random() < completion_prob
            if completed:
                ended = started + timedelta(minutes=duration)
                stop_reason = "early_done"
                completed_count += 1
            else:
                actual = random.randint(8, max(12, duration - 2))
                ended = started + timedelta(minutes=actual)
                stop_reason = random.choices(
                    ["distracted", "interrupted", "early_done"],
                    weights=[0.55, 0.35, 0.10] if not is_peak else [0.35, 0.45, 0.20],
                    k=1,
                )[0]
                if stop_reason == "distracted":
                    distracted_count += 1

            cur.execute(
                """INSERT INTO pomodoros
                   (user_id, task_name, started_at, ended_at, duration, completed, stop_reason, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    f"{profile.display_name}·学习单元",
                    started.isoformat(),
                    ended.isoformat(),
                    float(duration),
                    1 if completed else 0,
                    stop_reason,
                    f"profile={profile.key}",
                    started.isoformat(),
                ),
            )
            pomodoro_count += 1

    return pomodoro_count, completed_count, distracted_count


def run_seed(users: int, days: int, seed: int) -> None:
    random.seed(seed)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    hashed_pw = bcrypt.hashpw(b"test123", bcrypt.gensalt()).decode("utf-8")
    today = date.today()
    start_date = today - timedelta(days=days - 1)

    selected_profiles = build_profiles(users)
    print(f"\n[Seed] users={users}, days={days}, start={start_date.isoformat()}, db={DB_PATH}")

    for idx, profile in enumerate(selected_profiles, start=1):
        username = f"synthetic_{profile.key}_{idx}"
        email = f"{username}@study.test"
        created_at = (datetime.now() - timedelta(days=days + 7)).isoformat()

        user_id = ensure_user(cur, username, email, hashed_pw, created_at)
        cleanup_user_data(cur, user_id)
        goal_ids = create_goals(cur, user_id, today)

        task_count, completed_task_count, review_count = seed_tasks_and_reviews(
            cur,
            user_id=user_id,
            goal_ids=goal_ids,
            start_date=start_date,
            days=days,
            task_completion_base=profile.task_completion_base,
            review_due_pressure=profile.review_due_pressure,
        )

        pomodoro_count, completed_pomodoro_count, distracted_count = seed_pomodoros(
            cur,
            user_id=user_id,
            profile=profile,
            start_date=start_date,
            days=days,
        )

        completion_rate = (completed_pomodoro_count / pomodoro_count * 100) if pomodoro_count else 0.0
        print(f"- {username:<30} | {profile.display_name:<10} | pomodoro={pomodoro_count:<4} 完成率={completion_rate:>5.1f}% | tasks={completed_task_count}/{task_count} | review={review_count:<3} | distracted={distracted_count}")

    conn.commit()
    conn.close()

    print("\n✅ 测试数据生成完成（默认密码：test123）")
    print("建议：登录 synthetic_* 账号进入 /eda 与 /intervention 查看画像差异与建议输出。")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成学习系统多用户差异化测试数据")
    parser.add_argument("--users", type=int, default=8, help="用户数量（建议 5~10）")
    parser.add_argument("--days", type=int, default=60, help="每个用户生成天数（>=30）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子，便于复现")
    args = parser.parse_args()

    users = max(5, min(10, args.users))
    days = max(30, args.days)
    run_seed(users=users, days=days, seed=args.seed)


if __name__ == "__main__":
    main()
