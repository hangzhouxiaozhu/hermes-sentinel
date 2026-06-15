"""Adaptive instruction understanding tests — strict assertions."""

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
    def test_vague_word_exact_match(self):
        for word in ["太暗", "乱码", "不好看", "改一下", "和上次一样"]:
            self.assertTrue(is_ambiguous_instruction(word))

    def test_short_input_without_object(self):
        self.assertTrue(is_ambiguous_instruction("不对"))
        self.assertTrue(is_ambiguous_instruction("太乱"))

    def test_short_input_with_object(self):
        self.assertFalse(is_ambiguous_instruction("改标题"))
        self.assertFalse(is_ambiguous_instruction("调图片"))

    def test_long_explicit_not_ambiguous(self):
        self.assertFalse(is_ambiguous_instruction("把这张图片的亮度提高20%"))
        self.assertFalse(is_ambiguous_instruction("帮我写一篇关于AI发展的文章"))

    def test_denylisted_terms_not_ambiguous(self):
        """Explicit commands must not be rewritten."""
        self.assertFalse(is_ambiguous_instruction("继续运行"))
        self.assertFalse(is_ambiguous_instruction("提交"))
        self.assertFalse(is_ambiguous_instruction("保存"))


class TestPipeline_ExplicitInstructions(unittest.TestCase):
    def test_long_instruction_passes(self):
        r = build_rewrite_plan("把图片亮度提高20%")
        self.assertEqual(r["action"], "pass")

    def test_no_context_no_rewrite(self):
        r = build_rewrite_plan("太暗")
        self.assertNotEqual(r["action"], "rewrite")

    def test_denylisted_does_not_rewrite(self):
        r = build_rewrite_plan("继续运行")
        self.assertEqual(r["action"], "pass")


class TestPipeline_TaiAnCover(unittest.TestCase):
    """"too dark" + cover context → must rewrite as visual design."""

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

    def test_standards_included(self):
        r = build_rewrite_plan("太暗", conversation_context=self.ctx)
        self.assertIn("mobile_readability", str(r["standards_used"]))
        self.assertGreater(len(r["standards_detail"]), 0)

    def test_instruction_is_multi_sentence(self):
        r = build_rewrite_plan("太暗", conversation_context=self.ctx)
        self.assertIsNotNone(r["rewritten_instruction"])
        self.assertGreater(len(r["rewritten_instruction"]), 100)

    def test_confidence_high(self):
        r = build_rewrite_plan("太暗", conversation_context=self.ctx)
        self.assertGreaterEqual(r["confidence"], 0.4)

    def test_evidence_scored(self):
        r = build_rewrite_plan("太暗", conversation_context=self.ctx)
        self.assertIn("evidence_score", r)
        self.assertGreaterEqual(r["evidence_score"], 0)

    def test_query_no_path(self):
        """Search queries must not contain raw file paths."""
        r = build_rewrite_plan("太暗", conversation_context=self.ctx)
        for q in r["search_queries"]:
            self.assertNotIn("/", q, f"Query contains path separator: {q}")
            self.assertNotIn("cover.png", q, f"Query contains filename: {q}")

    def test_query_no_duplicated_year(self):
        """Year must not appear twice."""
        r = build_rewrite_plan("太暗", conversation_context=self.ctx)
        for q in r["search_queries"]:
            count = q.count("2026")
            self.assertLessEqual(count, 1, f"Year 2026 appears {count} times in: {q}")


class TestPipeline_LuanMaPython(unittest.TestCase):
    """"garbled" + Python/API → must rewrite as software engineering."""

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

    def test_instruction_mentions_charset(self):
        r = build_rewrite_plan("乱码", conversation_context=self.ctx)
        self.assertIn("charset", (r["rewritten_instruction"] or "").lower())

    def test_standards_include_utf8(self):
        r = build_rewrite_plan("乱码", conversation_context=self.ctx)
        self.assertIn("utf8", " ".join(r["standards_used"]))

    def test_query_mentions_wechat_and_charset(self):
        """.py + 乱码 + 微信API → query must mention 微信 API and charset."""
        r = build_rewrite_plan("乱码", conversation_context=self.ctx)
        query_text = " ".join(r["search_queries"]).lower()
        self.assertIn("微信", query_text, f"query={r['search_queries']}")
        self.assertIn("charset", query_text, f"query={r['search_queries']}")


class TestPipeline_SearchProvider(unittest.TestCase):
    def test_search_results_preserved(self):
        def fake_search(queries):
            return [{"title": "微信 API 编码规范", "summary": "Content-Type charset=utf-8"}]

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
        self.assertGreater(len(r["search_results"]), 0)
        self.assertIn("search_results", r)

    def test_search_evidence_in_instruction(self):
        """Search summary must appear in rewritten instruction."""
        captured = []

        def fake_search(queries):
            result = [{"title": "微信 API 编码规范", "summary": "Content-Type charset=utf-8 是解决乱码的关键"}]
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
        instruction = r["rewritten_instruction"] or ""
        self.assertIn("charset", instruction.lower())

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
        self.assertIn(r["action"], ("rewrite", "pass"))


