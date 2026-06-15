"""行业识别表。

第一版用规则表，不做复杂 AI 分类。
"""
from typing import Optional

# Signals that strongly indicate a specific industry (not generic).
# Used to boost confidence in match_industry().
STRONG_SIGNALS = {
    "new_media_visual_design": {"封面", "海报", "公众号", "渲染", "缩略图", "banner", "头图"},
    "social_media_content": {"小红书", "种草", "笔记", "抖音", "视频号"},
    "software_engineering": {"代码", "报错", "乱码", "API", "Python", "JSON", "编码", "git", "bug"},
    "ai_operations": {"token", "模型", "provider", "deepseek", "openai", "claude"},
    "document_writing": {"PPT", "周报", "报告", "文档", "提纲", "邮件"},
    "data_analysis": {"表格", "报表", "图表", "可视化", "CSV", "Excel", "SQL"},
}

INDUSTRY_PROFILES = {
    "new_media_visual_design": {
        "name": "新媒体视觉设计",
        "signals": [
            "公众号", "封面", "小红书", "海报", "标题", "缩略图",
            "渲染", "封面图", "配图", "banner", "头图",
        ],
        "ambiguous_terms": {
            "太暗": "提升亮度、对比度和移动端视觉锚点",
            "太亮": "降低曝光，恢复细节层次",
            "不好看": "检查层级、留白、字体、色彩和平台风格一致性",
            "太乱": "简化布局，强化视觉重心，减少信息密度",
            "不对齐": "检查网格对齐、边距一致性和元素间距",
        },
        "search_templates": [
            "{platform} 封面设计 移动端 可读性 最佳实践 2026",
            "{platform} 封面 色彩 对比度 缩略图 辨识度",
        ],
        "local_standards": [
            "mobile_readability",
            "thumbnail_legibility",
            "brand_color_consistency",
        ],
    },
    "social_media_content": {
        "name": "社交媒体内容运营",
        "signals": [
            "小红书", "笔记", "文案", "抖音", "视频号", "朋友圈",
            "种草", "标题", "封面文案",
        ],
        "ambiguous_terms": {
            "没人看": "检查标题吸引力、封面点击率和内容选题热度",
            "数据差": "分析完播率、互动率和发布时间",
            "没流量": "检查关键词覆盖、话题标签和平台推荐机制",
        },
        "search_templates": [
            "{platform} 内容运营 爆款 标题技巧 2026",
        ],
        "local_standards": [
            "platform_tone",
            "hashtag_strategy",
        ],
    },
    "software_engineering": {
        "name": "软件工程",
        "signals": [
            "代码", "报错", "乱码", "API", "Python", "JSON", "编码",
            "脚本", "函数", "bug", "配置", "git", "commit", "分支",
        ],
        "ambiguous_terms": {
            "乱码": "检查编码、响应头、序列化参数和终端/文件读写 charset",
            "报错": "定位堆栈、复现路径、最小修复和回归测试",
            "跑不起来": "检查依赖版本、环境变量、路径和权限",
            "优化": "分析性能瓶颈、减少冗余计算、增加缓存",
        },
        "search_templates": [
            "{api_name} charset utf-8 best practices python",
            "{language} {issue} common causes solutions",
        ],
        "local_standards": [
            "minimal_patch",
            "tests_first_for_regression",
            "utf8_headers",
        ],
    },
    "ai_operations": {
        "name": "AI 运维",
        "signals": [
            "token", "API", "模型", "调用", "超时", "报错", "provider",
            "deepseek", "openai", "claude", "费用",
        ],
        "ambiguous_terms": {
            "太贵": "检查模型选择、token 用量和缓存策略",
            "太慢": "检查模型延迟、并发限制和网络延迟",
            "报错": "检查 API Key、配额、限频和模型兼容性",
        },
        "search_templates": [
            "{provider} API pricing latest 2026",
            "{model} known issues error solutions",
        ],
        "local_standards": [
            "cost_budget",
            "provider_fallback",
        ],
    },
    "document_writing": {
        "name": "文档与写作",
        "signals": [
            "文档", "文章", "报告", "PPT", "周报", "日报", "邮件",
            "方案", "总结", "提纲",
        ],
        "ambiguous_terms": {
            "太啰嗦": "精简句子，删除冗余修饰，保持核心信息密度",
            "太短": "补充细节、数据支撑和案例说明",
            "改一下": "明确修改方向：结构/语气/篇幅/重点",
        },
        "search_templates": [
            "{doc_type} 写作规范 格式最佳实践 2026",
        ],
        "local_standards": [
            "document_template",
            "writing_tone",
        ],
    },
    "data_analysis": {
        "name": "数据分析",
        "signals": [
            "表格", "数据", "报表", "统计", "图表", "可视化",
            "CSV", "Excel", "SQL", "看板",
        ],
        "ambiguous_terms": {
            "看不出": "明确分析维度：趋势/分布/对比/异常",
            "太乱": "简化图表、聚焦核心指标、优化排版",
            "不对": "检查数据源、计算公式和筛选条件",
        },
        "search_templates": [
            "{chart_type} 数据可视化 最佳实践 2026",
        ],
        "local_standards": [
            "data_validation",
            "chart_style",
        ],
    },
}


def get_industry(industry_key: str) -> Optional[dict]:
    """按 key 获取行业配置"""
    return INDUSTRY_PROFILES.get(industry_key)


def match_industry(text_signals: list[str]) -> list[tuple[str, float, str]]:
    """
    Match signals to industries, return [(key, score, name), ...] sorted descending.

    Scoring:
      - Base: min(matches / 3, 1.0) — capped at 3 matches, so more context
        signals don't dilute the score.
      - Boost: +0.2 per strong signal, max +0.4.
      - Final clipped to [0, 1].
    """
    text_lower = [s.lower() for s in text_signals]
    results = []
    for key, profile in INDUSTRY_PROFILES.items():
        matches = sum(1 for sig in profile["signals"]
                      if any(sig.lower() in t for t in text_lower))
        if matches == 0:
            continue

        # Base: bounded by 3
        score = min(matches / 3.0, 1.0)

        # Boost: strong signals
        strong_set = STRONG_SIGNALS.get(key, set())
        strong_matches = sum(1 for sig in strong_set
                             if any(sig.lower() in t for t in text_lower))
        boost = min(strong_matches * 0.2, 0.4)

        final_score = min(score + boost, 1.0)
        results.append((key, round(final_score, 2), profile["name"]))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def get_ambiguous_rewrite(industry_key: str, term: str) -> Optional[str]:
    """获取某行业中某模糊术语的专业改写意图"""
    profile = INDUSTRY_PROFILES.get(industry_key)
    if not profile:
        return None
    return profile["ambiguous_terms"].get(term)


def get_search_templates(industry_key: str) -> list[str]:
    """获取某行业的搜索模板"""
    profile = INDUSTRY_PROFILES.get(industry_key)
    return profile["search_templates"] if profile else []


def get_industry_names() -> list[str]:
    """返回所有行业名称"""
    return [p["name"] for p in INDUSTRY_PROFILES.values()]
