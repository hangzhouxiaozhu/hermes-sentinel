"""
Hermes Sentinel — Token 统计与费用估算

核心功能：统计 API 调用消耗的 token 数（来自真实响应体，普适）。
附加功能：如需费用估算，自行设置 MODEL_PRICES，否则不计费。

设计原则：
  - token 统计是核心，所有 API 返回体都包含 token 数，与提供商无关
  - 费用估算是附加，需要维护价格表，中转 API 用户可不配置
  - 没有价格表时，token 统计仍正常工作，费用字段为 None
"""

import json
from datetime import datetime, timezone, date
from pathlib import Path
from collections import defaultdict

# ── 价格表 ────────────────────────────────────────────────
# 可选配置。不设置或设为空字典 {} 则不计费，只统计 token。
# 价格表由 maintainer 维护，详见 update_prices()。
MODEL_PRICES = {
    "deepseek-v4-pro":       {"input": 0.00055, "output": 0.00219},
    "deepseek-v4-flash":     {"input": 0.00014, "output": 0.00055},
    "deepseek-chat":         {"input": 0.00014, "output": 0.00028},
    "deepseek-reasoner":     {"input": 0.00055, "output": 0.00219},
    "gpt-4o":                {"input": 0.00250, "output": 0.01000},
    "gpt-4o-mini":           {"input": 0.00015, "output": 0.00060},
    "gpt-4.1":               {"input": 0.00200, "output": 0.00800},
    "o3-mini":               {"input": 0.00110, "output": 0.00440},
    "claude-sonnet-4":       {"input": 0.00300, "output": 0.01500},
    "claude-haiku-3.5":      {"input": 0.00080, "output": 0.00400},
    "claude-opus-4":         {"input": 0.01500, "output": 0.07500},
    "gemini-2.5-pro":        {"input": 0.00125, "output": 0.01000},
    "gemini-2.5-flash":      {"input": 0.00015, "output": 0.00060},
    "grok-4":                {"input": 0.00200, "output": 0.00800},
    "grok-4.20":             {"input": 0.00200, "output": 0.00800},
    "kimi-k2.6":             {"input": 0.00055, "output": 0.00219},
    "mistral-large":         {"input": 0.00200, "output": 0.00600},
}

HERMES_HOME = Path.home() / ".hermes"
LOG_FILE = HERMES_HOME / "logs" / "model_cost.log"
BUDGET_DAILY_USD = 0.50


def _has_price_table() -> bool:
    """检查是否有可用的价格表"""
    return bool(MODEL_PRICES)


def _get_model_price(model_name):
    """获取模型价格，无价格表时返回 None"""
    if not MODEL_PRICES:
        return None
    if model_name in MODEL_PRICES:
        return MODEL_PRICES[model_name]
    model_lower = model_name.lower()
    for key, price in MODEL_PRICES.items():
        if key.lower() in model_lower or model_lower in key.lower():
            return price
    return None


def calc_cost(model, input_tokens, output_tokens):
    """
    计算费用 (USD)。无价格表时返回 None。
    """
    price = _get_model_price(model)
    if price is None:
        return None
    input_cost = input_tokens / 1000 * price["input"]
    output_cost = output_tokens / 1000 * price["output"]
    return round(input_cost + output_cost, 6)


# ═══════════════════════════════════════════════════════════
#  从 API 响应中提取 token 数（核心功能）
# ═══════════════════════════════════════════════════════════

