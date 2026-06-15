"""Search query builder — convert context into clean, natural search queries.

Extracts platform/language/domain from context signals and file paths
instead of using raw paths in search strings.
"""

from typing import Optional


DO_NOT_REWRITE: set[str] = {
    "yes", "no", "好", "不用", "取消", "停",
    "继续运行", "提交", "保存", "exit", "quit",
}


def is_denylisted(text: str) -> bool:
    stripped = text.strip().lower()
    return stripped in DO_NOT_REWRITE


def infer_platform(signals: list[str], current_file: Optional[str], industry_key: str) -> str:
    """Extract a readable platform/domain name from context."""
    sig_set = set(s.lower() for s in signals)
    file_lower = (current_file or "").lower()

    platform_map = [
        (["公众号", "wechat", "微信"], "微信公众号"),
        (["小红书", "xiaohongshu", "red"], "小红书"),
        (["抖音", "tiktok", "douyin"], "抖音"),
        (["wechat", "微信", "微信api"], "微信 API"),
    ]

    for keywords, label in platform_map:
        if any(k in file_lower for k in keywords):
            return label
        if any(k in sig_set for k in keywords):
            return label

    # Fall back to industry name
    return industry_key.replace("_", " ").title()


def infer_language(signals: list[str], current_file: Optional[str]) -> str:
    """Infer programming language from context."""
    file_lower = (current_file or "").lower()
    sig_set = set(s.lower() for s in signals)

    if any(ext in file_lower for ext in [".py", "python"]):
        return "python"
    if "python" in sig_set:
        return "python"
    if any(ext in file_lower for ext in [".js", ".ts", ".jsx"]):
        return "javascript"
    if any(ext in file_lower for ext in [".java"]):
        return "java"
    if any(ext in file_lower for ext in [".go"]):
        return "go"
    return "python"  # sensible default


def infer_doc_type(signals: list[str], current_file: Optional[str]) -> str:
    """Infer document/report type."""
    file_lower = (current_file or "").lower()
    sig_set = set(s.lower() for s in signals)

    if "ppt" in sig_set or ".pptx" in file_lower:
        return "演示文稿"
    if "报告" in sig_set:
        return "报告"
    if "周报" in sig_set:
        return "周报"
    if "文档" in sig_set:
        return "文档"
    if "邮件" in sig_set:
        return "邮件"
    return "文档"


def infer_chart_type(signals: list[str]) -> str:
    sig_set = set(s.lower() for s in signals)
    if "图表" in sig_set:
        return "图表"
    if "可视化" in sig_set:
        return "数据可视化"
    return "数据图表"


def infer_model(signals: list[str]) -> str:
    sig_set = set(s.lower() for s in signals)
    if "deepseek" in sig_set:
        return "deepseek"
    if "openai" in sig_set:
        return "openai"
    if "claude" in sig_set:
        return "claude"
    return "模型"


def infer_provider(signals: list[str]) -> str:
    sig_set = set(s.lower() for s in signals)
    if "deepseek" in sig_set:
        return "deepseek"
    if "openai" in sig_set:
        return "openai"
    if "openrouter" in sig_set:
        return "openrouter"
    return "provider"


def build_search_queries(
    industry_key: str,
    user_input: str,
    ctx: dict,
    templates: list[str],
    year: str = "2026",
) -> list[str]:
    """
    Build clean search queries from context signals and templates.

    Never includes raw file paths. Extracts platform/language from signals.
    Appends year only when not already present in the template.
    """
    signals = ctx.get("signals", [])
    current_file = ctx.get("current_file")

    platform = infer_platform(signals, current_file, industry_key)
    language = infer_language(signals, current_file)
    doc_type = infer_doc_type(signals, current_file)
    chart_type = infer_chart_type(signals)
    model = infer_model(signals)
    provider = infer_provider(signals)

    queries: list[str] = []
    for tmpl in templates:
        q = tmpl.format(
            platform=platform,
            api_name=platform,
            language=language,
            issue=user_input,
            doc_type=doc_type,
            chart_type=chart_type,
            model=model,
            provider=provider,
        )
        # Append year only if not already present in template
        if year and year not in q:
            q = f"{q} {year}"
        queries.append(q)

    # Dedup while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            deduped.append(q)
    return deduped
