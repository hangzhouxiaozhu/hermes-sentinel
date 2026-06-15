"""
Hermes Guardian — 综合报告生成器 (Phase 2)

功能: 生成每日/按需的综合报告。
被 guardian_core.guardian_daily_report() 调用，不直接输出到终端。
"""

import json
from datetime import datetime, date
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"


def hardware_summary():
    """读取最近硬件巡检日志，生成摘要"""
    log_file = HERMES_HOME / "logs" / "hardware_monitor.log"
    if not log_file.exists():
        return {"status": "no_data"}

    entries = []
    try:
        with open(log_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        continue
    except Exception:
        return {"status": "no_data"}

    if not entries:
        return {"status": "no_data"}

    recent = entries[-144:]
    levels = {"normal": 0, "warn": 0, "danger": 0}
    mem_peak = 0
    swap_peak = 0
    cpu_peak = 0

    for e in recent:
        level = e.get("level", "normal")
        levels[level] = levels.get(level, 0) + 1
        mem = e.get("memory", {}).get("memory_pct", 0)
        swap = e.get("memory", {}).get("swap_pct", 0)
        cpu = e.get("cpu", {}).get("load_1min", 0)
        if mem > mem_peak: mem_peak = mem
        if swap > swap_peak: swap_peak = swap
        if cpu > cpu_peak: cpu_peak = cpu

    latest = entries[-1] if entries else {}
    mem_now = latest.get("memory", {})

    return {
        "status": "ok",
        "samples": len(recent),
        "memory_now": f"{mem_now.get('used_gb', 0)}/{mem_now.get('total_gb', 0)} GB ({mem_now.get('memory_pct', 0)}%)",
        "memory_peak": f"{mem_peak}%",
        "swap_peak": f"{swap_peak}%",
        "cpu_peak": f"{cpu_peak}",
        "levels": levels,
        "has_alerts": levels.get("danger", 0) > 0 or levels.get("warn", 0) > 5,
    }


def cost_summary():
    """读取今日成本"""
    log_file = HERMES_HOME / "logs" / "model_cost.log"
    if not log_file.exists():
        return {"status": "no_data"}

    today = str(date.today())
    models = {}
    total_calls = 0
    total_cost = 0

    try:
        with open(log_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    if e.get("timestamp", "")[:10] != today:
                        continue
                    model = e.get("model", "unknown")
                    models.setdefault(model, {"calls": 0, "cost": 0, "tokens": 0})
                    models[model]["calls"] += 1
                    models[model]["cost"] += e.get("cost_usd", 0)
                    models[model]["tokens"] += e.get("total_tokens", 0)
                    total_calls += 1
                    total_cost += e.get("cost_usd", 0)
                except Exception:
                    continue
    except Exception:
        return {"status": "no_data"}

    return {
        "status": "ok",
        "date": today,
        "total_calls": total_calls,
        "total_cost_usd": round(total_cost, 4),
        "total_cost_cny": round(total_cost * 7.25, 2),
        "by_model": models,
    }


def generate() -> str:
    """
    生成完整日报（markdown 格式，写日志用，不给用户看）。

    返回: str (markdown)
    """
    hw = hardware_summary()
    cost = cost_summary()

    lines = [
        f"# 📊 Hermes Sentinel · Daily Report",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %A')}",
        f"**Report ID:** {datetime.now().strftime('%Y%m%d')}",
        f"",
        f"---",
        f"",
        f"## 🖥️ Hardware",
        f"",
    ]

    if hw["status"] == "no_data":
        lines.append("No hardware monitoring data.")
    else:
        lines.append(f"| Metric | Current | Peak |")
        lines.append(f"|--------|---------|------|")
        lines.append(f"| Memory | {hw['memory_now']} | {hw['memory_peak']} |")
        lines.append(f"| Swap   | - | {hw['swap_peak']} |")
        lines.append(f"| CPU    | - | {hw['cpu_peak']} |")
        lines.append(f"")
        lines.append(f"Patrols: {hw['samples']} | 🟢{hw['levels']['normal']} 🟡{hw['levels']['warn']} 🔴{hw['levels']['danger']}")

    lines.extend(["", "---", "", "## 💰 Today's Cost", ""])

    if cost["status"] == "no_data":
        lines.append("No cost data.")
    else:
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Calls  | {cost['total_calls']} |")
        lines.append(f"| Total  | ${cost['total_cost_usd']:.4f} ≈ ¥{cost['total_cost_cny']:.2f} |")
        if cost["by_model"]:
            lines.extend(["", "**By model:**"])
            for model, data in sorted(cost["by_model"].items(), key=lambda x: x[1]["cost"], reverse=True):
                pct = data["cost"] / max(cost["total_cost_usd"], 0.001) * 100
                lines.append(f"- {model}: {data['calls']} calls / ${data['cost']:.4f} ({pct:.0f}%)")

    return "\n".join(lines)
