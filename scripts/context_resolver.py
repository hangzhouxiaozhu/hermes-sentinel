"""上下文解析器 — 从当前会话、最近任务、文件类型、已加载 skill 中推断场景。

给 adaptive_understanding 提供结构化的上下文信息。
"""

from pathlib import Path
from typing import Any, Optional


MAX_HISTORY_TOKENS = 2000  # 从会话历史中提取最近 N 个 token


def resolve_context(
    conversation_context: Optional[dict] = None,
    loaded_skills: Optional[list[dict]] = None,
) -> dict:
    """
    从多方来源聚合当前上下文，返回结构化场景描述。

    参数:
        conversation_context: Hermes 提供的会话上下文，包含：
            - last_user_message: str
            - recent_messages: list[dict]  # 最近几条消息
            - current_file: str | None     # 用户当前操作的文件
            - active_tool: str | None      # 用户正在使用的工具
            - session_tags: list[str]      # 会话标签
        loaded_skills: 已加载的 skill 列表，每项含 name/description/keywords

    返回:
    {
        "signals": [str],          # 提取到的信号词
        "possible_industries": [{"key": str, "score": float, "name": str}],
        "confidence": float,       # 整体置信度 0-1
        "recent_tasks": [str],     # 推断的最近任务
        "current_tool": str|None,
        "current_file": str|None,
    }
    """
    signals: list[str] = []
    recent_tasks: list[str] = []
    current_tool = None
    current_file = None

    ctx = conversation_context or {}

    # ── 从当前文件和工具推断 ──
    current_file = ctx.get("current_file")
    if current_file:
        path = Path(str(current_file))
        signals.extend(path.suffixes)
        signals.append(path.stem)
        # 从路径推断任务类型
        parts = path.parts
        known_dirs = {"公众号": "公众号排版", "封面": "封面设计",
                      "代码": "coding", "文档": "文档写作", "数据": "数据分析"}
        for part in parts:
            if part in known_dirs and known_dirs[part] not in recent_tasks:
                recent_tasks.append(known_dirs[part])

    current_tool = ctx.get("active_tool")
    if current_tool:
        signals.append(current_tool)

    # ── 从最近消息中提取信号词 ──
    last_msg = ctx.get("last_user_message", "")
    if last_msg:
        # 将用户输入中的词加入信号
        for word in last_msg.split():
            cleaned = word.strip("，。！？、（）""''：；【】《》")
            if len(cleaned) > 1:
                signals.append(cleaned)

    recent_msgs = ctx.get("recent_messages", []) or []
    for msg in recent_msgs[-5:]:  # 只看最近 5 条
        content = (msg.get("content") or "") if isinstance(msg, dict) else ""
        for word in content.split():
            cleaned = word.strip("，。！？、（）""''：；【】《》")
            if len(cleaned) > 1 and len(cleaned) < 20:
                signals.append(cleaned)

    # ── 从 skill 中提取信号 ──
    if loaded_skills:
        for skill in loaded_skills:
            if isinstance(skill, dict):
                for val in [skill.get("description", ""), skill.get("name", "")]:
                    if isinstance(val, str):
                        for word in val.split():
                            cleaned = word.strip("，。！？、（）""''：；【】《》")
                            if len(cleaned) > 1 and len(cleaned) < 20:
                                signals.append(cleaned)

    # ── 去重 ──
    signals = list(dict.fromkeys(signals))  # preserve order, dedup

    # ── 匹配行业 ──
    import industry_profiles
    possible = industry_profiles.match_industry(signals)

    confidence = possible[0][1] if possible else 0.0

    return {
        "signals": signals[:50],  # 截断避免过大
        "possible_industries": possible,
        "confidence": confidence,
        "recent_tasks": recent_tasks,
        "current_tool": current_tool,
        "current_file": current_file,
    }
