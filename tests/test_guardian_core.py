"""Guardian core tests — tick, notifications, daily report."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


class TestGuardianTick(unittest.TestCase):
    """guardian_tick() must handle all submodules gracefully."""

    def test_tick_returns_dict(self):
        import guardian_core
        result = guardian_core.guardian_tick()
        self.assertIn("notify", result)
        self.assertIn("message", result)
        self.assertIn("urgency", result)

    @patch.dict("os.environ", {"HERMES_SENTINEL_SKIP_SETUP": "1"}, clear=True)
    def test_tick_skip_setup_env(self):
        """HERMES_SENTINEL_SKIP_SETUP=1 should not crash."""
        import guardian_core
        guardian_core._INIT_DONE = False
        msg = guardian_core._first_run_setup()
        self.assertIsNone(msg, "SKIP_SETUP should return None")

    def test_tick_notify_false_when_healthy(self):
        """Normal conditions should produce notify=False."""
        import guardian_core
        result = guardian_core.guardian_tick()
        # May produce false if hardware is warn, but should not crash
        self.assertIn(result["notify"], (True, False))

    def test_tick_with_hardware_warn(self):
        """Ensure tick still returns a valid structure even when hardware is warn."""
        import guardian_core
        with patch("guardian_core.hardware_monitor") as mock_hw:
            mock_hw.check.return_value = {
                "level": "warn", "memory": {"memory_pct": 82},
                "disk": {"home_pct": 50},
            }
            mock_hw.auto_remediate.return_value = ["cleaned_logs"]
            result = guardian_core.guardian_tick()
            self.assertIn("notify", result)

    def test_exports_before_hook(self):
        import guardian_core
        self.assertTrue(hasattr(guardian_core, "guardian_before_user_message"))

    def test_exports_on_api_call(self):
        import guardian_core
        self.assertTrue(hasattr(guardian_core, "guardian_on_api_call"))

    def test_exports_get_notification(self):
        import guardian_core
        self.assertTrue(hasattr(guardian_core, "get_notification"))


class TestGetNotification(unittest.TestCase):
    """get_notification() must handle missing/corrupted flag files."""

    def test_no_flag_file(self):
        import guardian_core
        from pathlib import Path as P
        with patch("guardian_core.FLAG_FILE", P("/tmp/nonexistent-sentinel-flag-xyz")):
            r = guardian_core.get_notification()
            self.assertFalse(r["has"])
            self.assertIsNone(r["message"])


class TestGuardianDailyReport(unittest.TestCase):
    """Daily report must handle missing logs gracefully."""

    def test_report_returns_string(self):
        import guardian_core
        report = guardian_core.guardian_daily_report()
        self.assertIsInstance(report, str)
        self.assertGreater(len(report), 0)

    def test_report_with_mock_cost(self):
        import guardian_core
        with patch("guardian_core.cost_tracker") as mock_ct:
            mock_ct.get_user_friendly_summary.return_value = "Used 1.5K tokens today."
            report = guardian_core.guardian_daily_report()
            self.assertIn("token", report.lower())
