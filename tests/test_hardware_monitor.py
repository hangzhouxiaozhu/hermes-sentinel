"""Hardware monitor tests — check() structure, assess_level, auto_remediate."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


class TestAssessLevel(unittest.TestCase):
    def test_normal(self):
        from hardware_monitor import assess_level
        self.assertEqual(assess_level(50, 10, 2.0), "normal")

    def test_memory_warn(self):
        from hardware_monitor import assess_level
        self.assertEqual(assess_level(75, 10, 2.0), "warn")

    def test_memory_danger(self):
        from hardware_monitor import assess_level
        self.assertEqual(assess_level(90, 10, 2.0), "danger")

    def test_swap_warn(self):
        from hardware_monitor import assess_level
        self.assertEqual(assess_level(50, 40, 2.0), "warn")

    def test_swap_danger(self):
        from hardware_monitor import assess_level
        self.assertEqual(assess_level(50, 70, 2.0), "danger")

    def test_cpu_warn(self):
        from hardware_monitor import assess_level
        self.assertEqual(assess_level(50, 10, 6.0), "warn")


class TestCheck(unittest.TestCase):
    """check() with mocked os_detect."""

    def _mock_od(self, mem_pct=50, swap_pct=25, cpu_load=2.0):
        return patch("hardware_monitor.os_detect").start()

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
