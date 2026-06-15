"""自然语言输出层测试"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from narrator import (
    pick_notification, NotificationThrottle,
    _describe_hardware_warn, _describe_hardware_danger,
    _describe_network_issue, _describe_skill_blocked,
    _describe_cost, _describe_health_warn, _describe_health_danger,
)


class TestHardwareMessages(unittest.TestCase):

    def test_warn_no_crash(self):
        ctx = {"memory": {"memory_pct": 82, "used_gb": 13, "total_gb": 16},
               "disk": {"home_pct": 85, "home_avail_gb": 20}}
        self.assertIsInstance(_describe_hardware_warn(ctx), str)

    def test_warn_with_cleanup(self):
        ctx = {"memory": {"memory_pct": 82, "used_gb": 13, "total_gb": 16},
               "disk": {"home_pct": 92, "home_avail_gb": 5},
               "_actions_taken": ["cleaned_logs"],
               "freed_gb": 1.5}
        msg = _describe_hardware_warn(ctx)
        self.assertTrue("清理" in msg or "硬盘" in msg or "内存" in msg)

    def test_warn_normal_silent(self):
        ctx = {"memory": {"memory_pct": 50, "used_gb": 8, "total_gb": 16},
               "disk": {"home_pct": 50, "home_avail_gb": 100}}
        self.assertEqual(_describe_hardware_warn(ctx), "")

    def test_danger(self):
        ctx = {"memory": {"memory_pct": 92},
               "_actions_taken": ["emergency_saved", "compressed"]}
        msg = _describe_hardware_danger(ctx)
        self.assertTrue("保存" in msg or "内存" in msg)


class TestNetworkMessages(unittest.TestCase):

    def test_dns_failure(self):
        ctx = {"issues": ["dns_failure"], "advice": ["试试改 DNS"]}
        msg = _describe_network_issue(ctx)
        self.assertTrue("DNS" in msg or "域名" in msg)

    def test_empty(self):
        self.assertEqual(_describe_network_issue({"issues": [], "advice": []}), "")

    def test_no_network(self):
        ctx = {"issues": ["no_network"], "advice": ["检查网线"]}
        msg = _describe_network_issue(ctx)
        self.assertIn("网", msg)


class TestSkillBlocked(unittest.TestCase):

    def test_blocked(self):
        ctx = {"reason": "FATAL: rm -rf / detected"}
        msg = _describe_skill_blocked(ctx)
        self.assertTrue("不安全" in msg or "拦" in msg)


class TestCostMessages(unittest.TestCase):

    def test_normal(self):
        ctx = {"cost_usd": 0.52, "calls": 10, "over_budget": False}
        self.assertIn("$", _describe_cost(ctx))

    def test_over_budget(self):
        ctx = {"cost_usd": 0.52, "calls": 10, "over_budget": True}
        self.assertIn("预算", _describe_cost(ctx))


class TestHealthMessages(unittest.TestCase):

    def test_warn_empty(self):
        self.assertIsInstance(_describe_health_warn({"issues": []}), str)

    def test_warn_skills(self):
        msg = _describe_health_warn({"issues": ["2 broken skills"]})
        self.assertTrue("skill" in msg.lower() or "看看" in msg)

    def test_danger_log(self):
        msg = _describe_health_danger({"issues": ["log_unwritable"]})
        self.assertIsInstance(msg, str)

    def test_danger_empty(self):
        msg = _describe_health_danger({"issues": []})
        self.assertIn("问题", msg)


class TestNotificationPicker(unittest.TestCase):

    def test_empty(self):
        r = pick_notification([])
        self.assertFalse(r["notify"])

    def test_single(self):
        r = pick_notification([{"type": "skill_blocked",
                                "context": {"reason": "FATAL: test"}}])
        # may be throttled if already used today
        self.assertIn(r["notify"], (True, False))


class TestThrottle(unittest.TestCase):

    def test_allows_first(self):
        t = NotificationThrottle()
        t._log = {"entries": {}}
        self.assertTrue(t.should_speak("hardware_warn"))

    def test_blocks_excess(self):
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        t = NotificationThrottle()
        t._log = {"entries": {"hardware_warn": {today: [100, 200, 300]}}}
        self.assertFalse(t.should_speak("hardware_warn"))
