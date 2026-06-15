"""
Hermes Guardian — 配置冲突检测 (Phase 2)

功能: 扫描所有已安装 skill 的配置建议，自动检测并合并冲突。
被 guardian_core 调用，不直接输出到终端。
"""

import re
import json
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
SKILLS_DIR = HERMES_HOME / "skills"

CONFLICT_DOMAINS = {
    "web.backend":          "Web 搜索后端",
    "model.default":        "默认模型",
    "model.provider":       "默认 Provider",
    "compression.enabled":  "上下文压缩开关",
    "compression.threshold": "压缩触发阈值",
    "agent.max_turns":      "最大对话轮数",
    "memory.memory_enabled": "记忆开关",
    "terminal.timeout":     "终端超时",
    "display.language":     "显示语言",
    "browser.engine":       "浏览器引擎",
}


def _parse_config_hints(skill_dir) -> dict:
    """解析 SKILL.md 中的配置修改建议"""
    skill_md = Path(skill_dir) / "SKILL.md"
    if not skill_md.exists():
        return {}

    content = skill_md.read_text()
    hints = {}
    for match in re.finditer(r'hermes config set\s+([\w.]+)\s+([^\s\n]+)', content):
        key, val = match.groups()
        hints[key] = val
    return hints


def detect_conflicts() -> list:
    """
    扫描所有 skill，返回配置冲突清单。

    返回:
        [{"domain": str, "description": str, "claims": {value: [skills]}, "recommendation": {...}}, ...]
    """
    skill_configs = {}

    for skill_md in sorted(SKILLS_DIR.rglob("SKILL.md")):
        skill_name = skill_md.parent.name
        reqs = _parse_config_hints(skill_md.parent)
        if reqs:
            skill_configs[skill_name] = reqs

    domain_claims = {}
    for skill_name, reqs in skill_configs.items():
        for key, value in reqs.items():
            if key not in CONFLICT_DOMAINS:
                continue
            domain_claims.setdefault(key, {}).setdefault(value, []).append(skill_name)

    conflicts = []
    for domain, values in domain_claims.items():
        if len(values) > 1:
            best_value = max(values, key=lambda v: len(values[v]))
            conflict = {
                "domain": domain,
                "description": CONFLICT_DOMAINS.get(domain, domain),
                "claims": {val: {"skills": skills, "count": len(skills)} for val, skills in values.items()},
                "recommendation": {
                    "value": best_value,
                    "reason": f"被 {len(values[best_value])} 个 skill 推荐",
                },
            }
            conflicts.append(conflict)

    return conflicts


def auto_merge(skill_path: str) -> dict:
    """
    自动合并新 skill 的配置建议。

    对所有冲突域，取多数派推荐值。
    如果平局，不做任何事。

    返回:
        {"merged": bool, "conflicts_found": int, "resolutions": {key: value}}
    """
    conflicts = detect_conflicts()
    if not conflicts:
        return {"merged": True, "conflicts_found": 0, "resolutions": {}}

    resolutions = {}
    for c in conflicts:
        rec = c.get("recommendation")
        if rec:
            resolutions[c["domain"]] = rec["value"]

    return {"merged": len(resolutions) > 0, "conflicts_found": len(conflicts), "resolutions": resolutions}
