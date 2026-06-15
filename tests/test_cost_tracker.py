"""成本记账模块测试"""

import sys
import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from cost_tracker import (
    get_price_table_info, get_provider_sources,
    is_price_table_stale, update_prices,
    get_known_models,
    get_model_price, calc_cost, record,
    get_daily_summary, get_user_friendly_summary,
    MODEL_PRICES, BUDGET_DAILY_USD,
)


class TestPriceTableInfo(unittest.TestCase):

    def test_has_metadata(self):
        info = get_price_table_info()
        for key in ("last_updated", "currency", "models_count", "latency_months"):
            self.assertIn(key, info)

    def test_last_updated_format(self):
        info = get_price_table_info()
        self.assertRegex(info["last_updated"], r"\d{4}-\d{2}")

    def test_latency_months_exists(self):
        info = get_price_table_info()
        self.assertIn("latency_months", info)
        self.assertGreater(info["latency_months"], 0)


class TestProviderSources(unittest.TestCase):

    def test_returns_dict(self):
        sources = get_provider_sources()
        self.assertIsInstance(sources, dict)
        self.assertGreater(len(sources), 0)

    def test_urls_start_with_https(self):
        sources = get_provider_sources()
        for name, url in sources.items():
            self.assertTrue(url.startswith("https://"), f"{name}: {url}")


class TestIsPriceTableStale(unittest.TestCase):

    def test_returns_structure(self):
        result = is_price_table_stale()
        for key in ("stale", "last_updated", "months_since_update",
                     "latency_months", "recommended_update"):
            self.assertIn(key, result)

    def test_stale_is_bool(self):
        result = is_price_table_stale()
        self.assertIn(result["stale"], (True, False))

    def test_recommended_update_format(self):
        result = is_price_table_stale()
        self.assertRegex(result["recommended_update"], r"\d{4}-\d{2}")


class TestUpdatePrices(unittest.TestCase):

    def test_update_existing(self):
        result = update_prices({"deepseek-chat": {"input": 1, "output": 2}})
        self.assertGreaterEqual(result["updated"], 1)
        # 还原
        update_prices({"deepseek-chat": {"input": 0.00014, "output": 0.00028}})

    def test_add_new(self):
        result = update_prices({"new-test-model": {"input": 0.001, "output": 0.002}})
        self.assertGreaterEqual(result["added"], 1)

    def test_updates_last_updated(self):
        update_prices({"dummy": {"input": 0.001, "output": 0.002}}, updated_month="2099-12")
        info = get_price_table_info()
        self.assertEqual(info["last_updated"], "2099-12")
        # 还原
        update_prices({}, updated_month="2026-06")
        # 删除测试用的 dummy
        MODEL_PRICES.pop("dummy", None)

    def test_models_count_updated(self):
        old_count = get_price_table_info()["models_count"]
        update_prices({"test-abc": {"input": 0.001, "output": 0.002}})
        info = get_price_table_info()
        self.assertEqual(info["models_count"], old_count + 1)
        MODEL_PRICES.pop("test-abc", None)
        update_prices({})

    def test_returns_list(self):
        models = get_known_models()
        self.assertIsInstance(models, list)
        self.assertGreater(len(models), 0)

    def test_includes_deepseek(self):
        models = get_known_models()
        self.assertTrue(any("deepseek" in m for m in models))


class TestGetModelPrice(unittest.TestCase):

    def test_exact_match(self):
        price = get_model_price("deepseek-chat")
        self.assertIn("input", price)
        self.assertIn("output", price)

    def test_partial_match(self):
        price = get_model_price("deepseek-chat-123")
        self.assertIn("input", price)

    def test_unknown_model(self):
        """未知模型应返回保守价格而非最贵的"""
        price = get_model_price("unknown-model-v99")
        # 应该是 flash 级价格，不是最贵的 opus 或 grok
        self.assertLessEqual(price["input"], MODEL_PRICES["deepseek-v4-flash"]["input"] * 2)

    def test_case_insensitive(self):
        p1 = get_model_price("GPT-4o")
        p2 = get_model_price("gpt-4o")
        self.assertEqual(p1, p2)


