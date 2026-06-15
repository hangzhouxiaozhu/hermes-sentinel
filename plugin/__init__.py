"""Hermes Sentinel plugin — token usage tracking via post_api_request hook.

Records every LLM API call's prompt/completion tokens to
``~/.hermes/logs/model_cost.log`` via Sentinel's ``cost_tracker``.

Works with all providers and proxy APIs — extracts token counts from
the ``usage`` object in the API response.  Falls back gracefully when
no usage data is present.

Auto-activated by ``install.sh``; no manual setup needed.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict

logger = logging.getLogger("hermes_sentinel")


def _locate_sentinel_scripts() -> str:
    """Locate Sentinel's scripts directory (best-effort)."""
    path = os.path.join(
        os.path.expanduser("~"),
        ".hermes", "skills", "system", "hermes-sentinel", "scripts",
    )
    if os.path.isdir(path) and path not in sys.path:
        sys.path.insert(0, path)
    return path


def _record_token_usage(**kwargs: Any) -> None:
    """``post_api_request`` hook callback — record token usage."""
    usage: Dict[str, Any] = kwargs.get("usage") or {}
    if not usage:
        return

    model = kwargs.get("model") or kwargs.get("response_model") or "unknown"
    api_mode = kwargs.get("api_mode", "unknown")

    _locate_sentinel_scripts()

    try:
        from cost_tracker import extract_usage, record

        # 用 core 的 extract_usage() 统一解析，避免插件侧重复逻辑
        parsed = extract_usage({"usage": usage})
        if parsed.get("confidence") != "high":
            return

        result = record(
            model=model,
            input_tokens=parsed["input_tokens"],
            output_tokens=parsed["output_tokens"],
            task_type=api_mode,
        )
        logger.debug(
            "Recorded: %s | in=%s out=%s cost=%s",
            model, parsed["input_tokens"], parsed["output_tokens"],
            result.get("cost_usd", "N/A"),
        )
    except Exception as exc:
        logger.warning("Failed to record token usage: %s", exc)


def register(ctx) -> None:
    """Register plugin hooks with Hermes."""
    ctx.register_hook("post_api_request", _record_token_usage)
    logger.info(
        "Hermes Sentinel plugin registered: post_api_request → "
        "cost_tracker.extract_usage + record"
    )
