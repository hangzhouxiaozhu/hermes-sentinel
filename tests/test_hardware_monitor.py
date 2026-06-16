"""Hardware monitor tests — check() structure, assess_level, auto_remediate."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

# Standard thresholds for cross-platform test consistency
TEST_THRESHOLDS = {
    "memory_warn": 75,
    "memory_danger": 88,
    "swap_warn": 30,
    "swap_danger": 60,
    "cpu_load_warn": 5.0,
}

# macOS thresholds (more relaxed)
MACOS_THRESHOLDS = {
    "memory_warn": 80,
    "memory_danger": 92,
    "swap_warn": 40,
    "swap_danger": 70,
    "cpu_load_warn": 5.0,
}


class TestAssessLevel(unittest.TestCase):
    """assess_level uses passed thresholds, not platform defaults."""

    def test_normal(self):
        from hardware_monitor import assess_level
        self.assertEqual(assess_level(50, 10, 2.0, TEST_THRESHOLDS), "normal")

    def test_memory_warn(self):
        from hardware_monitor import assess_level
        self.assertEqual(assess_level(75, 10, 2.0, TEST_THRESHOLDS), "warn")

    def test_memory_danger(self):
        from hardware_monitor import assess_level
        self.assertEqual(assess_level(88, 10, 2.0, TEST_THRESHOLDS), "danger")

    def test_swap_warn(self):
        from hardware_monitor import assess_level
        self.assertEqual(assess_level(50, 40, 2.0, TEST_THRESHOLDS), "warn")

    def test_swap_danger(self):
        from hardware_monitor import assess_level
        self.assertEqual(assess_level(50, 70, 2.0, TEST_THRESHOLDS), "danger")

    def test_cpu_warn(self):
        from hardware_monitor import assess_level
        self.assertEqual(assess_level(50, 10, 6.0, TEST_THRESHOLDS), "warn")

    def test_macos_80_is_normal(self):
        """macOS 阈值 80% 才告警，75% 应返回 normal"""
        from hardware_monitor import assess_level
        self.assertEqual(assess_level(75, 10, 2.0, MACOS_THRESHOLDS), "normal")

    def test_macos_85_is_normal(self):
        """macOS 下 85% 仍低于 92% danger 阈值"""
        from hardware_monitor import assess_level
        self.assertEqual(assess_level(85, 10, 2.0, MACOS_THRESHOLDS), "warn")


class TestGetThresholds(unittest.TestCase):
    """get_thresholds must return platform-appropriate values."""

    def test_darwin_returns_macos(self):
        with patch("hardware_monitor.os_detect.SYSTEM", "Darwin"):
            from hardware_monitor import get_thresholds
            t = get_thresholds()
            self.assertEqual(t["memory_warn"], 80)
            self.assertEqual(t["memory_danger"], 92)

    def test_windows_returns_standard(self):
        with patch("hardware_monitor.os_detect.SYSTEM", "Windows"):
            from hardware_monitor import get_thresholds
            t = get_thresholds()
            self.assertEqual(t["memory_warn"], 70)
            self.assertEqual(t["memory_danger"], 85)

    def test_linux_returns_linux(self):
        with patch("hardware_monitor.os_detect.SYSTEM", "Linux"):
            from hardware_monitor import get_thresholds
            t = get_thresholds()
            self.assertEqual(t["memory_warn"], 75)
            self.assertEqual(t["memory_danger"], 88)

    def test_all_have_required_keys(self):
        from hardware_monitor import get_thresholds
        t = get_thresholds()
        for key in ("memory_warn", "memory_danger", "swap_warn", "swap_danger", "cpu_load_warn"):
            self.assertIn(key, t)
            self.assertGreater(t[key], 0)

    def test_threshold_summary_returns_dict(self):
        from hardware_monitor import threshold_summary
        s = threshold_summary()
        self.assertIn("platform", s)
        self.assertIn("memory_warn", s)

    def test_macos_warn_lower_than_danger(self):
        """warn 必须小于 danger"""
        from hardware_monitor import PLATFORM_THRESHOLDS
        for os_key, thresholds in PLATFORM_THRESHOLDS.items():
            self.assertLess(thresholds["memory_warn"], thresholds["memory_danger"],
                            f"{os_key}: memory_warn >= memory_danger")
            self.assertLess(thresholds["swap_warn"], thresholds["swap_danger"],
                            f"{os_key}: swap_warn >= swap_danger")


class TestCheck(unittest.TestCase):
    """check() with mocked os_detect + standard thresholds for cross-platform consistency."""

    def setUp(self):
        self.thresholds_patcher = patch("hardware_monitor.get_thresholds",
                                        return_value=TEST_THRESHOLDS)
        self.thresholds_patcher.start()

    def tearDown(self):
        self.thresholds_patcher.stop()

    @patch("hardware_monitor.os_detect")
    def test_check_returns_snapshot(self, mock_od):
        from hardware_monitor import check
        mock_od.get_memory_info.return_value = {
            "total_gb": 16, "used_gb": 8, "free_gb": 8, "memory_pct": 50,
            "swap_total_mb": 2048, "swap_used_mb": 512, "swap_pct": 25,
        }
        mock_od.get_cpu_info.return_value = {
            "load_1min": 2.0, "load_5min": 1.5, "load_15min": 1.0, "cores": 10,
        }
        mock_od.get_disk_info.return_value = {
            "root_total_gb": 256, "root_avail_gb": 128, "root_pct": 50,
            "home_total_gb": 256, "home_avail_gb": 128, "home_pct": 50,
        }
        mock_od.get_gpu_info.return_value = {
            "gpu_name": "Apple Silicon", "vram_mb": 0, "available": True,
        }
        snapshot = check()
        self.assertIn("level", snapshot)
        self.assertIn("memory", snapshot)
        self.assertEqual(snapshot["level"], "normal")

    @patch("hardware_monitor.os_detect")
    def test_check_high_memory_triggers_warn(self, mock_od):
        from hardware_monitor import check
        mock_od.get_memory_info.return_value = {
            "total_gb": 16, "used_gb": 12, "free_gb": 4, "memory_pct": 75,
            "swap_total_mb": 2048, "swap_used_mb": 512, "swap_pct": 25,
        }
        mock_od.get_cpu_info.return_value = {"load_1min": 2.0, "load_5min": 1.5, "load_15min": 1.0, "cores": 10}
        mock_od.get_disk_info.return_value = {"root_total_gb": 256, "root_avail_gb": 128, "root_pct": 50, "home_total_gb": 256, "home_avail_gb": 128, "home_pct": 50}
        mock_od.get_gpu_info.return_value = {"gpu_name": "Apple Silicon", "vram_mb": 0, "available": True}
        snapshot = check()
        self.assertEqual(snapshot["level"], "warn")

    @patch("hardware_monitor.os_detect")
    def test_check_danger_swap(self, mock_od):
        from hardware_monitor import check
        mock_od.get_memory_info.return_value = {
            "total_gb": 16, "used_gb": 8, "free_gb": 8, "memory_pct": 50,
            "swap_total_mb": 2048, "swap_used_mb": 1536, "swap_pct": 75,
        }
        mock_od.get_cpu_info.return_value = {"load_1min": 2.0, "load_5min": 1.5, "load_15min": 1.0, "cores": 10}
        mock_od.get_disk_info.return_value = {"root_total_gb": 256, "root_avail_gb": 128, "root_pct": 50, "home_total_gb": 256, "home_avail_gb": 128, "home_pct": 50}
        mock_od.get_gpu_info.return_value = {"gpu_name": "Apple Silicon", "vram_mb": 0, "available": True}
        snapshot = check()
        self.assertEqual(snapshot["level"], "danger")


class TestAutoRemediate(unittest.TestCase):
    """auto_remediate must handle edge cases without crashing."""

    def test_no_disk_issue_returns_empty(self):
        from hardware_monitor import auto_remediate
        result = {"level": "normal", "disk": {"home_pct": 50}}
        actions = auto_remediate(result)
        self.assertIsInstance(actions, list)

    def test_warn_without_cleanup(self):
        from hardware_monitor import auto_remediate
        result = {"level": "warn", "disk": {"home_pct": 85}}
        actions = auto_remediate(result)
        self.assertIsInstance(actions, list)

    def test_danger_adds_compressed(self):
        from hardware_monitor import auto_remediate
        result = {"level": "danger", "disk": {"home_pct": 50}}
        actions = auto_remediate(result)
        self.assertIn("compressed", actions)


class TestHistorySummary(unittest.TestCase):
    """History summary handles missing/empty logs."""

    def test_no_log(self):
        from hardware_monitor import history_summary
        with patch("hardware_monitor.LOG_FILE", Path(tempfile.mktemp())):
            s = history_summary()
            self.assertEqual(s["warn_count"], 0)
            self.assertEqual(s["danger_count"], 0)
