"""Adaptive instruction understanding — main entry point.

When user input is short or ambiguous, uses a 4-layer engine to determine
whether professional rewriting is needed. Integrates:

1. Ambiguity detection (is_ambiguous_instruction)
2. Context resolution   (context_resolver)
3. Industry matching    (industry_profiles)
4. Evidence scoring     (evidence_scorer)
5. Search integration   (query_builder)
6. Standards register   (standards_registry)
"""

from typing import Any, Callable, Optional

import context_resolver
import evidence_scorer
import industry_profiles
import query_builder
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

# Do-not-rewrite list
DO_NOT_REWRITE: set[str] = {
    "yes", "no", "好", "不用", "取消", "停",
    "继续运行", "提交", "保存", "exit", "quit",
}


def is_ambiguous_instruction(text: str) -> bool:
    """Return True if the input is short/ambiguous and may need rewriting.

    Excludes denylisted terms (explicit commands like "continue running").
    """
    stripped = text.strip().lower()
    if stripped in DO_NOT_REWRITE:
        return False
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
    search_results: Optional[list[dict]] = None,
    conflicts: Optional[list[dict]] = None,
) -> str:
    """
    Build a complete, actionable instruction from intent + standards + search evidence.

    This is the "professional output" — multi-sentence, principle-driven,
    referencing both local standards and current industry evidence.
    """
    lines: list[str] = []

    if intent:
        lines.append(
            f"Based on the current scenario ({industry_name}), "
            f"address the user's feedback: 「{original}」."
        )
        lines.append(f"Objective: {intent}.")
    else:
        lines.append(
            f"Handle the user's input 「{original}」 "
            f"within the {industry_name} context."
        )

    if standards:
        lines.append("Follow these local standards during execution:")
        for s in standards[:3]:
            lines.append(f"  - {s['name']}: {s['description']}")

    # ── Search evidence ──
    search_evidence = evidence_scorer.summarize_search_evidence(search_results or [])
    if search_evidence:
        lines.append("Reference current industry best practices:")
        for item in search_evidence[:2]:
            lines.append(f"  - {item}")

    # ── Conflicts ──
    if conflicts:
        for c in conflicts[:2]:
            lines.append(f"⚠️ Conflict detected ({c.get('type', '')}): {c.get('detail', '')}")

    if search_queries and not search_results:
        if needs_search:
            lines.append("Before executing, verify against current industry practices:")
        else:
            lines.append("If online verification is available, consider these directions:")
        for q in search_queries[:2]:
            lines.append(f"  - {q}")

    lines.append(
        "Output must be a complete, actionable plan — "
        "not a single-parameter adjustment."
    )
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

    Returns detailed metadata including evidence scoring, search results,
    conflicts, and the full rewritten instruction.
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

    # ── Risk control: multiple industries with similar scores → ask
    multi_industry_tie = False
    if len(ctx.get("possible_industries", [])) >= 2:
        scores = [p[1] for p in ctx["possible_industries"][:3]]
        if len(scores) >= 2 and abs(scores[0] - scores[1]) < 0.15:
            multi_industry_tie = True

    # ── Step 4: Look up industry-specific rewrite intent ──
    rewritten_intent: Optional[str] = None
    if industry_key:
        rewritten_intent = industry_profiles.get_ambiguous_rewrite(
            industry_key, user_input.strip()
        )

    # ── Step 5: Load local standards ──
    standards_detail: list[dict] = []
    standards_used: list[str] = []
    if industry_key:
        profile = industry_profiles.get_industry(industry_key)
        standard_keys = profile.get("local_standards", []) if profile else []
        standards_detail = standards_registry.get_standards(standard_keys)
        for s in standards_detail:
            standards_used.append(s["key"])

    # ── Step 6: Build search queries (clean, no file paths) ──
    needs_search = False
    search_queries: list[str] = []
    search_results: list[dict] = []

    if industry_key:
        profile = industry_profiles.get_industry(industry_key)
        templates = (profile.get("search_templates") or []) if profile else []
        if templates:
            needs_search = allow_web_search
            search_queries = query_builder.build_search_queries(
                industry_key=industry_key,
                user_input=user_input,
                ctx=ctx,
                templates=templates,
            )

            if needs_search and search_provider and search_queries:
                try:
                    raw = search_provider(search_queries)
                    if isinstance(raw, list):
                        search_results = raw
                    elif isinstance(raw, dict):
                        search_results = [raw]
                except Exception as exc:
                    search_results = [{"error": str(exc)}]

    # ── Step 7: Score evidence ──
    ev = evidence_scorer.score_evidence(
        context_confidence=confidence,
        local_standards=standards_detail,
        search_results=search_results,
    )

    # ── Step 8: Detect conflicts ──
    conflicts = evidence_scorer.detect_evidence_conflicts(
        standards=standards_detail,
        search_results=search_results,
    )

    # ── Step 9: Build rationale ──
    rationale: list[str] = []
    rewritten_instruction: Optional[str] = None

    if industry_key and confidence >= MIN_CONFIDENCE_FOR_REWRITE and not multi_industry_tie:
        if rewritten_intent:
            rationale.append(f"Matched industry '{industry_name}', fuzzy term resolved")
        else:
            rationale.append(f"Inferred '{industry_name}' scenario from context")

        if standards_detail:
            std_names = [s["name"] for s in standards_detail]
            rationale.append(f"Referenced local standards: {', '.join(std_names[:3])}")

        signals = ctx.get("signals", [])
        if signals:
            rationale.append(f"Context signals: {', '.join(signals[:5])}")

        if ev["sources"]:
            rationale.append(f"Evidence sources: {', '.join(ev['sources'])}")

        rewritten_instruction = compose_instruction(
            original=user_input,
            industry_name=industry_name or "unknown",
            intent=rewritten_intent,
            standards=standards_detail,
            search_queries=search_queries,
            needs_search=needs_search,
            search_results=search_results,
            conflicts=conflicts,
        )

    # ── Step 10: Decide action ──
    if multi_industry_tie:
        action = "ask"
    elif industry_key and confidence >= MIN_CONFIDENCE_FOR_REWRITE:
        action = "rewrite"
    elif industry_key and confidence >= MIN_CONFIDENCE_FOR_ASK:
        action = "ask"
    else:
        action = "pass"

    # ── Build evidence list ──
    evidence_used: list[str] = [f"standard:{s['key']}" for s in standards_detail]
    for sr in search_results[:3]:
        if "error" not in sr:
            title = sr.get("title") or sr.get("name") or sr.get("url", "")
            if title:
                evidence_used.append(f"search:{title[:80]}")

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
        "evidence_score": ev["score"],
        "evidence_sources": ev["sources"],
        "evidence_complete": ev["complete"],
        "evidence_used": evidence_used,
        "conflicts": conflicts,
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
        "evidence_score": 0.0,
        "evidence_sources": [],
        "evidence_complete": False,
        "evidence_used": [],
        "conflicts": [],
    }


