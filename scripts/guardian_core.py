"""
Hermes Guardian — 守护核心（中央协调器）

被 Hermes 主循环 / Cron 调用，协调所有子模块。
永不直接输出到终端，全部通过 flag 文件和 narrator 与用户沟通。

调用方：
  - Cron → guardian_tick()         每 N 分钟
  - Hermes hook → on_api_call()     每次 API 调用后
  - Hermes hook → on_skill_install() 安装 Skill 前
  - Hermes 主循环 → get_notification() 检查是否有通知待推送
"""

import json
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
CACHE_DIR = HERMES_HOME / "cache" / "guardian"
FLAG_FILE = CACHE_DIR / "notification.json"

# ── 导入各子模块（静默方式） ──────────────────────────────

try:
    import hardware_monitor
except ImportError:
    hardware_monitor = None

try:
    import cost_tracker
except ImportError:
    cost_tracker = None

try:
    import self_heal
except ImportError:
    self_heal = None

try:
    import narrator
except ImportError:
    narrator = None

try:
    import network_monitor
except ImportError:
    network_monitor = None

try:
    import adaptive_understanding
except ImportError:
    adaptive_understanding = None

# ── 用户消息前置 hook ──────────────────────────────────────

def guardian_before_user_message(user_input: str, context: dict = None) -> dict:
    """
    用户消息前置 hook — 模糊指令检测 + 专业重构。

    SKILL.md 声明的 before_user_message handler。
    在 Hermes 主循环处理用户输入前调用。

    参数:
        user_input: 用户原始输入
        context: 会话上下文 dict

    返回:
        {"action": "pass"|"rewrite", "input": str, "original_input": str, "metadata": dict}
    """
    if adaptive_understanding:
        try:
            return adaptive_understanding.guardian_before_user_message(user_input, context or {})
        except Exception as exc:
            return {
                "action": "pass",
                "input": user_input,
                "original_input": user_input,
                "metadata": {"should_rewrite": False,
                             "error": str(exc),
                             "error_type": type(exc).__name__},
            }
    return {
        "action": "pass",
        "input": user_input,
        "original_input": user_input,
        "metadata": {"should_rewrite": False,
                     "error": "adaptive_understanding module not imported"},
    }


# ── 定时巡检 ──────────────────────────────────────────────

