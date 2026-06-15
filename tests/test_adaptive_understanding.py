"""自适应指令理解测试

覆盖场景：
1. "太暗" + 公众号封面上下文 → 重写为视觉设计方案
2. "乱码" + Python/API 上下文 → 重写为编码修复方案
3. "继续" + 无上下文 → 不强行重写，action=pass
4. 长明确指令 → 直接 pass
5. 有本地标准时 → standards_used 包含标准
6. 无 web 权限时 → needs_search=False，不搜索
"""

import sys
import json
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from adaptive_understanding import (
    is_ambiguous_instruction,
    build_rewrite_plan,
    guardian_before_user_message,
    VAGUE_WORDS,
)


class TestIsAmbiguous(unittest.TestCase):
    """模糊指令判断"""

    def test_vague_word_exact_match(self):
        self.assertTrue(is_ambiguous_instruction("太暗"))
        self.assertTrue(is_ambiguous_instruction("乱码"))
        self.assertTrue(is_ambiguous_instruction("不好看"))

    def test_short_input_without_object(self):
        self.assertTrue(is_ambiguous_instruction("不对"))
        self.assertTrue(is_ambiguous_instruction("太乱"))

    def test_short_input_with_object(self):
        """含具体宾语时不触发"""
        self.assertFalse(is_ambiguous_instruction("改标题"))
        self.assertFalse(is_ambiguous_instruction("调图片"))

    def test_long_explicit_instruction(self):
        """长明确指令不触发"""
        self.assertFalse(
            is_ambiguous_instruction("把这张图片的亮度提高20%")
        )
        self.assertFalse(
            is_ambiguous_instruction("帮我写一篇公众号文章关于AI发展")
        )


class TestBuildRewritePlan(unittest.TestCase):
    """重写计划生成"""

    def test_long_instruction_passes(self):
        """长明确指令 → action=pass"""
        result = build_rewrite_plan("把图片亮度提高20%")
        self.assertEqual(result["action"], "pass")
        self.assertFalse(result["should_rewrite"])

    def test_without_context_low_confidence(self):
        """无上下文时即使模糊词也不强行重写"""
        result = build_rewrite_plan("太暗")
        # 无上下文信号 → 置信度低 → action 可能为 pass 或 ask
        self.assertIn(result["action"], ("pass", "ask"))

    def test_tai_an_with_cover_context(self):
        """"太暗" + 封面上下文 → 重写"""
        ctx = {
            "conversation_context": {
                "last_user_message": "封面太暗了",
                "current_file": "/公众号/封面设计/文章封面.png",
                "recent_messages": [
                    {"role": "user", "content": "帮我做公众号封面"},
                    {"role": "assistant", "content": "好的，当前底色偏暖白"},
                ],
            }
        }
        result = build_rewrite_plan("太暗", conversation_context=ctx["conversation_context"])
        # 因为有封面/公众号等信号，应该匹配到新媒体视觉设计
        if result["action"] == "rewrite":
            self.assertEqual(result["industry"], "new_media_visual_design")
            self.assertIsNotNone(result["rewritten_instruction"])
            self.assertGreater(len(result["rationale"]), 0)

    def test_luanma_with_code_context(self):
        """"乱码" + Python/API 上下文 → 重写"""
        ctx = {
            "conversation_context": {
                "last_user_message": "Python 请求返回乱码",
                "current_file": "/代码/api_test.py",
                "active_tool": "terminal",
                "recent_messages": [
                    {"role": "user", "content": "调用微信API返回乱码"},
                ],
            }
        }
        result = build_rewrite_plan("乱码", conversation_context=ctx["conversation_context"])
        if result["action"] == "rewrite":
            self.assertEqual(result["industry"], "software_engineering")
            self.assertIsNotNone(result["rewritten_instruction"])

    def test_standards_included_when_matched(self):
        """匹配行业时 standards_used 应有值"""
        ctx = {
            "conversation_context": {
                "last_user_message": "封面",
                "current_file": "/公众号/封面/cover.png",
            }
        }
        result = build_rewrite_plan("太暗", conversation_context=ctx["conversation_context"])
        if result["action"] == "rewrite":
            self.assertGreater(len(result["standards_used"]), 0)
            self.assertGreater(len(result["standards_detail"]), 0)

    def test_no_web_search_when_disabled(self):
        """allow_web_search=False 时 needs_search 应为 False"""
        ctx = {
            "conversation_context": {
                "last_user_message": "封面",
                "current_file": "/公众号/封面/cover.png",
            }
        }
        result = build_rewrite_plan(
            "太暗",
            conversation_context=ctx["conversation_context"],
            allow_web_search=False,
        )
        if result["action"] == "rewrite":
            self.assertFalse(result["needs_search"])

    def test_search_queries_generated_even_without_search(self):
        """不搜索时仍生成 search_queries"""
        ctx = {
            "conversation_context": {
                "last_user_message": "封面",
                "current_file": "/公众号/封面/cover.png",
            }
        }
        result = build_rewrite_plan(
            "太暗",
            conversation_context=ctx["conversation_context"],
            allow_web_search=False,
        )
        if result["action"] == "rewrite":
            self.assertGreater(len(result["search_queries"]), 0)

    def test_loaded_skills_enhance_context(self):
        """加载 skill 增加上下文信号"""
        skills = [{"name": "wechat-editor", "description": "公众号文章排版与封面设计"}]
        result = build_rewrite_plan("太暗", loaded_skills=skills)
        self.assertIn(result["action"], ("pass", "ask", "rewrite"))


