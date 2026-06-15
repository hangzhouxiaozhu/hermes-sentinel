"""
Hermes Sentinel — 成本记账模块

功能: Token 消耗统计，按模型单价计费，自动记录，输出一句话摘要。
被 guardian_core 调用，不直接输出到终端。

价格表维护:
  数据来源: 各 AI 提供商的官方定价页面，见 PROVIDER_SOURCES
  更新方式: 调用 update_prices() 修改 PRICE_TABLE_INFO.last_updated
  自动检测: 每次巡检检查是否过期，过期通知维护者
"""

import json
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from collections import defaultdict

# ── 价格表元信息 ──────────────────────────────────────────
# 维护者每季度核对一次价格，修改时同步更新 last_updated
PRICE_TABLE_INFO = {
    "last_updated": "2026-06",
    "currency": "USD",
    "unit": "per 1K tokens",
    "models_count": 17,
    "latency_months": 3,  # 超过 3 个月未更新视为过期
}

# 各提供商官方定价页面（便于核对）
PROVIDER_SOURCES = {
    "deepseek": "https://api-docs.deepseek.com/quick_start/pricing",
    "openai":   "https://openai.com/api/pricing/",
    "anthropic":"https://www.anthropic.com/pricing",
    "google":   "https://ai.google.dev/pricing",
    "xai":      "https://console.x.ai/",
    "mistral":  "https://mistral.ai/products/la-platform#pricing",
    "kimi":     "https://platform.moonshot.cn/docs/pricing/chat",
}

# ── 配置 ──────────────────────────────────────────────────
HERMES_HOME = Path.home() / ".hermes"
LOG_FILE = HERMES_HOME / "logs" / "model_cost.log"

# 模型价格表 (USD per 1K tokens)
MODEL_PRICES = {
    # DeepSeek
    "deepseek-v4-pro":       {"input": 0.00055, "output": 0.00219},
    "deepseek-v4-flash":     {"input": 0.00014, "output": 0.00055},
    "deepseek-chat":         {"input": 0.00014, "output": 0.00028},
    "deepseek-reasoner":     {"input": 0.00055, "output": 0.00219},

    # OpenAI
    "gpt-4o":                {"input": 0.00250, "output": 0.01000},
    "gpt-4o-mini":           {"input": 0.00015, "output": 0.00060},
    "gpt-4.1":               {"input": 0.00200, "output": 0.00800},
    "o3-mini":               {"input": 0.00110, "output": 0.00440},

    # Anthropic
    "claude-sonnet-4":       {"input": 0.00300, "output": 0.01500},
    "claude-haiku-3.5":      {"input": 0.00080, "output": 0.00400},
    "claude-opus-4":         {"input": 0.01500, "output": 0.07500},

    # Google
    "gemini-2.5-pro":        {"input": 0.00125, "output": 0.01000},
    "gemini-2.5-flash":      {"input": 0.00015, "output": 0.00060},

    # xAI
    "grok-4":                {"input": 0.00200, "output": 0.00800},
    "grok-4.20":             {"input": 0.00200, "output": 0.00800},

    # 其他
    "kimi-k2.6":             {"input": 0.00055, "output": 0.00219},
    "mistral-large":         {"input": 0.00200, "output": 0.00600},
}

# 每日预算上限 (USD)
BUDGET_DAILY_USD = 0.50


# ═══════════════════════════════════════════════════════════
#  价格表生命周期管理
# ═══════════════════════════════════════════════════════════

def get_price_table_info() -> dict:
    """返回价格表元信息"""
    return dict(PRICE_TABLE_INFO)


def get_provider_sources() -> dict:
    """返回各提供商官方定价页面 URL"""
    return dict(PROVIDER_SOURCES)


def is_price_table_stale() -> dict:
    """
    判断价格表是否已过期。

    返回:
    {
        "stale": bool,              # True = 需要更新
        "last_updated": str,         # 格式 "YYYY-MM"
        "months_since_update": int,  # 距上次更新以来的月数
        "latency_months": int,       # 容忍期
        "recommended_update": str,   # 建议更新月份
    }
    """
    lu = PRICE_TABLE_INFO["last_updated"]
    try:
        last = datetime.strptime(lu, "%Y-%m")
    except (ValueError, TypeError):
        return {"stale": True, "last_updated": lu, "months_since_update": 999,
                "latency_months": PRICE_TABLE_INFO["latency_months"],
                "recommended_update": datetime.now().strftime("%Y-%m")}

    now = datetime.now()
    elapsed = (now.year - last.year) * 12 + (now.month - last.month)
    stale = elapsed > PRICE_TABLE_INFO["latency_months"]

    return {
        "stale": stale,
        "last_updated": lu,
        "months_since_update": elapsed,
        "latency_months": PRICE_TABLE_INFO["latency_months"],
        "recommended_update": now.strftime("%Y-%m"),
    }


