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
import os
import shutil
import subprocess
import sys
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
    import intent_translator
except ImportError:
    intent_translator = None

# ── 自动安装插件（用户只需 cp -r 一次） ────────────────────

SKILL_DIR = Path(__file__).resolve().parent.parent
CRON_DIR = SKILL_DIR / "cron"
PLUGIN_SOURCE = SKILL_DIR / "plugin"
PLUGIN_TARGET = HERMES_HOME / "plugins" / "hermes-sentinel"
_INIT_DONE = False


def _first_run_setup() -> str | None:
    """
    首次安装自动配置：创建目录、安装插件、写 cron。

    由模块导入时触发，也在 guardian_tick() 开头冗余调用。
    返回状态消息字符串，首次完成时有值，后续调用返回 None。

    环境变量 HERMES_SENTINEL_SKIP_SETUP=1 跳过安装（用于测试环境/CI）。
    """
    global _INIT_DONE
    if _INIT_DONE:
        return None
    if os.environ.get("HERMES_SENTINEL_SKIP_SETUP") == "1":
        _INIT_DONE = True
        return None

    steps: list[str] = []

    # 1. 创建日志和缓存目录
    (HERMES_HOME / "logs").mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # 2. 安装插件
    if PLUGIN_SOURCE.exists():
        try:
            import shutil
            PLUGIN_TARGET.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(PLUGIN_SOURCE), str(PLUGIN_TARGET), dirs_exist_ok=True)
            steps.append("plugin")
        except Exception:
            pass

    # 3. 写 cron（仅在非 Windows 且有 crontab 时）
    if sys.platform != "win32":
        try:
            existing = subprocess.run(
                ["crontab", "-l"], capture_output=True, text=True, timeout=5
            ).stdout or ""
            tick_script = str(CRON_DIR / "hardware-check.sh")
            daily_script = str(CRON_DIR / "daily-backup.sh")

            new_cron = existing
            added = 0

            if "sentinel-tick" not in existing:
                import random
                m_off = random.randint(0, 9)
                new_cron += f"\n{m_off}-59/10 * * * * {tick_script} 2>&1 | logger -t sentinel-tick"
                added += 1

            if "sentinel-daily" not in existing:
                rnd = random.randint(0, 29)
                new_cron += f"\n{rnd} 9 * * * {daily_script} 2>&1 | logger -t sentinel-daily"
                added += 1

            if added > 0:
                subprocess.run(
                    ["crontab"], input=new_cron, capture_output=True, text=True, timeout=5
                )
                steps.append(f"cron({added} jobs)")
        except Exception:
            pass

    _INIT_DONE = True

    if steps:
        return "Sentinel setup: " + ", ".join(steps) + " installed"
    return None


# 模块导入时自动执行首次初始化（Hermes 加载 skill 时触发）
_first_run_setup()


# ── 自身环境检测 ──────────────────────────────────────────

