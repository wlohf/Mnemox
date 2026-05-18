import unittest

from app.services.agent_service import _personalize_actions


CONTEXT = {
    "review": {"due_review_count": 4},
    "tasks": {"overdue_task_count": 2, "today_task_count": 1},
    "learning": {"recent_distracted_rate": 0.3},
    "weaknesses": {},
}


def action_for(reason_code: str) -> dict:
    fixtures = {
        "too_long": {
            "id": "review_long",
            "title": "复习一批内容",
            "reason": "到期复习较多",
            "action_type": "review",
            "priority": "high",
            "estimated_minutes": 25,
            "route": "/review",
            "target": {"title": "复习"},
        },
        "too_disruptive": {
            "id": "focus_noise",
            "title": "立刻开始专注",
            "reason": "今天有任务",
            "action_type": "focus",
            "priority": "medium",
            "estimated_minutes": 25,
            "route": "/pomodoro",
            "target": {"title": "任务"},
        },
        "too_easy": {
            "id": "practice_easy",
            "title": "基础练习",
            "reason": "巩固薄弱点",
            "action_type": "practice",
            "priority": "low",
            "estimated_minutes": 10,
            "route": "/wrong-questions",
            "target": {"name": "函数"},
        },
        "already_known": {
            "id": "practice_known",
            "title": "同主题练习",
            "reason": "继续练习",
            "action_type": "practice",
            "priority": "medium",
            "estimated_minutes": 20,
            "route": "/wrong-questions",
            "target": {"name": "已掌握主题"},
        },
        "too_hard": {
            "id": "hard_task",
            "title": "难题专项",
            "reason": "难点突破",
            "action_type": "practice",
            "priority": "high",
            "estimated_minutes": 30,
            "route": "/wrong-questions",
            "target": {"name": "难题"},
        },
        "too_late": {
            "id": "late_rescue",
            "title": "补救过期任务",
            "reason": "有过期任务",
            "action_type": "task",
            "priority": "high",
            "estimated_minutes": 25,
            "route": "/goals",
            "target": {"title": "过期任务"},
        },
    }
    return fixtures[reason_code]


def personalize_single(action: dict, reason_code: str) -> dict:
    target = action.get("target") or {}
    topic = target.get("name") or target.get("title") or ""
    personalization = {
        "avoid_action_ids": [],
        "avoid_action_types": [],
        "avoid_topics": [],
        "recent_feedback": [
            {
                "action_id": action["id"],
                "reason_code": reason_code,
                "outcome_label": "无用",
            }
        ],
        "feedback_stats": {
            "by_reason_code": {reason_code: 1},
            "by_reason_action_type": {reason_code: {action["action_type"]: 1}},
            "by_reason_topic": {reason_code: {topic: 1}},
        },
        "feedback_impacts": [],
    }
    return _personalize_actions([action], personalization, CONTEXT)[0]


class AgentReasonBehaviorTests(unittest.TestCase):
    def test_too_long_shortens_to_small_first_step(self):
        adjusted = personalize_single(action_for("too_long"), "too_long")
        self.assertLessEqual(adjusted["estimated_minutes"], 10)
        self.assertTrue(any("5-10 分钟" in item for item in adjusted["explainability"]["reason_adjustments"]))

    def test_too_disruptive_reduces_noise(self):
        adjusted = personalize_single(action_for("too_disruptive"), "too_disruptive")
        self.assertEqual(adjusted["priority"], "low")
        self.assertIn("低噪音", "".join(adjusted["explainability"]["reason_adjustments"]))

    def test_too_easy_prefers_deeper_step(self):
        adjusted = personalize_single(action_for("too_easy"), "too_easy")
        self.assertGreaterEqual(adjusted["estimated_minutes"], 15)
        self.assertIn("更深入", "".join(adjusted["explainability"]["reason_adjustments"]))

    def test_already_known_lowers_same_topic_basics(self):
        adjusted = personalize_single(action_for("already_known"), "already_known")
        self.assertEqual(adjusted["priority"], "low")
        self.assertIn("降低同主题", "".join(adjusted["explainability"]["reason_adjustments"]))

    def test_too_hard_splits_into_smaller_step(self):
        adjusted = personalize_single(action_for("too_hard"), "too_hard")
        self.assertLessEqual(adjusted["estimated_minutes"], 10)
        self.assertIn("更小", "".join(adjusted["explainability"]["reason_adjustments"]))

    def test_too_late_avoids_urgent_rescue(self):
        adjusted = personalize_single(action_for("too_late"), "too_late")
        self.assertEqual(adjusted["priority"], "low")
        self.assertIn("时机太晚", "".join(adjusted["explainability"]["reason_adjustments"]))


if __name__ == "__main__":
    unittest.main()