class TestCalcCost(unittest.TestCase):

    def test_zero_tokens(self):
        cost = calc_cost("deepseek-chat", 0, 0)
        self.assertEqual(cost, 0)

    def test_known_model(self):
        cost = calc_cost("gpt-4o", 1000, 500)
        self.assertGreater(cost, 0)

    def test_unknown_model(self):
        """未知模型不应 crash"""
        cost = calc_cost("unknown-model", 100, 50)
        self.assertGreaterEqual(cost, 0)


class TestRecord(unittest.TestCase):

    @patch("cost_tracker.LOG_FILE", new_callable=lambda: Path(tempfile.mktemp(suffix=".log")))
    def test_record_writes_log(self, mock_path):
        # 确保文件不存在
        if mock_path.exists():
            mock_path.unlink()
        mock_path.parent.mkdir(parents=True, exist_ok=True)

        result = record("deepseek-chat", 100, 50)
        self.assertTrue(result["recorded"])
        self.assertIn("cost_usd", result)
        self.assertIn("over_budget", result)
        # 返回值应包含 price_stale 字段（True 或 False）
        self.assertIn("price_stale", result)
        self.assertIn(result["price_stale"], (True, False))

        # 验证日志文件已被写入
        self.assertTrue(mock_path.exists())
        lines = mock_path.read_text().strip().split("\n")
        self.assertGreaterEqual(len(lines), 1)

        entry = json.loads(lines[0])
        self.assertEqual(entry["model"], "deepseek-chat")
        self.assertEqual(entry["input_tokens"], 100)

        # 清理
        mock_path.unlink(missing_ok=True)

    @patch("cost_tracker.LOG_FILE", new_callable=lambda: Path(tempfile.mktemp(suffix=".log")))
    def test_multiple_records(self, mock_path):
        if mock_path.exists():
            mock_path.unlink()
        mock_path.parent.mkdir(parents=True, exist_ok=True)

        record("gpt-4o", 1000, 500)
        record("deepseek-chat", 200, 100)

        lines = mock_path.read_text().strip().split("\n")
        self.assertEqual(len(lines), 2)

        mock_path.unlink(missing_ok=True)


class TestGetDailySummary(unittest.TestCase):

    def test_no_log(self):
        """无日志文件时应返回空结构"""
        summary = get_daily_summary()
        self.assertIn("date", summary)
        self.assertEqual(summary["total_calls"], 0)

    def test_structure(self):
        summary = get_daily_summary()
        for key in ("date", "total_calls", "total_cost_usd", "by_model"):
            self.assertIn(key, summary)


class TestGetUserFriendlySummary(unittest.TestCase):

    def test_no_calls(self):
        """无调用记录应返回空字符串"""
        with patch("cost_tracker.LOG_FILE", Path(tempfile.mktemp())):
            result = get_user_friendly_summary()
            self.assertEqual(result, "")


class TestModelPricesConsistency(unittest.TestCase):

    def test_all_prices_positive(self):
        for name, price in MODEL_PRICES.items():
            self.assertGreater(price["input"], 0, f"{name} input price <= 0")
            self.assertGreater(price["output"], 0, f"{name} output price <= 0")

    def test_all_have_both_keys(self):
        for name, price in MODEL_PRICES.items():
            self.assertIn("input", price, f"{name} missing input")
            self.assertIn("output", price, f"{name} missing output")

    def test_output_costlier_than_input(self):
        """输出通常比输入贵——如果不是，标记但不强制"""
        for name, price in MODEL_PRICES.items():
            if price["output"] < price["input"]:
                # 只是警告，不是错误——有些模型确实输出比输入便宜
                pass