def guardian_before_user_message(user_input: str, context: Optional[dict] = None) -> dict:
    """
    Pre-process hook for user messages — called by Hermes main loop.

    Args:
        user_input: Original user input string
        context: Session context dict (may contain conversation_context, loaded_skills, web_available)

    Returns:
        {"action": "pass" | "rewrite" | "ask", "input": str, "original_input": str, "metadata": dict}
    """
    ctx = context or {}
    result = build_rewrite_plan(
        user_input=user_input,
        conversation_context=ctx.get("conversation_context"),
        loaded_skills=ctx.get("loaded_skills"),
        allow_web_search=ctx.get("web_available", False),
    )

    if result["action"] == "rewrite":
        return {
            "action": "rewrite",
            "input": result["rewritten_instruction"] or user_input,
            "original_input": user_input,
            "metadata": result,
        }

    if result["action"] == "ask":
        industries = result.get("industry_name") or "unknown"
        return {
            "action": "ask",
            "input": user_input,
            "original_input": user_input,
            "metadata": {
                **result,
                "clarifying_question": (
                    f"I see this could relate to '{industries}' or another context. "
                    f"Could you clarify what you're working on?"
                ),
            },
        }

    return {
        "action": "pass",
        "input": user_input,
        "original_input": user_input,
        "metadata": result,
    }
