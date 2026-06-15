"""Context resolver — infer scenario from session, file, tools, and loaded skills.

Provides structured context data for the adaptive understanding engine.
"""

from pathlib import Path
from typing import Any, Optional


# Known signal keywords (Chinese + English) that map to industries.
# Substring matching, no space dependency — works for CJK text.
KNOWN_SIGNAL_TERMS = {
    # new_media_visual_design
    "公众号", "封面", "海报", "渲染", "banner", "头图", "缩略图", "配图",
    # social_media_content
    "小红书", "笔记", "文案", "抖音", "视频号", "朋友圈", "种草",
    # software_engineering
    "代码", "报错", "乱码", "API", "Python", "JSON", "编码", "脚本",
    "函数", "bug", "配置", "git", "微信", "charset", "utf-8",
    # ai_operations
    "token", "模型", "调用", "超时", "provider", "deepseek", "openai",
    "claude", "费用",
    # document_writing
    "文档", "文章", "报告", "PPT", "周报", "日报", "邮件", "方案", "总结", "提纲",
    # data_analysis
    "表格", "数据", "报表", "统计", "图表", "可视化", "CSV", "Excel", "SQL",
}


def extract_signals_from_text(text: str) -> list[str]:
    """
    Extract industry signal keywords from text using known-term dictionary.

    Works on CJK text without relying on word-boundary splitting.
    Also captures tokenized fragments (after replacing separators with spaces).
    """
    signals: list[str] = []
    if not text:
        return signals

    lower = text.lower()

    # Match known terms by substring (captures Chinese without spaces)
    for term in KNOWN_SIGNAL_TERMS:
        if term.lower() in lower:
            signals.append(term)

    # Also split on common separators for ASCII tokens
    for sep in ("/", "_", "-", "\\"):
        text = text.replace(sep, " ")

    for token in text.split():
        cleaned = token.strip("，。！？、（）\"'':：；【】《》（）\t\n\r")
        if 1 < len(cleaned) < 30:
            signals.append(cleaned)

    return list(dict.fromkeys(signals))  # dedup, preserve order


def resolve_context(
    conversation_context: Optional[dict] = None,
    loaded_skills: Optional[list[dict]] = None,
) -> dict:
    """
    Aggregate context from multiple sources into a structured scenario description.

    Returns:
    {
        "signals": [str],
        "possible_industries": [{"key": str, "score": float, "name": str}],
        "confidence": float,
        "recent_tasks": [str],
        "current_tool": str|None,
        "current_file": str|None,
    }
    """
    signals: list[str] = []
    recent_tasks: list[str] = []
    current_tool = None
    current_file = None

    ctx = conversation_context or {}

    # ── Current file ──
    current_file = ctx.get("current_file")
    if current_file:
        path = Path(str(current_file))
        if path.suffix:
            signals.append(path.suffix)
        stem = path.stem
        if stem:
            signals.append(stem)
        # Map directory names to tasks
        known_dirs = {"公众号": "公众号排版", "封面": "封面设计",
                      "代码": "coding", "文档": "文档写作", "数据": "数据分析"}
        for part in path.parts:
            if part in known_dirs and known_dirs[part] not in recent_tasks:
                recent_tasks.append(known_dirs[part])

    # ── Active tool ──
    current_tool = ctx.get("active_tool")
    if current_tool:
        signals.append(current_tool)

    # ── Last user message ──
    last_msg = ctx.get("last_user_message", "")
    if last_msg:
        signals.extend(extract_signals_from_text(last_msg))

    # ── Recent messages ──
    recent_msgs = ctx.get("recent_messages", []) or []
    for msg in recent_msgs[-5:]:
        content = ""
        if isinstance(msg, dict):
            content = msg.get("content") or ""
        else:
            content = str(msg)
        signals.extend(extract_signals_from_text(content))

    # ── Loaded skills ──
    if loaded_skills:
        for skill in loaded_skills:
            if isinstance(skill, dict):
                desc = skill.get("description", "") or ""
                name = skill.get("name", "") or ""
                signals.extend(extract_signals_from_text(desc))
                signals.extend(extract_signals_from_text(name))

    # ── Dedup ──
    signals = list(dict.fromkeys(signals))

    # ── Industry matching ──
    import industry_profiles
    possible = industry_profiles.match_industry(signals)

    confidence = possible[0][1] if possible else 0.0

    # ── Infer task type ──
    file_lower = (current_file or "").lower()
    all_text = " ".join(signals).lower()

    task_type = "general"
    if any(ext in file_lower for ext in [".png", ".jpg", ".jpeg", ".gif", ".svg", ".psd", ".ai"]):
        task_type = "visual_edit"
    elif any(ext in file_lower for ext in [".py", ".js", ".ts", ".java", ".go", ".rs"]):
        task_type = "code_fix"
    elif any(ext in file_lower for ext in [".xlsx", ".xls", ".csv"]):
        task_type = "data_analysis"
    elif any(ext in file_lower for ext in [".pptx", ".ppt"]):
        task_type = "presentation"
    elif any(ext in file_lower for ext in [".docx", ".doc", ".md", ".txt"]):
        task_type = "document_writing"
    elif "封面" in all_text or "海报" in all_text or "渲染" in all_text:
        task_type = "visual_edit"
    elif "代码" in all_text or "报错" in all_text or "乱码" in all_text:
        task_type = "code_fix"
    elif "表格" in all_text or "数据" in all_text or "图表" in all_text:
        task_type = "data_analysis"
    elif "PPT" in all_text or "报告" in all_text or "文档" in all_text:
        task_type = "document_writing"

    return {
        "signals": signals[:50],
        "possible_industries": possible,
        "confidence": confidence,
        "recent_tasks": recent_tasks,
        "current_tool": current_tool,
        "current_file": current_file,
        "task_type": task_type,
    }
