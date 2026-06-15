"""Adaptive instruction understanding — main entry point.

When user input is short or ambiguous, determines whether a professional
rewrite is needed. Integrates context_resolver, industry_profiles, and
standards_registry.
"""

from typing import Any, Callable, Optional

import context_resolver
import industry_profiles
import standards_registry

# Thresholds
MIN_CONFIDENCE_FOR_REWRITE = 0.4
MIN_CONFIDENCE_FOR_ASK = 0.2
SHORT_INPUT_THRESHOLD = 8

# Ambiguous words (exact match)
VAGUE_WORDS: set[str] = {
    "太暗", "太亮", "乱码", "继续", "不对", "不好看", "太乱",
    "改一下", "和上次一样", "再看看", "优化", "太贵", "太慢",
    "太啰嗦", "太短", "没人看", "数据差", "没流量", "跑不起来",
    "看不出", "不对齐",
}


def is_ambiguous_instruction(text: str) -> bool:
    """Return True if the input is short/ambiguous and may need rewriting."""
    stripped = text.strip()
    if stripped in VAGUE_WORDS:
        return True
    if len(stripped) <= SHORT_INPUT_THRESHOLD:
        concrete_objects = {"文件", "图片", "代码", "标题", "表格", "页面",
                            "封面", "文章", "报告", "脚本", "数据", "邮件",
                            "文档", "笔记", "配置", "模型", "API"}
        if not any(obj in stripped for obj in concrete_objects):
            return True
    return False


def compose_instruction(
    original: str,
    industry_name: str,
    intent: Optional[str],
    standards: list[dict],
    search_queries: list[str],
    needs_search: bool,
) -> str:
    """
    Build a complete, actionable instruction from intent + standards + search.

    Returns a multi-sentence instruction string, not a single-line patch.
    """
    lines: list[str] = []

    if intent:
        lines.append(f"Based on the current scenario ({industry_name}), address the user's concern: 「{original}」.")
        lines.append(f"Objective: {intent}.")
    else:
        lines.append(f"Handle the user's input 「{original}」 within the {industry_name} context.")

    if standards:
        lines.append("Follow these standards during execution:")
        for s in standards[:3]:
            lines.append(f"  - {s['name']}: {s['description']}")

    if search_queries:
        if needs_search:
            lines.append("Before executing, verify against current industry best practices:")
        else:
            lines.append("If online verification is available, reference these directions:")
        for q in search_queries[:2]:
            lines.append(f"  - {q}")

    lines.append("Output must be a complete, actionable plan — not a single parameter adjustment.")
    return "\n".join(lines)


