"""Intent translator tests — lightweight fuzzy instruction completion."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from intent_translator import translate


class TestTranslate_VisualTerms(unittest.TestCase):
    def test_tai_an(self):
        r = translate("太暗")
        self.assertTrue(r["should_translate"])
        self.assertEqual(r["category"], "视觉调整")
        self.assertIn("亮度", r["translated"])

    def test_tai_an_with_file(self):
        r = translate("太暗", current_file="/封面/cover.png")
        self.assertTrue(r["should_translate"])
        self.assertIn("图片/设计", r["translated"] or "")

    def test_tai_liang(self):
        r = translate("太亮")
        self.assertTrue(r["should_translate"])
        self.assertEqual(r["category"], "视觉调整")

    def test_buhaokan(self):
        r = translate("不好看")
        self.assertTrue(r["should_translate"])

    def test_kanbujian(self):
        r = translate("看不清")
        self.assertTrue(r["should_translate"])


class TestTranslate_CodeTerms(unittest.TestCase):
    def test_luanma(self):
        r = translate("乱码")
        self.assertTrue(r["should_translate"])
        self.assertEqual(r["category"], "编码修复")
        self.assertIn("utf-8", r["translated"].lower())

    def test_baocuo(self):
        r = translate("报错")
        self.assertTrue(r["should_translate"])
        self.assertEqual(r["category"], "代码调试")

    def test_paobuqilai(self):
        r = translate("跑不起来")
        self.assertTrue(r["should_translate"])


class TestTranslate_HermesTerms(unittest.TestCase):
    def test_tai_man(self):
        r = translate("太慢")
        self.assertTrue(r["should_translate"])
        self.assertEqual(r["category"], "性能优化")

    def test_tai_gui(self):
        r = translate("太贵")
        self.assertTrue(r["should_translate"])

    def test_lianbushang(self):
        r = translate("连不上")
        self.assertTrue(r["should_translate"])


class TestTranslate_DocumentTerms(unittest.TestCase):
    def test_tailuosuo(self):
        r = translate("太啰嗦")
        self.assertTrue(r["should_translate"])

    def test_taiduan(self):
        r = translate("太短")
        self.assertTrue(r["should_translate"])


class TestTranslate_Passthrough(unittest.TestCase):
    def test_long_instruction(self):
        r = translate("把这张图片的亮度提高20%")
        self.assertFalse(r["should_translate"])

    def test_denylisted(self):
        r = translate("继续运行")
        self.assertFalse(r["should_translate"])

    def test_clear_command(self):
        r = translate("帮我写一篇关于AI发展的文章")
        self.assertFalse(r["should_translate"])

    def test_short_with_object(self):
        """Short input with concrete object → passthrough."""
        r = translate("改标题")
        self.assertFalse(r["should_translate"])


class TestTranslate_NonFuzzy(unittest.TestCase):
    def test_yes(self):
        r = translate("yes")
        self.assertFalse(r["should_translate"])

    def test_no(self):
        r = translate("no")
        self.assertFalse(r["should_translate"])


class TestGuardianCoreHook(unittest.TestCase):
    def test_exports_before_hook(self):
        import guardian_core
        self.assertTrue(hasattr(guardian_core, "guardian_before_user_message"))

    def test_translates_fuzzy_input(self):
        import guardian_core
        r = guardian_core.guardian_before_user_message("太暗")
        self.assertIn(r["action"], ("pass", "translate"))

    def test_passes_long(self):
        import guardian_core
        r = guardian_core.guardian_before_user_message("把图片亮度提高20%")
        self.assertEqual(r["action"], "pass")

    def test_original_input_preserved(self):
        import guardian_core
        r = guardian_core.guardian_before_user_message("太暗")
        self.assertEqual(r["original_input"], "太暗")