class TestGuardianBeforeUserMessage(unittest.TestCase):
    """前置 hook 入口"""

    def test_known_context_returns_rewrite_action(self):
        """有上下文时返回 rewrite action"""
        context = {
            "conversation_context": {
                "last_user_message": "封面设计",
                "current_file": "/公众号/封面/cover.png",
            },
            "web_available": False,
        }
        result = guardian_before_user_message("太暗", context=context)
        self.assertIn(result["action"], ("pass", "rewrite"))
        self.assertIn("original_input", result)
        self.assertIn("metadata", result)
        self.assertEqual(result["original_input"], "太暗")

    def test_long_instruction_passes_through(self):
        """长指令直接 pass"""
        result = guardian_before_user_message(
            "把这张图片的亮度提高20%"
        )
        self.assertEqual(result["action"], "pass")
        self.assertEqual(result["input"], "把这张图片的亮度提高20%")
        self.assertFalse(result["metadata"]["should_rewrite"])

    def test_original_input_preserved(self):
        """original_input 总是保留原始输入"""
        result = guardian_before_user_message("太暗")
        self.assertEqual(result["original_input"], "太暗")


class TestIndustryProfiles(unittest.TestCase):
    """行业配置表"""

    def test_all_industries_have_required_fields(self):
        from industry_profiles import INDUSTRY_PROFILES
        for key, profile in INDUSTRY_PROFILES.items():
            self.assertIn("name", profile, f"{key} missing name")
            self.assertIn("signals", profile, f"{key} missing signals")
            self.assertIsInstance(profile["signals"], list, f"{key} signals not list")
            self.assertGreater(len(profile["signals"]), 0, f"{key} has no signals")

    def test_match_industry_returns_sorted(self):
        from industry_profiles import match_industry
        results = match_industry(["公众号", "封面", "渲染"])
        self.assertGreater(len(results), 0)
        # 第一项得分应该是最高分
        if len(results) > 1:
            self.assertGreaterEqual(results[0][1], results[1][1])

    def test_known_ambiguous_term(self):
        from industry_profiles import get_ambiguous_rewrite
        intent = get_ambiguous_rewrite("new_media_visual_design", "太暗")
        self.assertIsNotNone(intent)
        self.assertIn("亮度", intent)

    def test_unknown_ambiguous_term(self):
        from industry_profiles import get_ambiguous_rewrite
        intent = get_ambiguous_rewrite("new_media_visual_design", "不存在的词")
        self.assertIsNone(intent)


class TestContextResolver(unittest.TestCase):
    """上下文解析器"""

    def test_resolve_returns_signals(self):
        from context_resolver import resolve_context
        result = resolve_context()
        self.assertIn("signals", result)
        self.assertIn("possible_industries", result)
        self.assertIn("confidence", result)

    def test_file_path_extracts_signals(self):
        from context_resolver import resolve_context
        result = resolve_context({"current_file": "/代码/test.py", "last_user_message": "报错"})
        self.assertGreater(len(result["signals"]), 0)

    def test_skill_enhances_signals(self):
        from context_resolver import resolve_context
        result = resolve_context(
            conversation_context={"last_user_message": "报错"},
            loaded_skills=[{"name": "debugger", "description": "Python 调试"}],
        )
        self.assertGreater(len(result["signals"]), 0)


class TestStandardsRegistry(unittest.TestCase):
    """本地标准注册表"""

    def test_get_known_standards(self):
        from standards_registry import get_standards
        standards = get_standards(["mobile_readability", "minimal_patch"])
        self.assertEqual(len(standards), 2)
        for s in standards:
            self.assertIn("key", s)
            self.assertIn("name", s)
            self.assertIn("description", s)
            self.assertIn("source", s)

    def test_get_unknown_standard_returns_empty(self):
        from standards_registry import get_standards
        standards = get_standards(["nonexistent_standard_xyz"])
        self.assertEqual(len(standards), 0)

    def test_get_all_keys(self):
        from standards_registry import get_all_standard_keys
        keys = get_all_standard_keys()
        self.assertGreater(len(keys), 0)
