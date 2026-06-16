"""Token stats & cost estimation tests.

Default state: no price table → cost_usd=None.
Tests that verify cost calculation use update_prices() to enable it.
"""

import sys
import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from cost_tracker import (
    get_known_models,
    calc_cost, record, extract_usage, record_from_response, update_prices,
    get_daily_summary, get_user_friendly_summary,
    MODEL_PRICES, BUDGET_DAILY_USD,
)


class TestExtractUsage(unittest.TestCase):
    """Token extraction from API responses (core feature, always works)."""

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
        # Default: no price table → cost_usd is None
        self.assertIsNone(r["cost_usd"])

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


class TestGetDailySummary(unittest.TestCase):

    def test_no_log(self):
        with patch("cost_tracker.LOG_FILE", Path(tempfile.mktemp())):
            s = get_daily_summary()
            self.assertEqual(s["total_calls"], 0)
            self.assertEqual(s["total_tokens"], 0)


class TestGetUserFriendlySummary(unittest.TestCase):

    def test_no_calls_empty(self):
        with patch("cost_tracker.LOG_FILE", Path(tempfile.mktemp())):
            r = get_user_friendly_summary()
            self.assertEqual(r, "")

    def test_summary_format_with_mock(self):
        with patch("cost_tracker.get_daily_summary") as mock_summary:
            mock_summary.return_value = {
                "total_calls": 3, "total_tokens": 1500,
                "total_input_tokens": 1000, "total_output_tokens": 500,
                "total_cost_usd": None, "by_model": {"gpt-4o": {}},
            }
            r = get_user_friendly_summary()
            self.assertIn("token", r.lower())
            self.assertNotIn("$", r)

    def test_summary_no_cost(self):
        with patch("cost_tracker.get_daily_summary") as mock_summary:
            mock_summary.return_value = {
                "total_calls": 1, "total_tokens": 500,
                "total_input_tokens": 300, "total_output_tokens": 200,
                "total_cost_usd": None, "by_model": {"unk": {}},
            }
            r = get_user_friendly_summary()
            self.assertIn("token", r.lower())
            self.assertNotIn("$", r)


class TestCalcCostDefaultEmpty(unittest.TestCase):

    def test_no_price_table_returns_none(self):
        """Without prices, calc_cost returns None."""
        self.assertIsNone(calc_cost("gpt-4o", 1000, 500))

    def test_record_cost_is_none_by_default(self):
        with patch("cost_tracker.LOG_FILE", Path(tempfile.mktemp(suffix=".log"))) as mock_path:
            mock_path.parent.mkdir(parents=True, exist_ok=True)
            r = record("gpt-4o", 100, 50)
            self.assertIsNone(r["cost_usd"])
            mock_path.unlink(missing_ok=True)

    def test_record_cost_has_value_after_update_prices(self):
        """After update_prices(), cost_usd is calculated."""
        with patch("cost_tracker.LOG_FILE", Path(tempfile.mktemp(suffix=".log"))) as mock_path:
            mock_path.parent.mkdir(parents=True, exist_ok=True)
            update_prices({"gpt-4o": {"input": 0.0025, "output": 0.01}})
            r = record("gpt-4o", 1000, 500)
            self.assertIsNotNone(r["cost_usd"])
            self.assertGreater(r["cost_usd"], 0)
            # Restore empty
            update_prices({})
            mock_path.unlink(missing_ok=True)


class TestUpdatePrices(unittest.TestCase):

    def test_update_adds_model(self):
        update_prices({"test-model": {"input": 0.001, "output": 0.002}})
        cost = calc_cost("test-model", 1000, 500)
        self.assertIsNotNone(cost)
        self.assertGreater(cost, 0)
        update_prices({})

    def test_update_replaces_model(self):
        update_prices({"gpt-4o": {"input": 1, "output": 2}})
        cost = calc_cost("gpt-4o", 1, 1)
        self.assertEqual(cost, 0.003)
        update_prices({})
        self.assertIsNone(calc_cost("gpt-4o", 1, 1))
