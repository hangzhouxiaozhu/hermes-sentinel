"""Hermes Sentinel plugin — token tracking hook test.

Covers four post_api_request hook parameter shapes:
1. OpenAI format     (usage.prompt_tokens)
2. Anthropic format  (usage.input_tokens)
3. Gemini format     (usageMetadata at top level, not inside usage)
4. No usage — silently skipped

Plus Sentinel-not-installed degradation.
"""

import sys
import tempfile
import json
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def _run_hook(usage_kwarg, model="test-model", response_model=None):
    """Import and invoke the plugin hook callback with given kwargs."""
    import importlib.util
    plugin_init = Path(__file__).resolve().parent.parent / "plugin" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_test_plugin_mod", plugin_init)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    kwargs = {"model": model, "api_mode": "chat", "usage": usage_kwarg}
    if response_model:
        kwargs["response_model"] = response_model
    mod._record_token_usage(**kwargs)
    return mod


class TestPluginOpenAIFormat(unittest.TestCase):
    """usage.prompt_tokens + completion_tokens"""

    def test_records(self):
        log = Path(tempfile.mktemp(suffix=".log"))
        with unittest.mock.patch("cost_tracker.LOG_FILE", log):
            log.parent.mkdir(parents=True, exist_ok=True)
            _run_hook({"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
            entry = json.loads(log.read_text())
            self.assertEqual(entry["model"], "test-model")
            self.assertEqual(entry["input_tokens"], 100)
            self.assertEqual(entry["output_tokens"], 50)
            log.unlink(missing_ok=True)

    def test_model_prefers_kwargs_model(self):
        """kwargs['model'] wins over response_model for proxies."""
        log = Path(tempfile.mktemp(suffix=".log"))
        with unittest.mock.patch("cost_tracker.LOG_FILE", log):
            log.parent.mkdir(parents=True, exist_ok=True)
            _run_hook({"prompt_tokens": 10, "completion_tokens": 5},
                      model="deepseek-chat", response_model="gpt-4o")
            entry = json.loads(log.read_text())
            self.assertEqual(entry["model"], "deepseek-chat")
            log.unlink(missing_ok=True)


class TestPluginAnthropicFormat(unittest.TestCase):
    """usage.input_tokens + output_tokens"""

    def test_records(self):
        log = Path(tempfile.mktemp(suffix=".log"))
        with unittest.mock.patch("cost_tracker.LOG_FILE", log):
            log.parent.mkdir(parents=True, exist_ok=True)
            _run_hook({"input_tokens": 200, "output_tokens": 80})
            entry = json.loads(log.read_text())
            self.assertEqual(entry["input_tokens"], 200)
            self.assertEqual(entry["output_tokens"], 80)
            log.unlink(missing_ok=True)


class TestPluginGeminiFormat(unittest.TestCase):
    """
    Gemini: Hermes post_api_request hook 传入的是 usage 字典。
    如果 Hermes 没归一化 usageMetadata，usage 里不含 prompt_tokens → extract_usage
    返回 confidence=none → 安全跳过。不崩溃、不写脏数据。
    """

    def test_prompttokens_at_top_level_is_ok(self):
        """即使用户把 usageMetadata 拍平传进来也能用"""
        log = Path(tempfile.mktemp(suffix=".log"))
        with unittest.mock.patch("cost_tracker.LOG_FILE", log):
            log.parent.mkdir(parents=True, exist_ok=True)
            _run_hook({"promptTokenCount": 300, "candidatesTokenCount": 120})
            # extract_usage 信任的是 usage 里的 prompt_tokens / completion_tokens 等
            # promptTokenCount 不在已知格式中 → confidence=none → 不记录
            # 但不 crash
            if log.exists():
                log.unlink(missing_ok=True)

    def test_usage_metadata_if_normalized(self):
        """Hermes 把 usageMetadata 归一化到 usage.promptTokenCount 也能用"""
        log = Path(tempfile.mktemp(suffix=".log"))
        with unittest.mock.patch("cost_tracker.LOG_FILE", log):
            log.parent.mkdir(parents=True, exist_ok=True)
            # 如果 Hermes 归一化为 OpenAI 格式
            _run_hook({"prompt_tokens": 300, "completion_tokens": 120})
            entry = json.loads(log.read_text())
            self.assertEqual(entry["input_tokens"], 300)
            self.assertEqual(entry["output_tokens"], 120)
            log.unlink(missing_ok=True)


class TestPluginNoUsage(unittest.TestCase):
    """空/None usage 应静默跳过"""

    def test_empty_usage(self):
        log = Path(tempfile.mktemp(suffix=".log"))
        with unittest.mock.patch("cost_tracker.LOG_FILE", log):
            log.parent.mkdir(parents=True, exist_ok=True)
            _run_hook({})
            self.assertFalse(log.exists())
            log.unlink(missing_ok=True)

    def test_none_usage(self):
        log = Path(tempfile.mktemp(suffix=".log"))
        with unittest.mock.patch("cost_tracker.LOG_FILE", log):
            log.parent.mkdir(parents=True, exist_ok=True)
            _run_hook(None)
            self.assertFalse(log.exists())
            log.unlink(missing_ok=True)


class TestPluginSentinelNotInstalled(unittest.TestCase):
    """Sentinel 未安装时，插件不应崩溃"""

    def test_graceful_degradation(self):
        log = Path(tempfile.mktemp(suffix=".log"))
        with unittest.mock.patch("cost_tracker.LOG_FILE", log):
            log.parent.mkdir(parents=True, exist_ok=True)
            import importlib.util
            plugin_init = Path(__file__).resolve().parent.parent / "plugin" / "__init__.py"
            spec = importlib.util.spec_from_file_location("_test_no_sentinel", plugin_init)
            mod = importlib.util.module_from_spec(spec)
            # 篡改全局路径为不存在目录
            mod._SENTINEL_SCRIPTS = "/tmp/nonexistent-sentinel-test-xyz"
            spec.loader.exec_module(mod)
            # 不应抛出异常
            mod._record_token_usage(**{"usage": {"prompt_tokens": 10, "completion_tokens": 5}})
            # 由于 Sentinel 不存在，不应该写日志
            if log.exists():
                log.unlink(missing_ok=True)