def build_rewrite_plan(
    user_input: str,
    conversation_context: Optional[dict] = None,
    loaded_skills: Optional[list[dict]] = None,
    allow_web_search: bool = False,
    search_provider: Optional[Callable] = None,
) -> dict:
    """
    Decide whether to rewrite the user input, return a structured rewrite plan.

    Returns:
    {
        "should_rewrite": bool,
        "action": "rewrite" | "ask" | "pass",
        "industry": str | None,
        "industry_name": str | None,
        "confidence": float,
        "original": str,
        "rewritten_instruction": str | None,
        "rationale": [str],
        "needs_search": bool,
        "search_queries": [str],
        "search_results": [dict],
        "standards_used": [str],
        "standards_detail": [dict],
        "evidence_used": [str],
    }
    """
    # ── Step 1: Ambiguity check ──
    if not is_ambiguous_instruction(user_input):
        return _empty_plan(user_input)

    # ── Step 2: Resolve context ──
    ctx = context_resolver.resolve_context(
        conversation_context=conversation_context,
        loaded_skills=loaded_skills,
    )

    # ── Step 3: Match industry and ambiguous term ──
    top_industry = ctx["possible_industries"][0] if ctx["possible_industries"] else None
    industry_key = top_industry[0] if top_industry else None
    industry_name = top_industry[2] if top_industry else None
    confidence = ctx["confidence"]

    # ── Step 4: Look up industry-specific rewrite intent ──
    rewritten_intent = None
    if industry_key:
        rewritten_intent = industry_profiles.get_ambiguous_rewrite(industry_key, user_input.strip())

    # ── Step 5: Load local standards ──
    standards_detail: list[dict] = []
    standards_used: list[str] = []
    if industry_key:
        profile = industry_profiles.get_industry(industry_key)
        standard_keys = profile.get("local_standards", []) if profile else []
        standards_detail = standards_registry.get_standards(standard_keys)
        for s in standards_detail:
            standards_used.append(s["key"])

    # ── Step 6: Build instruction and search ──
    rewritten_instruction = None
    rationale: list[str] = []
    needs_search = False
    search_queries: list[str] = []
    search_results: list[dict] = []

    if industry_key and confidence >= MIN_CONFIDENCE_FOR_REWRITE:
        if rewritten_intent:
            rationale.append(f"Matched industry '{industry_name}', fuzzy term resolved")
        else:
            rationale.append(f"Inferred '{industry_name}' scenario from context signals")

        if standards_detail:
            std_names = [s["name"] for s in standards_detail]
            rationale.append(f"Referenced local standards: {', '.join(std_names[:3])}")

        signals = ctx.get("signals", [])
        if signals:
            rationale.append(f"Context signals: {', '.join(signals[:5])}")

        # Generate search queries
        profile = industry_profiles.get_industry(industry_key) if industry_key else None
        if profile and profile.get("search_templates"):
            needs_search = allow_web_search
            templates = profile["search_templates"]
            platform = ctx.get("current_file") or "default"
            for tmpl in templates:
                query = tmpl.replace("{platform}", str(platform).replace("_", " "))
                query = query.replace("{api_name}", str(platform))
                query = query.replace("{language}", "python")
                query = query.replace("{issue}", user_input)
                query = query.replace("{doc_type}", industry_name or "document")
                query = query.replace("{chart_type}", "data chart")
                query = query.replace("{model}", user_input)
                query = query.replace("{provider}", user_input)
                search_queries.append(query + " 2026")

            # Execute search if provider is available
            if needs_search and search_provider:
                try:
                    raw = search_provider(search_queries)
                    if isinstance(raw, list):
                        search_results = raw
                    elif isinstance(raw, dict):
                        search_results = [raw]
                except Exception as exc:
                    search_results = [{"error": str(exc)}]

        # Build full instruction using compose_instruction()
        rewritten_instruction = compose_instruction(
            original=user_input,
            industry_name=industry_name or "unknown",
            intent=rewritten_intent,
            standards=standards_detail,
            search_queries=search_queries,
            needs_search=needs_search,
        )

    # ── Step 7: Decide action ──
    if industry_key and confidence >= MIN_CONFIDENCE_FOR_REWRITE:
        action = "rewrite"
    elif industry_key and confidence >= MIN_CONFIDENCE_FOR_ASK:
        action = "ask"
    else:
        action = "pass"

    # ── Build evidence list ──
    evidence_used = [f"standard:{s['key']}" for s in standards_detail]
    if search_results:
        for sr in search_results[:3]:
            title = sr.get("title") or sr.get("name") or sr.get("url", "")
            if title:
                evidence_used.append(f"search:{title[:60]}")

    return {
        "should_rewrite": action == "rewrite",
        "action": action,
        "industry": industry_key,
        "industry_name": industry_name,
        "confidence": round(confidence, 2),
        "original": user_input,
        "rewritten_instruction": rewritten_instruction,
        "rationale": rationale,
        "needs_search": needs_search,
        "search_queries": search_queries[:3],
        "search_results": search_results[:5],
        "standards_used": standards_used,
        "standards_detail": standards_detail,
        "evidence_used": evidence_used,
    }


def _empty_plan(user_input: str) -> dict:
    return {
        "should_rewrite": False,
        "action": "pass",
        "industry": None,
        "industry_name": None,
        "confidence": 0.0,
        "original": user_input,
        "rewritten_instruction": None,
        "rationale": [],
        "needs_search": False,
        "search_queries": [],
        "search_results": [],
        "standards_used": [],
        "standards_detail": [],
        "evidence_used": [],
    }


def guardian_before_user_message(user_input: str, context: Optional[dict] = None) -> dict:
    """
    Pre-process hook for user messages — called by Hermes main loop.

    Args:
        user_input: Original user input string
        context: Session context, may contain conversation_context, loaded_skills, web_available

    Returns:
        {"action": "pass" | "rewrite", "input": str, "original_input": str, "metadata": dict}
    """
    ctx = context or {}
    result = build_rewrite_plan(
        user_input=user_input,
        conversation_context=ctx.get("conversation_context"),
        loaded_skills=ctx.get("loaded_skills"),
        allow_web_search=ctx.get("web_available", False),
    )

    if result["action"] != "rewrite":
        return {
            "action": "pass",
            "input": user_input,
            "original_input": user_input,
            "metadata": result,
        }

    return {
        "action": "rewrite",
        "input": result["rewritten_instruction"] or user_input,
        "original_input": user_input,
        "metadata": result,
    }
