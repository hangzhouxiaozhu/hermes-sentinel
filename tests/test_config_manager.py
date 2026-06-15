"""配置冲突检测模块测试"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from config_manager import detect_conflicts, detect_and_recommend


class TestConfigManager(unittest.TestCase):

    def test_detect_conflicts_is_list(self):
        self.assertIsInstance(detect_conflicts(), list)

    def test_detect_and_recommend_no_crash(self):
        result = detect_and_recommend("/nonexistent/path")
        self.assertIn("has_conflicts", result)
        self.assertIn("conflicts_found", result)
        self.assertIn("resolutions", result)
