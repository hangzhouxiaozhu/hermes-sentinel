"""本地标准注册表 — 读取 skill/memory/本地规则中的用户偏好和专业标准。

第一版使用内置标准 + 扫描本地 skill 的 SKILL.md。
后续可扩展为从 ~/.hermes/memories/ 读取用户偏好。
"""

import re
from pathlib import Path
from typing import Any, Optional

HERMES_HOME = Path.home() / ".hermes"

# ── 内置标准（第一版硬编码，后续从 skill/memory 动态加载） ──
BUILTIN_STANDARDS: dict[str, dict[str, Any]] = {
    "mobile_readability": {
        "name": "移动端可读性",
        "description": "移动端 feed 流需在 0.3 秒内建立视觉锚点，标题/关键信息在缩略图模式下可辨识",
        "source": "builtin",
    },
    "thumbnail_legibility": {
        "name": "缩略图辨识度",
        "description": "200×200 像素缩略图下标题仍可辨识，对比度不低于 WCAG AA 标准",
        "source": "builtin",
    },
    "brand_color_consistency": {
        "name": "品牌色彩一致性",
        "description": "保持品牌色系一致性，暖白底色 #fdfcf9，主色调 #1a1a2e，强调色金色",
        "source": "builtin",
    },
    "minimal_patch": {
        "name": "最小改动原则",
        "description": "修复问题时只修改相关行，不重构未涉及的代码",
        "source": "builtin",
    },
    "tests_first_for_regression": {
        "name": "回归测试优先",
        "description": "修改 bug 前先写可复现的测试用例，确保修复不破坏已有功能",
        "source": "builtin",
    },
    "utf8_headers": {
        "name": "UTF-8 编码头",
        "description": "HTTP 响应需包含 Content-Type charset=utf-8，Python 文件写 ensure_ascii=False",
        "source": "builtin",
    },
    "platform_tone": {
        "name": "平台语气风格",
        "description": "根据平台调性调整语气：小红书亲切专业，公众号正式有深度",
        "source": "builtin",
    },
    "hashtag_strategy": {
        "name": "话题标签策略",
        "description": "每篇笔记 3-5 个标签，覆盖大词+长尾词，与内容高度相关",
        "source": "builtin",
    },
    "document_template": {
        "name": "文档模板规范",
        "description": "按项目标准模板组织文档结构：背景→方案→预期效果",
        "source": "builtin",
    },
    "writing_tone": {
        "name": "写作语气",
        "description": "保持简洁直接，避免冗余修饰，段落不超过 5 行",
        "source": "builtin",
    },
    "cost_budget": {
        "name": "成本预算控制",
        "description": "优先使用性价比模型，避免不必要的大模型调用",
        "source": "builtin",
    },
    "provider_fallback": {
        "name": "提供商容灾",
        "description": "API 调用失败时自动按优先级列表切换提供商",
        "source": "builtin",
    },
    "data_validation": {
        "name": "数据验证",
        "description": "分析前检查数据完整性、空值和异常值",
        "source": "builtin",
    },
    "chart_style": {
        "name": "图表风格",
        "description": "使用品牌色系，图例清晰，坐标轴标注完整",
        "source": "builtin",
    },
}


def get_standards(keys: list[str]) -> list[dict[str, Any]]:
    """
    按 key 获取标准列表。

    参数:
        keys: 标准键名列表

    返回:
        [{"key": str, "name": str, "description": str, "source": str}, ...]
    """
    results = []
    for key in keys:
        standard = BUILTIN_STANDARDS.get(key)
        if standard:
            results.append({"key": key, **standard})
    return results


def scan_skill_standards(skill_name: str) -> list[dict[str, Any]]:
    """
    扫描指定 skill 的 SKILL.md 中是否有可识别的标准。

    返回:
        [{"key": str, "name": str, "description": str, "source": "skill:xxx"}, ...]
    """
    results = []
    for skill_md in HERMES_HOME.rglob(f"skills/**/{skill_name}/SKILL.md"):
        if skill_md.exists():
            try:
                content = skill_md.read_text()
                # 简单规则：SKILL.md 中的 "标准" 或 "规范" 章节
                standards_section = re.split(
                    r"##\s*(?:标准|规范|规则|standards|rules)",
                    content, flags=re.IGNORECASE,
                )
                if len(standards_section) > 1:
                    body = standards_section[1].split("##")[0].strip()
                    # 提取列表项作为标准
                    items = re.findall(r"[-*]\s*(.+?)(?:\n|$)", body)
                    for item in items[:10]:
                        key = f"skill_{skill_name}_{len(results)}"
                        results.append({
                            "key": key,
                            "name": item[:40],
                            "description": item,
                            "source": f"skill:{skill_name}",
                        })
            except Exception:
                continue
    return results


def get_all_standard_keys() -> list[str]:
    """返回所有内置标准键名"""
    return sorted(BUILTIN_STANDARDS.keys())