def extract_usage(response: dict, model: str = "") -> dict:
    """
    从 API 返回体中提取 token 消耗数。

    支持主流格式：
    - OpenAI / DeepSeek / OpenRouter / 多数中转:
      response.usage.prompt_tokens + completion_tokens
    - Anthropic:      response.usage.input_tokens + output_tokens
    - Google Gemini:  response.usageMetadata.promptTokenCount + candidatesTokenCount
    - 通用平铺:       response.prompt_tokens + completion_tokens
    """
    if not isinstance(response, dict):
        return {"input_tokens": 0, "output_tokens": 0,
                "confidence": "none", "error": "response is not a dict"}

    # OpenAI / DeepSeek / 大部分中转
    usage = response.get("usage")
    if isinstance(usage, dict):
        inp = usage.get("prompt_tokens")
        out = usage.get("completion_tokens")
        if isinstance(inp, (int, float)) and isinstance(out, (int, float)):
            return {"input_tokens": int(inp), "output_tokens": int(out),
                    "source": "openai", "confidence": "high"}

    # Anthropic
    if isinstance(usage, dict):
        inp = usage.get("input_tokens")
        out = usage.get("output_tokens")
        if isinstance(inp, (int, float)) and isinstance(out, (int, float)):
            return {"input_tokens": int(inp), "output_tokens": int(out),
                    "source": "anthropic", "confidence": "high"}

    # Gemini
    meta = response.get("usageMetadata")
    if isinstance(meta, dict):
        inp = meta.get("promptTokenCount")
        out = meta.get("candidatesTokenCount")
        if isinstance(inp, (int, float)) and isinstance(out, (int, float)):
            return {"input_tokens": int(inp), "output_tokens": int(out),
                    "source": "gemini", "confidence": "high"}

    # 通用平铺格式
    inp = response.get("prompt_tokens")
    out = response.get("completion_tokens")
    if isinstance(inp, (int, float)) and isinstance(out, (int, float)):
        return {"input_tokens": int(inp), "output_tokens": int(out),
                "source": "common_count_tokens", "confidence": "high"}

    return {"input_tokens": 0, "output_tokens": 0, "confidence": "none",
            "error": "无法从响应体中提取 token 数据",
            "response_keys": list(response.keys())[:10]}


# ═══════════════════════════════════════════════════════════
#  记录（核心：token；附加：费用）
# ═══════════════════════════════════════════════════════════

def record(model, input_tokens, output_tokens, task_type="unknown") -> dict:
    """
    记录一次 API 调用。

    核心数据：model、input_tokens、output_tokens（永远有值）。
    附加数据：cost_usd（仅在有价格表时计算，否则为 None）。

    返回:
        {"recorded": bool, "input_tokens": int, "output_tokens": int,
         "cost_usd": float|None}  # None = 无价格表或不计费
    """
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    cost = calc_cost(model, input_tokens, output_tokens)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "task_type": task_type,
    }
    if cost is not None:
        entry["cost_usd"] = cost

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {"recorded": True, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "cost_usd": cost}


def record_from_response(response: dict, model: str, task_type: str = "unknown") -> dict:
    """
    从 API 响应体中提取 token 并记录（推荐入口）。

    token 数来自真实响应体，不依赖调用方估算，适用于所有 API 提供商和中转。

    返回:
        {"recorded": bool, "input_tokens": int, "output_tokens": int,
         "cost_usd": float|None, "usage_source": str|None}
    """
    usage = extract_usage(response, model)
    if usage.get("confidence") == "high":
        r = record(model=model, input_tokens=usage["input_tokens"],
                   output_tokens=usage["output_tokens"], task_type=task_type)
        r["usage_source"] = usage.get("source")
        return r

    # fallback：尝试从顶层 key 中读取
    inp = response.get("input_tokens") or response.get("prompt_tokens") or 0
    out = response.get("output_tokens") or response.get("completion_tokens") or 0
    if isinstance(inp, (int, float)) and isinstance(out, (int, float)) and (inp > 0 or out > 0):
        r = record(model=model, input_tokens=int(inp), output_tokens=int(out), task_type=task_type)
        r["usage_source"] = "fallback_keys"
        return r

    return {"recorded": False, "input_tokens": 0, "output_tokens": 0,
            "cost_usd": None, "usage_source": None,
            "error": "response contains no token usage data"}


# ═══════════════════════════════════════════════════════════
#  价格表维护（可选功能，中转用户无需操心）
# ═══════════════════════════════════════════════════════════

PRICE_TABLE_INFO = {
    "available": _has_price_table(),
    "last_updated": "2026-06",
    "models_count": len(MODEL_PRICES),
}

