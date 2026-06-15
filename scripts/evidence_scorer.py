"""Evidence scorer — tri-source confidence model + conflict detection.

Combines context confidence, local standards, and web search results
into a unified evidence score. Detects conflicts between standards and
search results.
"""

from typing import Any


def score_evidence(
    context_confidence: float,
    local_standards: list[dict],
    search_results: list[dict],
) -> dict:
    """
    Score evidence from three sources.

    Returns:
    {
        "score": float,          # 0-1, overall evidence confidence
        "sources": [str],        # which sources contributed
        "complete": bool,        # >= 2 sources available
    }
    """
    score = 0.0
    sources: list[str] = []

    if context_confidence >= 0.4:
        score += 0.35
        sources.append("context")

    if local_standards:
        score += 0.35
        sources.append("local_standards")

    if search_results:
        # Only count non-error results
        valid = [r for r in search_results if "error" not in r]
        if valid:
            score += 0.30
            sources.append("web_search")

    return {
        "score": round(min(score, 1.0), 2),
        "sources": sources,
        "complete": len(sources) >= 2,
    }


def detect_evidence_conflicts(
    standards: list[dict],
    search_results: list[dict],
) -> list[dict]:
    """
    Detect conflicts between local standards and web search results.

    Returns list of conflict dicts, empty if no conflicts found.
    """
    conflicts: list[dict] = []

    # Join all search text for keyword matching
    search_text = " ".join(
        str(r.get("summary") or r.get("snippet") or r.get("title") or "")
        for r in search_results
    ).lower()

    for s in standards:
        desc = (s.get("description") or "").lower()
        key = s.get("key", "")

        # Brand color: local says warm white #fdfcf9, search says dark background
        if "#fdfcf9" in desc or "暖白" in desc:
            if "dark background" in search_text or "深色背景" in search_text:
                conflicts.append({
                    "standard": key,
                    "type": "style_conflict",
                    "detail": (
                        "Local standard prefers warm white (#fdfcf9); "
                        "search results mention dark background. "
                        "Prioritize user's existing brand standard; "
                        "only switch to dark if explicitly requested."
                    ),
                })

        # Mobile-first: local says mobile, search says desktop-only
        if "移动端" in desc or "mobile" in desc:
            if "desktop only" in search_text or "桌面端" in search_text:
                conflicts.append({
                    "standard": key,
                    "type": "platform_conflict",
                    "detail": (
                        "Local standard requires mobile-friendly output; "
                        "search suggests desktop-only approach. "
                        "Prioritize mobile-compatible solution."
                    ),
                })

    return conflicts


def summarize_search_evidence(search_results: list[dict]) -> list[str]:
    """Extract readable evidence items from search results."""
    evidence: list[str] = []
    for r in search_results[:3]:
        if "error" in r:
            continue
        title = r.get("title") or r.get("name") or ""
        summary = r.get("summary") or r.get("snippet") or ""
        if title and summary:
            evidence.append(f"{title}: {summary}")
        elif summary:
            evidence.append(summary)
        elif title:
            evidence.append(title)
    return evidence
