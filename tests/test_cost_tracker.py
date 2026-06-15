"""Token 统计与费用估算模块测试"""

import sys
import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from cost_tracker import (
    get_known_models,
    calc_cost, record, extract_usage, record_from_response,
    get_daily_summary, get_user_friendly_summary,
    MODEL_PRICES,
)


def _get_model_price(n):
    """测试用——访问内部价格查询"""
    return MODEL_PRICES.get(n) or next(
        (v for k, v in MODEL_PRICES.items() if k.lower() in n.lower() or n.lower() in k.lower()),
        MODEL_PRICES.get("deepseek-v4-flash"),
    )


class TestExtractUsage(unittest.TestCase):
    """从 API 响应体中提取 token 数（核心功能）"""

    def test_openai_format(self):
        resp = {"usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}
        r = extract_usage(resp)
        self.assertEqual(r["input_tokens"], 100)
        self.assertEqual(r["output_tokens"], 50)
        self.assertEqual(r["source"], "openai")
        self.assertEqual(r["confidence"], "high")

    def test_anthropic_format(self):
        resp = {"usage": {"input_tokens": 200, "output_tokens": 80}}
        r = extract_usage(resp)
        self.assertEqual(r["input_tokens"], 200)
        self.assertEqual(r["output_tokens"], 80)
        self.assertEqual(r["source"], "anthropic")

    def test_gemini_format(self):
        resp = {"usageMetadata": {"promptTokenCount": 300, "candidatesTokenCount": 120}}
        r = extract_usage(resp)
        self.assertEqual(r["input_tokens"], 300)
        self.assertEqual(r["output_tokens"], 120)
        self.assertEqual(r["source"], "gemini")

    def test_flat_format(self):
        resp = {"prompt_tokens": 50, "completion_tokens": 25}
        r = extract_usage(resp)
        self.assertEqual(r["input_tokens"], 50)
        self.assertEqual(r["output_tokens"], 25)
        self.assertEqual(r["source"], "common_count_tokens")

    def test_empty_response(self):
        r = extract_usage({})
        self.assertEqual(r["confidence"], "none")

    def test_not_a_dict(self):
        r = extract_usage("not a dict")
        self.assertEqual(r["confidence"], "none")

    def test_openai_with_extra_fields(self):
        resp = {"id": "chatcmpl-xxx", "usage": {"prompt_tokens": 150, "completion_tokens": 75}}
        r = extract_usage(resp)
        self.assertEqual(r["input_tokens"], 150)
        self.assertEqual(r["output_tokens"], 75)


class TestRecord(unittest.TestCase):

    @patch("cost_tracker.LOG_FILE", new_callable=lambda: Path(tempfile.mktemp(suffix=".log")))
    def test_record_returns_tokens(self, mock_path):
        if mock_path.exists():
            mock_path.unlink()
        mock_path.parent.mkdir(parents=True, exist_ok=True)

        r = record("deepseek-chat", 100, 50)
        self.assertTrue(r["recorded"])
        self.assertEqual(r["input_tokens"], 100)
        self.assertEqual(r["output_tokens"], 50)
        # cost_usd 应有值（当前有价格表）
        self.assertIsNotNone(r["cost_usd"])

        entry = json.loads(mock_path.read_text().strip().split("\n")[0])
        self.assertEqual(entry["model"], "deepseek-chat")
        self.assertEqual(entry["input_tokens"], 100)
        mock_path.unlink(missing_ok=True)

    @patch("cost_tracker.LOG_FILE", new_callable=lambda: Path(tempfile.mktemp(suffix=".log")))
    def test_record_multiple(self, mock_path):
        if mock_path.exists():
            mock_path.unlink()
        mock_path.parent.mkdir(parents=True, exist_ok=True)
        record("gpt-4o", 1000, 500)
        record("deepseek-chat", 200, 100)
        lines = mock_path.read_text().strip().split("\n")
        self.assertEqual(len(lines), 2)
        mock_path.unlink(missing_ok=True)


class TestRecordFromResponse(unittest.TestCase):

    @patch("cost_tracker.LOG_FILE", new_callable=lambda: Path(tempfile.mktemp(suffix=".log")))
    def test_record_from_openai(self, mock_path):
        if mock_path.exists():
            mock_path.unlink()
        mock_path.parent.mkdir(parents=True, exist_ok=True)
        resp = {"usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        r = record_from_response(resp, "gpt-4o")
        self.assertTrue(r["recorded"])
        self.assertEqual(r["usage_source"], "openai")
        self.assertEqual(r["input_tokens"], 100)
        self.assertEqual(r["output_tokens"], 50)
        mock_path.unlink(missing_ok=True)

    @patch("cost_tracker.LOG_FILE", new_callable=lambda: Path(tempfile.mktemp(suffix=".log")))
    def test_record_from_empty(self, mock_path):
        if mock_path.exists():
            mock_path.unlink()
        mock_path.parent.mkdir(parents=True, exist_ok=True)
        r = record_from_response({}, "unknown-model")
        self.assertFalse(r["recorded"])
        self.assertIsNone(r["usage_source"])
        mock_path.unlink(missing_ok=True)


class TestGetDailySummary(unittest.TestCase):

    def test_no_log(self):
        s = get_daily_summary()
        self.assertEqual(s["total_calls"], 0)
        self.assertEqual(s["total_tokens"], 0)


class TestGetUserFriendlySummary(unittest.TestCase):

    def test_no_calls_empty(self):
        with patch("cost_tracker.LOG_FILE", Path(tempfile.mktemp())):
            r = get_user_friendly_summary()
            self.assertEqual(r, "")

    def test_with_tokens_direct(self):
        """直接测试 record() 返回值的 token 字段"""
        with patch("cost_tracker.LOG_FILE", Path(tempfile.mktemp(suffix=".log"))) as _:
            r = record("gpt-4o", 1000, 500)
            self.assertEqual(r["input_tokens"], 1000)
            self.assertEqual(r["output_tokens"], 500)

    def test_summary_format_with_mock(self):
        """mock get_daily_summary 测试输出格式"""
        with patch("cost_tracker.get_daily_summary") as mock_summary:
            mock_summary.return_value = {
                "total_calls": 3, "total_tokens": 1500,
                "total_input_tokens": 1000, "total_output_tokens": 500,
                "total_cost_usd": 0.0075, "by_model": {"gpt-4o": {}},
            }
            r = get_user_friendly_summary()
            self.assertIn("token", r.lower())

    def test_summary_no_cost(self):
        """无费用时应只显示 token"""
        with patch("cost_tracker.get_daily_summary") as mock_summary:
            mock_summary.return_value = {
                "total_calls": 1, "total_tokens": 500,
                "total_input_tokens": 300, "total_output_tokens": 200,
                "total_cost_usd": None, "by_model": {"unk": {}},
            }
            r = get_user_friendly_summary()
            self.assertIn("token", r.lower())
            self.assertNotIn("$", r)


class TestGetModelPrice(unittest.TestCase):

    def test_exact_match(self):
        self.assertIn("input", _get_model_price("deepseek-chat"))

    def test_unknown_model_returns_price(self):
        self.assertIsNotNone(_get_model_price("unknown-model-v99"))


class TestCalcCost(unittest.TestCase):

    def test_zero_tokens(self):
        self.assertEqual(calc_cost("deepseek-chat", 0, 0), 0)

    def test_known_model(self):
        self.assertGreater(calc_cost("gpt-4o", 1000, 500), 0)


class TestModelPricesConsistency(unittest.TestCase):

    def test_all_prices_positive(self):
        for name, price in MODEL_PRICES.items():
            self.assertGreater(price["input"], 0)
            self.assertGreater(price["output"], 0)