def update_prices(new_prices: dict, updated_month: str = None) -> dict:
    """
    更新模型价格表。

    参数:
        new_prices: {model_name: {"input": float, "output": float}, ...}
        updated_month: "YYYY-MM" 格式，默认当前月份

    返回:
        {"updated": int, "added": int, "total": int, "last_updated": str}
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

    new_date = updated_month or datetime.now().strftime("%Y-%m")
    PRICE_TABLE_INFO["last_updated"] = new_date
    PRICE_TABLE_INFO["models_count"] = len(MODEL_PRICES)

    return {
        "updated": updated,
        "added": added,
        "total": len(MODEL_PRICES),
        "last_updated": new_date,
    }


# ═══════════════════════════════════════════════════════════
#  价格查询与计费
# ═══════════════════════════════════════════════════════════

def get_model_price(model_name):
    """
    获取模型价格，支持精确匹配和部分匹配。

    精确匹配优先 → 部分匹配降级 → unknown 模型用保守价格（flash 级）。
    """
    if model_name in MODEL_PRICES:
        return MODEL_PRICES[model_name]

    model_lower = model_name.lower()
    for key, price in MODEL_PRICES.items():
        if key.lower() in model_lower or model_lower in key.lower():
            return price

    return MODEL_PRICES["deepseek-v4-flash"]


def get_known_models() -> list:
    """返回已知模型名称列表"""
    return sorted(MODEL_PRICES.keys())


def calc_cost(model, input_tokens, output_tokens):
    """计算费用 (USD)"""
    price = get_model_price(model)
    input_cost = input_tokens / 1000 * price["input"]
    output_cost = output_tokens / 1000 * price["output"]
    return round(input_cost + output_cost, 6)


# ═══════════════════════════════════════════════════════════
#  记录与汇总
# ═══════════════════════════════════════════════════════════

def record(model, input_tokens, output_tokens, task_type="unknown") -> dict:
    """
    记录一次 API 调用（静默写入日志）。

    返回:
        {"recorded": bool, "over_budget": bool, "cost_usd": float,
         "price_stale": bool}  # price_stale 供 guardian_core 判断
    """
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    cost = calc_cost(model, input_tokens, output_tokens)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cost_usd": cost,
        "task_type": task_type,
    }

    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    today_cost = _today_cost()
    over = today_cost > BUDGET_DAILY_USD
    stale = is_price_table_stale()["stale"]

    return {"recorded": True, "over_budget": over, "cost_usd": cost, "price_stale": stale}


def _today_cost() -> float:
    """计算今日总花费"""
    today = str(date.today())
    total = 0.0
    if not LOG_FILE.exists():
        return 0

    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if e.get("timestamp", "")[:10] == today:
                    total += e.get("cost_usd", 0)
            except Exception:
                continue
    return total


# ═══════════════════════════════════════════════════════════
#  报表输出
# ═══════════════════════════════════════════════════════════

def get_daily_summary(target_date=None) -> dict:
    """获取指定日期的汇总（结构化，给 guardian_core/日志用）"""
    if target_date is None:
        target_date = date.today()

    if not LOG_FILE.exists():
        return {"date": str(target_date), "total_calls": 0, "total_cost_usd": 0, "by_model": {}}

    models = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0})
    total_calls = 0

    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = entry.get("timestamp", "")[:10]
                if ts != str(target_date):
                    continue

                model = entry.get("model", "unknown")
                models[model]["calls"] += 1
                models[model]["input_tokens"] += entry.get("input_tokens", 0)
                models[model]["output_tokens"] += entry.get("output_tokens", 0)
                models[model]["cost_usd"] += entry.get("cost_usd", 0)
                total_calls += 1
            except Exception:
                continue

    total_cost = round(sum(m["cost_usd"] for m in models.values()), 6)
    total_input = sum(m["input_tokens"] for m in models.values())
    total_output = sum(m["output_tokens"] for m in models.values())

    return {
        "date": str(target_date),
        "total_calls": total_calls,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "total_cost_usd": total_cost,
        "total_cost_cny": round(total_cost * 7.25, 2),
        "by_model": dict(models),
    }


def get_user_friendly_summary() -> str:
    """
    生成一句话成本摘要（给 narrator 用）。

    返回:
        str — 如有过时价格表，追加在末尾
    """
    today = get_daily_summary()
    if today["total_calls"] == 0:
        return ""

    cost = today["total_cost_usd"]
    calls = today["total_calls"]

    stale = is_price_table_stale()
    suffix = ""
    if stale["stale"]:
        suffix = f"（注意：价格表上次更新于 {stale['last_updated']}，已有 {stale['months_since_update']} 个月，费用可能不准确）"

    if cost >= BUDGET_DAILY_USD:
        return f"今天 API 花了 ${cost:.2f}，快到预算了（${BUDGET_DAILY_USD:.2f}）。{suffix}"
    if cost >= BUDGET_DAILY_USD * 0.5:
        return f"今天花了 ${cost:.4f} 美元（已到预算的一半）。{suffix}"
    return f"花了 ${cost:.4f} 美元。{suffix}"