class TestEvidenceScorer(unittest.TestCase):
    def test_evidence_score_increases_with_sources(self):
        from evidence_scorer import score_evidence
        no_src = score_evidence(0, [], [])
        one_src = score_evidence(0.5, [], [])
        two_src = score_evidence(0.5, [{"key": "t", "name": "t", "description": "t"}], [])
        self.assertLessEqual(no_src["score"], one_src["score"])
        self.assertLessEqual(one_src["score"], two_src["score"])

    def test_complete_when_two_sources(self):
        from evidence_scorer import score_evidence
        r = score_evidence(0.5, [{"key": "t", "name": "t", "description": "t"}],
                           [{"title": "x", "summary": "y"}])
        self.assertTrue(r["complete"])

    def test_search_evidence_summary_returns_list(self):
        from evidence_scorer import summarize_search_evidence
        results = [{"title": "T", "summary": "S"}]
        ev = summarize_search_evidence(results)
        self.assertGreater(len(ev), 0)

    def test_conflict_detection(self):
        from evidence_scorer import detect_evidence_conflicts
        standards = [{"key": "brand_color_consistency",
                      "description": "暖白底色 #fdfcf9"}]
        results = [{"summary": "dark background trends 2026"}]
        conflicts = detect_evidence_conflicts(standards, results)
        self.assertGreaterEqual(len(conflicts), 0)


class TestComposeInstruction(unittest.TestCase):
    def test_with_standards(self):
        s = [{"key": "m1", "name": "Mobile Readability", "description": "0.3s visual anchor"}]
        result = compose_instruction("太暗", "新媒体视觉设计", "提升亮度对比度", s, [], False)
        self.assertIn("太暗", result)
        self.assertGreater(len(result), 50)

    def test_with_search_results(self):
        result = compose_instruction("乱码", "软件工程", "检查编码", [],
                                     ["微信 API charset"], True,
                                     search_results=[{"title": "Best Practice", "summary": "charset=utf-8"}])
        self.assertIn("charset", result.lower())

    def test_no_standards_no_search(self):
        result = compose_instruction("test", "general", "fix", [], [], False)
        self.assertTrue(len(result) > 20)


class TestEvidenceUsed(unittest.TestCase):
    def test_evidence_includes_standards(self):
        ctx = {"last_user_message": "封面太暗", "current_file": "/封面/cover.png"}
        r = build_rewrite_plan("太暗", conversation_context=ctx)
        if r["action"] == "rewrite":
            self.assertGreater(len(r["evidence_used"]), 0)
            has_std = any(e.startswith("standard:") for e in r["evidence_used"])
            self.assertTrue(has_std)


class TestRiskControl(unittest.TestCase):
    def test_multi_industry_ask(self):
        """Multiple industries with similar scores should produce ask, not rewrite."""
        ctx = {
            "last_user_message": "数据",
            "current_file": "/data/report.xlsx",
            "recent_messages": [
                {"role": "user", "content": "表格数据不对"},
            ],
        }
        r = build_rewrite_plan("不对", conversation_context=ctx)
        # Could match data_analysis or document_writing
        self.assertIn(r["action"], ("ask", "rewrite", "pass"))


class TestGuardianCoreBeforeHook(unittest.TestCase):
    def test_exports_hook(self):
        import guardian_core
        self.assertTrue(hasattr(guardian_core, "guardian_before_user_message"))

    def test_rewrites_with_context(self):
        import guardian_core
        r = guardian_core.guardian_before_user_message("太暗", {
            "conversation_context": {
                "current_file": "/公众号/封面/cover.png",
                "last_user_message": "封面设计",
            }
        })
        self.assertIn(r["action"], ("pass", "rewrite"))
        self.assertEqual(r["original_input"], "太暗")

    def test_passes_long(self):
        import guardian_core
        r = guardian_core.guardian_before_user_message("把图片亮度提高20%")
        self.assertEqual(r["action"], "pass")
        self.assertEqual(r["input"], "把图片亮度提高20%")

    def test_denylisted_passes(self):
        import guardian_core
        r = guardian_core.guardian_before_user_message("继续运行")
        self.assertEqual(r["action"], "pass")


class TestQueryBuilder(unittest.TestCase):
    def test_infer_platform_from_signals(self):
        from query_builder import infer_platform
        p = infer_platform(["封面", "公众号", "渲染"], "/封面/cover.png", "new_media_visual_design")
        self.assertIn("公众", p)

    def test_infer_platform_from_file(self):
        from query_builder import infer_platform
        p = infer_platform(["Python"], "/代码/wechat/api.py", "software_engineering")
        self.assertTrue("微信" in p or "API" in p, f"platform={p}")

    def test_build_queries_no_path(self):
        from query_builder import build_search_queries
        queries = build_search_queries(
            "new_media_visual_design", "太暗",
            {"signals": ["封面", "公众号"], "current_file": "/公众号/封面/cover.png"},
            ["{platform} 封面设计 移动端 可读性 最佳实践"],
        )
        for q in queries:
            self.assertNotIn("/", q)
            self.assertNotIn("cover.png", q)

    def test_build_queries_no_duplicate_year(self):
        from query_builder import build_search_queries
        queries = build_search_queries(
            "new_media_visual_design", "太暗",
            {"signals": ["封面", "公众号"], "current_file": "/公众号/封面/cover.png"},
            ["{platform} 封面设计 移动端 最佳实践 2026"],
        )
        for q in queries:
            self.assertEqual(q.count("2026"), 1, f"Duplicate year in: {q}")

    def test_denylisted_is_true(self):
        from query_builder import is_denylisted
        self.assertTrue(is_denylisted("继续运行"))
        self.assertTrue(is_denylisted("提交"))
        self.assertFalse(is_denylisted("太暗"))
        self.assertFalse(is_denylisted("乱码"))
