"""
Hermes Guardian — 自然语言输出层

把机器数据翻译成人话，同时控制通知频率，避免刷屏。

使用方式（被 guardian_core 调用）:
    narrator.pick_notification(notifications) → {"notify": bool, "message": str, "urgency": str}
    narrator.speak(event_type, context) → {"should_speak": bool, "message": str}
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
THROTTLE_LOG = HERMES_HOME / "cache" / "guardian" / "notif_throttle.json"

# ── 通知频率限制 ──────────────────────────────────────────

NOTIFICATION_LIMITS = {
    "hardware_warn":      {"daily_max": 3, "cooldown_sec": 3600},
    "hardware_danger":    {"daily_max": 5, "cooldown_sec": 900},
    "health_warn":        {"daily_max": 3, "cooldown_sec": 1800},
    "health_danger":      {"daily_max": 3, "cooldown_sec": 900},
    "cost_budget":        {"daily_max": 2, "cooldown_sec": 0},
    "price_stale":        {"daily_max": 1, "cooldown_sec": 0},     # 每天最多一次
    "network_issue":      {"daily_max": 4, "cooldown_sec": 1800},
    "network_restored":   {"daily_max": 2, "cooldown_sec": 3600},
    "skill_blocked":      {"daily_max": 1, "cooldown_sec": 0},
}

# ── 消息模板 ──────────────────────────────────────────────

MESSAGE_TEMPLATES = {
    "hardware_warn": {
        "normal": lambda ctx: _describe_hardware_warn(ctx),
    },
    "hardware_danger": {
        "normal": lambda ctx: _describe_hardware_danger(ctx),
    },
    "health_warn": {
        "normal": lambda ctx: _describe_health_warn(ctx),
    },
    "health_danger": {
        "normal": lambda ctx: _describe_health_danger(ctx),
    },
    "cost_budget": {
        "normal": lambda ctx: _describe_cost(ctx),
    },
    "network_issue": {
        "normal": lambda ctx: _describe_network_issue(ctx),
    },
    "network_restored": {
        "normal": lambda ctx: "网恢复了，可以继续用了。",
    },
    "price_stale": {
        "normal": lambda ctx: _describe_price_stale(ctx),
    },
    "skill_blocked": {
        "normal": lambda ctx: _describe_skill_blocked(ctx),
    },
}

# ── 具体消息生成器 ────────────────────────────────────────

def _describe_hardware_warn(ctx) -> str:
    """硬件预警 → 人话"""
    mem = ctx.get("memory", {}).get("memory_pct", 0)
    mem_gb = ctx.get("memory", {}).get("used_gb", 0)
    mem_total = ctx.get("memory", {}).get("total_gb", 0)
    disk_pct = ctx.get("disk", {}).get("home_pct", 0)
    actions = ctx.get("_actions_taken", [])

    msg = ""
    if mem >= 80:
        avail = round(mem_total - mem_gb, 1)
        msg += f"内存快满了（还剩 {avail}GB 空闲）"
    if disk_pct >= 90:
        avail_gb = ctx.get("disk", {}).get("home_avail_gb", 0)
        if msg:
            msg += "，"
        msg += f"硬盘只剩 {avail_gb}GB 了"

    if actions:
        action_msgs = []
        if "cleaned_logs" in actions:
            freed = ctx.get("freed_gb", 0)
            if freed >= 0.5:
                action_msgs.append(f"帮你清理了些旧日志（多了 {freed}GB 空间）")
            elif freed >= 0.1:
                action_msgs.append("帮你清理了些旧日志，多了点空间")
            else:
                action_msgs.append("帮你清理了些旧日志")
        if "compressed" in actions:
            action_msgs.append("帮你压缩了上下文，应该好点了")
        if action_msgs:
            msg += "。" + "。".join(action_msgs)

    return msg


def _describe_hardware_danger(ctx) -> str:
    """硬件危险 → 人话"""
    msg = "电脑内存严重不足，我已经临时保存了当前的工作。"
    actions = ctx.get("_actions_taken", [])
    if "compressed" in actions:
        msg += "正在压缩上下文腾出空间。"
    if "emergency_saved" in actions:
        msg += "当前对话已安全保存，不会丢失。"
    return msg


def _describe_health_warn(ctx) -> str:
    """健康预警 → 人话"""
    issues = ctx.get("issues", [])
    if not issues:
        return "有个小问题在后台处理，不影响你使用。"
    msg = ""
    for i in issues:
        if "broken skill" in i:
            msg = f"有 {i}，不影响使用，但建议看看。"
        elif "log" in i:
            msg = "日志写入有点问题，但不影响当前使用。"
    return msg or "有个小问题在后台处理，不影响你使用。"


def _describe_health_danger(ctx) -> str:
    """健康危险 → 人话"""
    issues = ctx.get("issues", [])
    if not issues:
        return "有个问题需要处理，我还在尝试修复。"
    if any("log" in i for i in issues):
        return "日志写入失败，功能可能会受影响，需要检查一下。"
    return "有个问题需要处理，我还在尝试修复。"


def _describe_cost(ctx) -> str:
    """成本摘要 → 人话"""
    cost = ctx.get("cost_usd", 0)
    calls = ctx.get("calls", 0)
    over = ctx.get("over_budget", False)
    if over:
        return f"今天 API 花了 ${cost:.2f} 了，快到预算了。"
    return f"今天用了 {calls} 次，花了 ${cost:.4f} 美元。"


def _describe_price_stale(ctx) -> str:
    """价格表过期 → 人话（只对维护者说）"""
    months = ctx.get("months_since_update", 0)
    lu = ctx.get("last_updated", "?")
    sources = None
    try:
        from . import cost_tracker
        sources = cost_tracker.get_provider_sources()
    except Exception:
        pass

    msg = f"价格表已有 {months} 个月没更新了（上次更新于 {lu}），当前计费可能不准确。"
    if sources:
        urls = "\n".join(f"- {name}: {url}" for name, url in sorted(sources.items()))
        msg += f"\n核对链接：\n{urls}"
    return msg


def _describe_network_issue(ctx) -> str:
    """
    网络问题 → 人话（合作语气：我先自愈了，搞不定再请你帮忙）

    ctx 结构来自 network_monitor.check():
    {
        "issues": [str],
        "advice": [str],
        "topology": "direct"|"proxy"|"vpn"|"corporate",
    }
    """
    issues = ctx.get("issues", [])
    advice = ctx.get("advice", [])

    if not issues:
        return ""

    scenario = issues[0].split(":")[0]

    messages = {
        "no_network":           "我连不上网络，试了几次也不行。你能看看网线或 WiFi 是不是没开吗？",
        "gateway_unreachable":  "路由器连不上，我重试了也不行。方便的话检查一下路由器电源或重启一下？",
        "dns_failure":          "网络是通的，但域名解析不了。你方便把 DNS 改成 8.8.8.8 或 114.114.114.114 试试吗？",
        "internet_down":        "路由器能连上，但外网不通。可能宽带欠费了，或者需要在浏览器里登录认证一下。",
        "proxy_down":           "代理连不上，我等了一会儿重试还是不行。你检查一下代理客户端有没有开着？",
        "proxy_working_but_internet_down": "代理开着但走不出去，可能是代理本身的网络也断了。",
        "api_blocked":          "网络正常，但所有 AI 服务都连不上。如果你在用代理，看看规则里有没有把 AI 网站加进去？",
        "api_partial_blocked":  "有些 AI 服务连不上，你可以切换到能用的那个提供商试试。",
        "api_high_latency":     _describe_high_latency(issues[0], ctx.get("topology", "unknown")),
        "unknown":              "网络有点不稳定，我再观察一下。",
    }

    msg = messages.get(scenario, messages["unknown"])

    if advice and scenario not in ("unknown",):
        first_advice = advice[0].rstrip("。")
        if first_advice not in msg:
            msg += f"\n{first_advice}。"

    return msg


def _describe_high_latency(issue: str, topology: str) -> str:
    """高延迟场景给出地区自适应的建议"""
    if ":" in issue:
        slow_apis = issue.split(":", 1)[1]
    else:
        return "连接 AI 服务的速度比平时慢，响应会多等一会儿。"

    if topology == "proxy":
        return f"走代理到 {slow_apis} 速度不理想。你能换个代理节点试试吗？"
    elif topology == "vpn":
        return f"走 VPN 到 {slow_apis} 延迟偏高，这是 VPN 本身的正常损耗。我调整了超时参数，不影响使用。"
    elif topology == "corporate":
        return f"走公司网络到 {slow_apis} 比较慢，这是企业出口的正常情况。我调整了等待时间，尽量不影响你。"
    elif topology == "direct":
        return f"到 {slow_apis} 延迟偏高。如果你在国内，试试走代理可能会快很多。"
    else:
        return f"到 {slow_apis} 响应偏慢，我调整了策略再试试。"


def _describe_skill_blocked(ctx) -> str:
    """Skill 被拦截 → 人话"""
    reason = ctx.get("reason", "")
    if "不安全" in reason or "风险" in reason:
        return f"我检查了一下这个插件，发现不太安全，就没让它装上。"
    return f"这个插件没通过安全检查，我帮你拦下了。"


# ── 通知节流器 ──────────────────────────────────────────

class NotificationThrottle:
    """通知节流器 — 防止同类型通知刷屏"""

    def __init__(self):
        self._log = self._load()

    def _load(self) -> dict:
        if THROTTLE_LOG.exists():
            try:
                return json.loads(THROTTLE_LOG.read_text())
            except Exception:
                pass
        return {"entries": {}}

    def _save(self):
        THROTTLE_LOG.parent.mkdir(parents=True, exist_ok=True)
        THROTTLE_LOG.write_text(json.dumps(self._log, ensure_ascii=False))

    def _today_key(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def should_speak(self, event_type: str) -> bool:
        """
        判断给定事件类型是否允许发通知。

        规则：
        - 同类型每天不超过 daily_max 次
        - 同类型在冷却期内不重复
        """
        limits = NOTIFICATION_LIMITS.get(event_type)
        if not limits:
            return True  # 未限制的类型放行

        today = self._today_key()
        entries = self._log["entries"].get(event_type, {}).get(today, [])

        # 日上限
        if len(entries) >= limits.get("daily_max", 999):
            return False

        # 冷却期
        if entries and limits.get("cooldown_sec", 0) > 0:
            last_ts = entries[-1]
            elapsed = time.time() - last_ts
            if elapsed < limits["cooldown_sec"]:
                return False

        return True

    def record(self, event_type: str):
        """记录一次已发出的通知"""
        today = self._today_key()
        entry = self._log["entries"].setdefault(event_type, {}).setdefault(today, [])
        entry.append(int(time.time()))
        self._save()

    def cleanup_old(self):
        """清理超过 7 天的记录"""
        today = self._today_key()
        for event_type in list(self._log["entries"].keys()):
            for day in list(self._log["entries"][event_type].keys()):
                if day < today:
                    del self._log["entries"][event_type][day]
        self._save()


# ── 核心选择器 ──────────────────────────────────────────

_throttle = NotificationThrottle()

def pick_notification(notifications: list) -> dict:
    """
    从多条通知中选择最重要的那一条，节制后输出。

    参数:
        notifications: [{"type": str, "context": dict}, ...]

    返回:
        {"notify": bool, "message": str|None, "urgency": str}
    """
    if not notifications:
        return {"notify": False, "message": None, "urgency": "none"}

    # 按紧急程度排序：danger > warn > 其他
    urgency_order = {"hardware_danger": 0, "health_danger": 1,
                     "hardware_warn": 2, "health_warn": 3,
                     "network_issue": 4, "cost_budget": 5,
                     "price_stale": 6, "skill_blocked": 7,
                     "network_restored": 8}
    notifications.sort(key=lambda n: urgency_order.get(n.get("type", ""), 99))

    for notif in notifications:
        event_type = notif.get("type", "")
        context = notif.get("context", {})

        if _throttle.should_speak(event_type):
            _throttle.record(event_type)
            message = _build_message(event_type, context)
            urgency = "danger" if "danger" in event_type else "warn" if "warn" in event_type else "low"
            return {"notify": True, "message": message, "urgency": urgency}

    return {"notify": False, "message": None, "urgency": "none"}


def _build_message(event_type: str, context: dict) -> str:
    """根据事件类型构建消息"""
    tmpl = MESSAGE_TEMPLATES.get(event_type, {})
    builder = tmpl.get("normal")
    if builder:
        try:
            return builder(context)
        except Exception:
            pass
    return "有件事想跟你说。"  # fallback


def speak(event_type: str, context: dict) -> dict:
    """
    外部调用 — 直接生成一条通知（受节流控制）。

    返回:
        {"should_speak": bool, "message": str}
    """
    if not _throttle.should_speak(event_type):
        return {"should_speak": False, "message": ""}

    _throttle.record(event_type)
    return {"should_speak": True, "message": _build_message(event_type, context)}