def self_inspect() -> list[dict]:
    """
    检查自身运行环境是否完整。

    对每个问题判断：
    - can_auto_fix=True  → Sentinel 已自动修复
    - can_auto_fix=False → 需要外部干预（Hermes 或用户）

    返回:
    [{"type": str, "severity": "info"|"warn"|"danger",
      "message": str,       # 人话描述
      "hermes_instruction": str,  # 给 Hermes AI 的执行指令
      "can_auto_fix": bool,
      "auto_fixed": bool}, ...]
    """
    issues: list[dict] = []

    # 1. 插件检测
    if not (PLUGIN_TARGET / "__init__.py").exists():
        fixed = _first_run_setup()
        if fixed and "plugin" in fixed:
            issues.append({
                "type": "plugin_missing",
                "severity": "info",
                "message": "Token 统计插件已自动安装",
                "hermes_instruction": "",
                "can_auto_fix": True,
                "auto_fixed": True,
            })
        else:
            issues.append({
                "type": "plugin_missing",
                "severity": "warn",
                "message": "Token 统计插件未安装，API 调用不会自动记账",
                "hermes_instruction": "帮我检查一下 Hermes Sentinel 的 plugin 目录是否正确安装到了 ~/.hermes/plugins/hermes-sentinel/，如果没有，从 skill 目录复制一份过来。",
                "can_auto_fix": False,
                "auto_fixed": False,
            })

    # 2. cron 检测
    if sys.platform != "win32":
        try:
            cron_out = subprocess.run(
                ["crontab", "-l"], capture_output=True, text=True, timeout=5
            ).stdout or ""
            if "sentinel-tick" not in cron_out:
                fixed = _first_run_setup()
                issues.append({
                    "type": "cron_missing",
                    "severity": "info" if fixed else "warn",
                    "message": "定时巡检 cron 任务已自动配置" if fixed else "定时巡检 cron 任务未配置",
                    "hermes_instruction": "请在终端执行 crontab -e 检查 sentinel-tick 和 sentinel-daily 任务是否存在",
                    "can_auto_fix": True,
                    "auto_fixed": bool(fixed),
                })
        except Exception:
            pass

    # 3. 日志权限检测
    log_dir = HERMES_HOME / "logs"
    if log_dir.exists():
        if not os.access(str(log_dir), os.W_OK):
            issues.append({
                "type": "log_permission",
                "severity": "danger",
                "message": "日志目录 ~/.hermes/logs/ 无写入权限，可能导致监控失效",
                "hermes_instruction": "请在终端执行 chmod -R 755 ~/.hermes/logs/ 来修复日志目录权限",
                "can_auto_fix": False,
                "auto_fixed": False,
            })

    # 4. Python 版本检测
    if sys.version_info < (3, 9):
        issues.append({
            "type": "python_version",
            "severity": "warn",
            "message": f"Python {sys.version_info.major}.{sys.version_info.minor} 版本过旧，建议升级到 Python 3.9+",
            "hermes_instruction": f"检测到 Python {sys.version_info.major}.{sys.version_info.minor}。访问 https://www.python.org/downloads/ 下载安装 Python 3.9 或更高版本",
            "can_auto_fix": False,
            "auto_fixed": False,
        })

    # 5. 关键系统命令检测
    for cmd in ["curl", "ping"]:
        if not shutil.which(cmd):
            if cmd == "curl" and sys.platform == "win32":
                continue
            issues.append({
                "type": f"cmd_missing:{cmd}",
                "severity": "info",
                "message": f"系统命令 {cmd} 未安装，部分网络检测能力受限",
                "hermes_instruction": f"当前系统缺少 {cmd} 命令。macOS/Linux 请执行包管理器安装（brew install curl），Windows 用户可忽略此提示。",
                "can_auto_fix": False,
                "auto_fixed": False,
            })

    # 6. 日志文件大小检测（超过 50MB 警告）
    for log_file in ["hardware_monitor.log", "network_monitor.log", "model_cost.log"]:
        fp = log_dir / log_file
        if fp.exists() and fp.stat().st_size > 50 * 1024 * 1024:
            issues.append({
                "type": f"log_too_large:{log_file}",
                "severity": "warn",
                "message": f"{log_file} 已超过 50MB，建议轮替或清理",
                "hermes_instruction": f"文件 {log_file} 体积过大。请执行：rm ~/.hermes/logs/{log_file} 清理旧日志，或将日志加入 logrotate 轮替",
                "can_auto_fix": False,
                "auto_fixed": False,
            })

    return issues


# ── 用户消息前置 hook ──────────────────────────────────────

def guardian_before_user_message(user_input: str, context: dict = None) -> dict:
    """
    用户消息前置 hook — 模糊指令翻译。

    将小白模糊输入（"太暗"、"乱码"、"太慢"）翻译成 Hermes 能执行的清晰指令。

    参数:
        user_input: 用户原始输入
        context: 会话上下文 dict（至少含 conversation_context.current_file）

    返回:
        {"action": "pass"|"translate", "input": str, "original_input": str, "metadata": dict}
    """
    if intent_translator:
        try:
            ctx = context or {}
            conv = ctx.get("conversation_context") or {}
            current_file = conv.get("current_file") if isinstance(conv, dict) else None

            result = intent_translator.translate(user_input, current_file=current_file)

            if result.get("should_translate"):
                return {
                    "action": "translate",
                    "input": result["translated"] or user_input,
                    "original_input": user_input,
                    "metadata": result,
                }
            return {
                "action": "pass",
                "input": user_input,
                "original_input": user_input,
                "metadata": result,
            }
        except Exception as exc:
            return {
                "action": "pass",
                "input": user_input,
                "original_input": user_input,
                "metadata": {"should_translate": False,
                             "error": str(exc),
                             "error_type": type(exc).__name__},
            }
    return {
        "action": "pass",
        "input": user_input,
        "original_input": user_input,
        "metadata": {"should_translate": False,
                     "error": "intent_translator module not imported"},
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
    # 冗余：首次安装初始化（即使模块导入时已触发）
    _first_run_setup()

    notifications = []

    # 0. 自身环境检测（每天最多提醒一次）
    for issue in self_inspect():
        if issue["can_auto_fix"] and issue["auto_fixed"]:
            continue  # 已自动修复，静默
        if issue.get("hermes_instruction"):
            notifications.append({
                "type": "self_inspect",
                "context": issue,
            })

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

    # 4. 判定是否需要通知用户
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
    import skill_auditor

    # 安全审查
    audit = skill_auditor.scan(skill_path)
    if not audit["approved"]:
        return {"approved": False, "reason": audit.get("user_reason", "该 Skill 存在安全风险，已自动阻止。")}

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
