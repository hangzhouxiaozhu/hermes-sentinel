"""Hermes Sentinel plugin — token usage tracking via post_api_request hook.

Records every LLM API call's prompt/completion tokens to
``~/.hermes/logs/model_cost.log`` via Sentinel's ``cost_tracker``.

Works with all providers and proxy APIs — only depends on the ``usage``
object that every OpenAI-compatible response includes.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict

logger = logging.getLogger("hermes_sentinel")


def _track_usage(**kwargs: Any) -> None:
    """``post_api_request`` hook callback — record token usage."""
    usage: Dict[str, Any] = kwargs.get("usage") or {}
    prompt = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
    completion = usage.get("completion_tokens") or usage.get("output_tokens") or 0

    if not prompt and not completion:
        return  # no usage data, nothing to record

    model = kwargs.get("response_model") or kwargs.get("model") or "unknown"
    api_mode = kwargs.get("api_mode", "unknown")

    # ── locate Sentinel's cost_tracker ──────────────────────────
    _sentinel_scripts = os.path.join(
        os.path.expanduser("~"),
        ".hermes", "skills", "system", "hermes-sentinel", "scripts",
    )
    if not os.path.isdir(_sentinel_scripts):
        logger.debug("Sentinel scripts not found at %s", _sentinel_scripts)
        return

    if _sentinel_scripts not in sys.path:
        sys.path.insert(0, _sentinel_scripts)

    try:
        from cost_tracker import record

        result = record(
            model=model,
            input_tokens=int(prompt),
            output_tokens=int(completion),
            task_type=api_mode,
        )
        logger.debug(
            "Recorded: %s | in=%s out=%s cost=%s",
            model, prompt, completion, result.get("cost_usd", "N/A"),
        )
    except Exception as exc:
        logger.warning("Failed to record token usage: %s", exc)


def register(ctx) -> None:
    """Register plugin hooks with Hermes."""
    ctx.register_hook("post_api_request", _track_usage)
    logger.info("Hermes Sentinel plugin registered: post_api_request → cost_tracker.record")