PROVIDER_SOURCES = {
    "deepseek": "https://api-docs.deepseek.com/quick_start/pricing",
    "openai":   "https://openai.com/api/pricing/",
    "anthropic":"https://www.anthropic.com/pricing",
    "google":   "https://ai.google.dev/pricing",
    "xai":      "https://console.x.ai/",
    "mistral":  "https://mistral.ai/products/la-platform#pricing",
    "kimi":     "https://platform.moonshot.cn/docs/pricing/chat",
}


def get_known_models() -> list:
    return sorted(MODEL_PRICES.keys())


def update_prices(new_prices: dict) -> dict:
    """
    更新模型价格表。不设置价格表时，费用计算始终返回 None。
    """
    global MODEL_PRICES, PRICE_TABLE_INFO
    updated = 0
    added = 0
    for name, price in new_prices.items():
        if name in MODEL_PRICES:
            updated += 1
        else:
            added += 1
        MODEL_PRICES[name] = price
    PRICE_TABLE_INFO["models_count"] = len(MODEL_PRICES)
    PRICE_TABLE_INFO["last_updated"] = datetime.now().strftime("%Y-%m")
    return {"updated": updated, "added": added, "total": len(MODEL_PRICES)}


# ═══════════════════════════════════════════════════════════
#  报表（优先 token，费用可选）
# ═══════════════════════════════════════════════════════════

def get_daily_summary(target_date=None) -> dict:
    """
    获取指定日期的汇总。

    通用字段：date、total_calls、total_tokens
    token 字段：total_input_tokens、total_output_tokens（永远有值）
    费用字段：total_cost_usd（仅 MODELS_PRICES 有价格时才有，否则为 None）
    """
    if target_date is None:
        target_date = date.today()

    if not LOG_FILE.exists():
        return {"date": str(target_date), "total_calls": 0,
                "total_tokens": 0, "total_cost_usd": None, "by_model": {}}

    models = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0})
    has_any_cost = False
    total_calls = 0

    with open(LOG_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if e.get("timestamp", "")[:10] != str(target_date):
                    continue
                model = e.get("model", "unknown")
                models[model]["calls"] += 1
                models[model]["input_tokens"] += e.get("input_tokens", 0)
                models[model]["output_tokens"] += e.get("output_tokens", 0)
                model_cost = e.get("cost_usd")
                if model_cost is not None:
                    models[model]["cost_usd"] += model_cost
                    has_any_cost = True
                total_calls += 1
            except Exception:
                continue

    total_input = sum(m["input_tokens"] for m in models.values())
    total_output = sum(m["output_tokens"] for m in models.values())

    result = {
        "date": str(target_date),
        "total_calls": total_calls,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "by_model": dict(models),
    }
    if has_any_cost:
        total_cost = round(sum(m["cost_usd"] for m in models.values()), 6)
        result["total_cost_usd"] = total_cost
        result["total_cost_cny"] = round(total_cost * 7.25, 2)
    else:
        result["total_cost_usd"] = None

    return result


def get_user_friendly_summary() -> str:
    """
    生成一句话摘要（给 narrator 用）。

    示例:
      "今天用了 15000 个 token（入 10000 出 5000）。"
      "今天用了 15000 个 token，花了 $0.08。"
    """
    today = get_daily_summary()
    if today["total_calls"] == 0:
        return ""

    total = today["total_tokens"]
    inp = today["total_input_tokens"]
    out = today["total_output_tokens"]
    calls = today["total_calls"]
    cost = today.get("total_cost_usd")

    # 核心：token 统计（永远有）
    if total >= 1_000_000:
        token_part = f"今天用了 {total/1_000_000:.1f}M token（{calls} 次调用）"
    elif total >= 1_000:
        token_part = f"今天用了 {total/1_000:.0f}K token（入 {inp/1_000:.0f}K 出 {out/1_000:.0f}K，{calls} 次调用）"
    else:
        token_part = f"今天用了 {total} 个 token（{calls} 次调用）"

    # 附加：费用（仅有价格表时）
    if cost is not None and cost > 0:
        if cost >= BUDGET_DAILY_USD:
            return f"{token_part}，花了 ${cost:.2f}（已到预算 ${BUDGET_DAILY_USD:.2f}）。"
        return f"{token_part}，花了 ${cost:.4f}。"
    else:
        return f"{token_part}。"
