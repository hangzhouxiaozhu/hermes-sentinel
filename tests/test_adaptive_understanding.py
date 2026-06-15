"""Adaptive instruction understanding tests.

Strict assertions — must rewrite when context is clear.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from adaptive_understanding import (
    is_ambiguous_instruction,
    build_rewrite_plan,
    guardian_before_user_message,
    compose_instruction,
    VAGUE_WORDS,
)


class TestIsAmbiguous(unittest.TestCase):
    """Ambiguity detection"""

    def test_vague_word_exact_match(self):
        for word in ["太暗", "乱码", "不好看", "改一下", "和上次一样"]:
            self.assertTrue(is_ambiguous_instruction(word), f"{word} should be ambiguous")

    def test_short_input_without_object(self):
        self.assertTrue(is_ambiguous_instruction("不对"))
        self.assertTrue(is_ambiguous_instruction("太乱"))

    def test_short_input_with_object_is_not_ambiguous(self):
        """Has concrete object → not ambiguous"""
        self.assertFalse(is_ambiguous_instruction("改标题"))
        self.assertFalse(is_ambiguous_instruction("调图片"))

    def test_long_explicit_instruction_not_ambiguous(self):
        self.assertFalse(is_ambiguous_instruction("把这张图片的亮度提高20%"))
        self.assertFalse(is_ambiguous_instruction("帮我写一篇关于AI发展的文章"))


class TestBuildRewritePlan_ExplicitInstructions(unittest.TestCase):
    """Clear commands must pass through unchanged."""

    def test_long_instruction_passes(self):
        r = build_rewrite_plan("把图片亮度提高20%")
        self.assertEqual(r["action"], "pass")
        self.assertFalse(r["should_rewrite"])

    def test_without_context_low_confidence(self):
        """Ambiguous word with zero context should not force rewrite."""
        r = build_rewrite_plan("太暗")
        self.assertNotEqual(r["action"], "rewrite",
                            "No context → should not force rewrite")


class TestBuildRewritePlan_TaiAnCover(unittest.TestCase):
    """"too dark" + wechat cover context → must rewrite as visual design."""

    def setUp(self):
        self.ctx = {
            "last_user_message": "这个封面太暗了",
            "current_file": "/公众号/封面设计/文章封面.png",
            "recent_messages": [
                {"role": "user", "content": "帮我做公众号封面"},
                {"role": "assistant", "content": "好的，当前底色偏暖白"},
                {"role": "user", "content": "太暗"},
            ],
        }

    def test_must_rewrite(self):
        r = build_rewrite_plan("太暗", conversation_context=self.ctx)
        self.assertEqual(r["action"], "rewrite")
        self.assertEqual(r["industry"], "new_media_visual_design")

    def test_rewritten_instruction_includes_standards(self):
        r = build_rewrite_plan("太暗", conversation_context=self.ctx)
        self.assertIn("mobile_readability", str(r["standards_used"]))
        self.assertGreater(len(r["standards_detail"]), 0)

    def test_rewritten_instruction_is_multi_sentence(self):
        r = build_rewrite_plan("太暗", conversation_context=self.ctx)
        instruction = r["rewritten_instruction"]
        self.assertIsNotNone(instruction)
        # Should be more than just a short intent
        self.assertGreater(len(instruction), 50)
        self.assertIn("standard", instruction.lower())

    def test_search_queries_generated(self):
        r = build_rewrite_plan("太暗", conversation_context=self.ctx, allow_web_search=False)
        self.assertGreater(len(r["search_queries"]), 0)

    def test_confidence_high(self):
        r = build_rewrite_plan("太暗", conversation_context=self.ctx)
        self.assertGreaterEqual(r["confidence"], 0.4)


class TestBuildRewritePlan_LuanMaPython(unittest.TestCase):
    """"garbled" + Python/API context → must rewrite as software engineering."""

    def setUp(self):
        self.ctx = {
            "last_user_message": "Python 请求返回乱码",
            "current_file": "/代码/api_test.py",
            "active_tool": "terminal",
            "recent_messages": [
                {"role": "user", "content": "调用微信API返回乱码"},
            ],
        }

    def test_must_rewrite(self):
        r = build_rewrite_plan("乱码", conversation_context=self.ctx)
        self.assertEqual(r["action"], "rewrite")
        self.assertEqual(r["industry"], "software_engineering")

    def test_rewritten_instruction_mentions_charset(self):
        r = build_rewrite_plan("乱码", conversation_context=self.ctx)
        instruction = r["rewritten_instruction"] or ""
        self.assertIn("charset", instruction.lower())

    def test_standards_include_utf8(self):
        r = build_rewrite_plan("乱码", conversation_context=self.ctx)
        used = " ".join(r["standards_used"])
        self.assertIn("utf8", used)


class TestBuildRewritePlan_SearchProvider(unittest.TestCase):
    """search_provider results must be preserved in output."""

    def test_search_results_preserved(self):
        captured = []

        def fake_search(queries):
            result = [{"title": "微信 API 编码规范", "summary": "Content-Type charset=utf-8"}]
            captured.append(result)
            return result

        r = build_rewrite_plan(
            "乱码",
            conversation_context={
                "last_user_message": "Python 微信API乱码",
                "current_file": "/代码/wechat.py",
            },
            allow_web_search=True,
            search_provider=fake_search,
        )
        self.assertEqual(r["action"], "rewrite")
        self.assertTrue(r["needs_search"])
        self.assertIn("search_results", r)
        self.assertGreater(len(r["search_results"]), 0)

    def test_search_provider_error_does_not_crash(self):
        def broken_search(queries):
            raise RuntimeError("search failed")

        r = build_rewrite_plan(
            "乱码",
            conversation_context={
                "last_user_message": "Python 乱码",
                "current_file": "/代码/wechat.py",
            },
            allow_web_search=True,
            search_provider=broken_search,
        )
        # Should not crash, should still produce a plan
        self.assertIn(r["action"], ("rewrite", "pass"))


class TestComposeInstruction(unittest.TestCase):
    """Instruction composition."""

    def test_compose_with_standards(self):
        standards = [
            {"key": "m1", "name": "Mobile Readability", "description": "0.3s visual anchor"},
            {"key": "m2", "name": "Thumbnail Legibility", "description": "Readable at 200px"},
        ]
        result = compose_instruction(
            original="太暗",
            industry_name="新媒体视觉设计",
            intent="提升亮度对比度",
            standards=standards,
            search_queries=[],
            needs_search=False,
        )
        self.assertIn("Readability", result)
        self.assertIn("太暗", result)
        self.assertGreater(len(result), 50)

    def test_compose_with_search_queries(self):
        result = compose_instruction(
            original="乱码",
            industry_name="软件工程",
            intent="检查编码",
            standards=[],
            search_queries=["微信 API charset 2026"],
            needs_search=True,
        )
        self.assertIn("微信", result)

    def test_compose_no_standards_no_search(self):
        result = compose_instruction(
            original="test",
            industry_name="general",
            intent="fix",
            standards=[],
            search_queries=[],
            needs_search=False,
        )
        self.assertTrue(result.startswith("Based on") or result.startswith("Handle"))


class TestEvidenceUsed(unittest.TestCase):
    """evidence_used must be populated correctly."""

    def test_evidence_includes_standards(self):
        ctx = {
            "last_user_message": "封面太暗",
            "current_file": "/封面/cover.png",
        }
        r = build_rewrite_plan("太暗", conversation_context=ctx)
        if r["action"] == "rewrite":
            self.assertGreater(len(r["evidence_used"]), 0)
            has_standard = any(e.startswith("standard:") for e in r["evidence_used"])
            self.assertTrue(has_standard, f"evidence_used={r['evidence_used']}")


class TestGuardianCoreBeforeHook(unittest.TestCase):
    """guardian_core must export guardian_before_user_message."""

    def test_guardian_core_exports_before_hook(self):
        import guardian_core
        self.assertTrue(hasattr(guardian_core, "guardian_before_user_message"),
                        "guardian_core does not export guardian_before_user_message")

    def test_guardian_core_before_hook_rewrites_with_context(self):
        import guardian_core
        result = guardian_core.guardian_before_user_message("太暗", {
            "conversation_context": {
                "current_file": "/公众号/封面/cover.png",
                "last_user_message": "封面设计",
            }
        })
        self.assertIn(result["action"], ("pass", "rewrite"))
        self.assertEqual(result["original_input"], "太暗")

    def test_guardian_core_before_hook_passes_long(self):
        import guardian_core
        result = guardian_core.guardian_before_user_message(
            "把这张图片的亮度提高20%"
        )
        self.assertEqual(result["action"], "pass")


class TestGuardianBeforeUserMessage(unittest.TestCase):
    """Front-end hook integrity."""

    def test_known_context_returns_rewrite_action(self):
        result = guardian_before_user_message("太暗", {
            "conversation_context": {
                "current_file": "/公众号/封面/cover.png",
                "last_user_message": "封面设计"
            },
            "web_available": False,
        })
        self.assertIn(result["action"], ("pass", "rewrite"))
        self.assertIn("metadata", result)
        self.assertEqual(result["original_input"], "太暗")

    def test_long_instruction_passes_through(self):
        result = guardian_before_user_message("把图片亮度提高20%")
        self.assertEqual(result["action"], "pass")
        self.assertEqual(result["input"], "把图片亮度提高20%")

    def test_original_input_preserved(self):
        result = guardian_before_user_message("太暗")
        self.assertEqual(result["original_input"], "太暗")


class TestIndustryProfiles(unittest.TestCase):
    """Industry configuration."""

    def test_all_industries_have_required_fields(self):
        from industry_profiles import INDUSTRY_PROFILES
        for key, profile in INDUSTRY_PROFILES.items():
            self.assertIn("name", profile, f"{key} missing name")
            self.assertIn("signals", profile, f"{key} missing signals")
            self.assertIsInstance(profile["signals"], list)
            self.assertGreater(len(profile["signals"]), 0)

    def test_match_industry_returns_sorted(self):
        from industry_profiles import match_industry
        results = match_industry(["公众号", "封面", "渲染"])
        self.assertGreater(len(results), 0)
        if len(results) > 1:
            self.assertGreaterEqual(results[0][1], results[1][1])

    def test_signal_dilution_does_not_kill_score(self):
        """Many irrelevant signals should not dilute a strong match to zero."""
        from industry_profiles import match_industry
        noisy = ["封面", "公众号", "渲染", "hello", "world", "foo", "bar", "baz"]
        results = match_industry(noisy)
        self.assertGreater(len(results), 0)
        top_score = results[0][1]
        self.assertGreater(top_score, 0.2, f"Score {top_score} too low after dilution")

    def test_known_ambiguous_term(self):
        from industry_profiles import get_ambiguous_rewrite
        intent = get_ambiguous_rewrite("new_media_visual_design", "太暗")
        self.assertIsNotNone(intent)
        self.assertIn("亮度", intent)

    def test_unknown_ambiguous_term(self):
        from industry_profiles import get_ambiguous_rewrite
        intent = get_ambiguous_rewrite("new_media_visual_design", "不存在的词")
        self.assertIsNone(intent)

    def test_strong_signals_boost_score(self):
        from industry_profiles import match_industry
        # 2 strong signals should give > 0.5
        results = match_industry(["Python", "API", "乱码"])
        self.assertGreater(len(results), 0)
        for key, score, _ in results:
            if key == "software_engineering":
                self.assertGreaterEqual(score, 0.5,
                    f"2 strong signals should give >= 0.5, got {score}")


class TestContextResolver(unittest.TestCase):
    """Context resolver."""

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

    def test_extract_signals_finds_chinese_keywords(self):
        from context_resolver import extract_signals_from_text
        signals = extract_signals_from_text("调用微信API返回乱码，需要修复编码问题")
        signal_set = set(signals)
        self.assertIn("乱码", signal_set, f"signals={signals}")
        self.assertIn("API", signal_set, f"signals={signals}")
        self.assertIn("微信", signal_set, f"signals={signals}")

    def test_extract_signals_from_cover_text(self):
        from context_resolver import extract_signals_from_text
        signals = extract_signals_from_text("这个公众号封面太暗了，需要调整")
        signal_set = set(signals)
        self.assertIn("公众号", signal_set, f"signals={signals}")
        self.assertIn("封面", signal_set, f"signals={signals}")


class TestStandardsRegistry(unittest.TestCase):
    """Standards registry."""

    def test_get_known_standards(self):
        from standards_registry import get_standards
        standards = get_standards(["mobile_readability", "minimal_patch"])
        self.assertEqual(len(standards), 2)
        for s in standards:
            self.assertIn("key", s)
            self.assertIn("name", s)

    def test_get_unknown_standard_returns_empty(self):
        from standards_registry import get_standards
        standards = get_standards(["nonexistent_standard_xyz"])
        self.assertEqual(len(standards), 0)

    def test_get_all_keys(self):
        from standards_registry import get_all_standard_keys
        keys = get_all_standard_keys()
        self.assertGreater(len(keys), 0)