def guardian_tick() -> dict:
    """
    定时巡检（每 10 分钟由 Cron 调用）。

    返回:
        {"notify": bool, "message": str|None, "urgency": str}
        notify=False → 静默，不通知用户
        notify=True  → narrator 把 message 翻译成人话输出
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    notifications = []

    # 1. 硬件监控
    if hardware_monitor:
        try:
            hw_result = hardware_monitor.check()
            if hw_result.get("level") in ("warn", "danger"):
                actions = hardware_monitor.auto_remediate(hw_result)
                notifications.append({
                    "type": f"hardware_{hw_result['level']}",
                    "context": hw_result,
                    "actions_taken": actions,
                })
        except Exception:
            pass  # 避免单模块 crash 影响整体

    # 2. 故障检测（Skill 完整性 + 日志健康）
    if self_heal:
        try:
            health = self_heal.quick_check()
            if not health.get("healthy", True):
                notifications.append({
                    "type": f"health_{health.get('severity', 'warn')}",
                    "context": health,
                })
        except Exception:
            pass

    # 3. 本地网络质量检测（每次 tick 都做轻量检查）
    if network_monitor:
        try:
            quick = network_monitor.quick_reachability()
            if not quick.get("healthy", True):
                # 先尝试自动恢复——很多是短暂抖动
                recovery = network_monitor.recover(quick)
                if not recovery.get("recovered"):
                    # 自动恢复失败，需要用户配合
                    full = recovery.get("still_broken", {})
                    notifications.append({
                        "type": "network_issue",
                        "context": {"issues": full.get("issues", []),
                                    "advice": full.get("advice", []),
                                    "topology": full.get("topology")},
                    })
        except Exception:
            pass

    # 5. 判定是否需要通知用户
    if notifications and narrator:
        return narrator.pick_notification(notifications)

    return {"notify": False, "message": None, "urgency": "none"}


# ── API 调用后 hook ──────────────────────────────────────

def guardian_on_api_call(model: str, input_tokens: int, output_tokens: int,
                         task_type: str = "unknown") -> dict:
    """
    API 调用结束后记录 token 消耗（由调用方提供 token 数）。

    推荐使用 guardian_on_api_response()——从真实响应体提取 token，更精准。
    不依赖任何价格表，中转 API 用户同样适用。

    返回:
        {"recorded": bool, "input_tokens": int, "output_tokens": int,
         "cost_usd": float|None}  # cost_usd 仅在配置价格表后才有值
    """
    if cost_tracker:
        try:
            return cost_tracker.record(model, input_tokens, output_tokens, task_type)
        except Exception:
            pass
    return {"recorded": False, "input_tokens": 0, "output_tokens": 0, "cost_usd": None}


def guardian_on_api_response(response: dict, model: str,
                              task_type: str = "unknown") -> dict:
    """
    API 返回后自动记录——从响应体中提取真实 token 数。

    相比 guardian_on_api_call()，这个函数不需要调用方提供 token，
    它自己解析 response.usage 中的数据。

    参数:
        response: API 返回的完整 JSON 响应体
        model: 模型名称（如 "deepseek-chat"）

    返回:
        {"recorded": bool, "over_budget": bool, "cost_usd": float,
         "usage_source": str|None}
    """
    if cost_tracker:
        try:
            return cost_tracker.record_from_response(response, model, task_type)
        except Exception:
            pass
    return {"recorded": False, "over_budget": False, "cost_usd": 0, "usage_source": None}


# ── 安装 Skill 前 hook ───────────────────────────────────

def guardian_on_skill_install(skill_path: str) -> dict:
    """
    安装 Skill 前自动安全审查 + 配置冲突检测。

    返回:
        {"approved": bool, "reason": str | None}
        approved=False → Hermes 阻止安装
    """
    import skill_auditor, config_manager

    # 安全审查
    audit = skill_auditor.scan(skill_path)
    if not audit["approved"]:
        return {"approved": False, "reason": audit.get("user_reason", "该 Skill 存在安全风险，已自动阻止。")}

    # 配置冲突检测（只检测推荐，不写入）
    try:
        config_manager.detect_and_recommend(skill_path)
    except Exception:
        pass

    return {"approved": True, "reason": None}


# ── 通知读取（给 Hermes 主循环） ──────────────────────────

def get_notification() -> dict:
    """
    Hermes 主循环调用 — 检查是否有待推送通知。

    返回:
        {"has": bool, "message": str | None, "urgency": str}
    """
    if not FLAG_FILE.exists():
        return {"has": False, "message": None, "urgency": "none"}

    try:
        notif = json.loads(FLAG_FILE.read_text())
        FLAG_FILE.unlink(missing_ok=True)
        return {
            "has": True,
            "message": notif.get("message"),
            "urgency": notif.get("urgency", "low"),
        }
    except Exception:
        FLAG_FILE.unlink(missing_ok=True)
        return {"has": False, "message": None, "urgency": "none"}


# ── 每日一句话报告 ───────────────────────────────────────

def guardian_daily_report() -> str:
    """
    生成一句话日报（给 narrator 输出）。

    输出示例:
      "今天一切正常，花了 0.08 美元。"
      "今天内存偏高 2 次，已自动处理。花了 0.15 美元。"
    """
    parts = []
    hw_ok = True

    if hardware_monitor:
        try:
            hw = hardware_monitor.history_summary()
            if hw.get("warn_count", 0) > 5:
                parts.append(f"内存偏高 {hw['warn_count']} 次，已自动处理")
                hw_ok = False
            if hw.get("danger_count", 0) > 0:
                parts.append(f"出现 {hw['danger_count']} 次内存紧张，已兜底保存")
                hw_ok = False
        except Exception:
            pass

    if cost_tracker:
        try:
            cost = cost_tracker.get_user_friendly_summary()
            if cost:
                parts.append(cost)
        except Exception:
            pass

    if hw_ok and parts:
        return "今天一切正常。" + " " + parts[0]
    elif not parts:
        return "今天一切正常。"
    return "。".join(parts) + "。"
