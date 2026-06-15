"""自适应指令理解 — 总入口。

当用户输入短/模糊时，判断是否需要专业重构。
整合 context_resolver、industry_profiles、standards_registry 三个模块。
"""

from typing import Any, Callable, Optional

import context_resolver
import industry_profiles
import standards_registry

# 触发模糊判断的规则阈值
MIN_CONFIDENCE_FOR_REWRITE = 0.4  # 上下文置信度 >= 此值时自动重写
MIN_CONFIDENCE_FOR_ASK = 0.2      # >= 此值但 < 重写阈值时，要求用户澄清
SHORT_INPUT_THRESHOLD = 8         # 输入 <= 此长度视为短输入

# 常见模糊词汇（精确匹配）
VAGUE_WORDS: set[str] = {
    "太暗", "太亮", "乱码", "继续", "不对", "不好看", "太乱",
    "改一下", "和上次一样", "再看看", "优化", "太贵", "太慢",
    "太啰嗦", "太短", "没人看", "数据差", "没流量", "跑不起来",
    "看不出", "太乱", "不对齐",
}


def is_ambiguous_instruction(text: str) -> bool:
    """
    判断用户输入是否为模糊指令。

    规则：
    1. 输入在模糊词表中（精确匹配）
    2. 输入 <= SHORT_INPUT_THRESHOLD 且不包含具体宾语词

    返回 True 表示需要进一步分析。
    """
    stripped = text.strip()

    # 精确匹配模糊词
    if stripped in VAGUE_WORDS:
        return True

    # 短输入且不含具体宾语
    if len(stripped) <= SHORT_INPUT_THRESHOLD:
        concrete_objects = {"文件", "图片", "代码", "标题", "表格", "页面",
                            "封面", "文章", "报告", "脚本", "数据", "邮件",
                            "文档", "笔记", "配置", "模型", "API"}
        has_object = any(obj in stripped for obj in concrete_objects)
        if not has_object:
            return True

    return False


def build_rewrite_plan(
    user_input: str,
    conversation_context: Optional[dict] = None,
    loaded_skills: Optional[list[dict]] = None,
    allow_web_search: bool = False,
    search_provider: Optional[Callable] = None,
) -> dict:
    """
    判断是否需要重写用户输入，返回结构化 rewrite plan。

    参数:
        user_input: 用户原始输入
        conversation_context: Hermes 提供的会话上下文
        loaded_skills: 已加载 skill 列表
        allow_web_search: 是否允许联网搜索
        search_provider: 外部搜索函数（由调用方注入）

    返回:
    {
        "should_rewrite": bool,       # 是否需要重写
        "action": str,                # "rewrite" | "ask" | "pass"
        "industry": str | None,       # 匹配到的行业 key
        "industry_name": str | None,  # 行业中文名
        "confidence": float,          # 行业匹配置信度
        "original": str,              # 用户原始输入
        "rewritten_instruction": str | None,  # 重写后的完整指令
        "rationale": list[str],       # 重写理由
        "needs_search": bool,         # 是否建议搜索
        "search_queries": list[str],  # 建议的搜索词
        "standards_used": list[str],  # 用到的标准 key
        "standards_detail": list[dict],  # 标准详情
    }
    """
    # ── 第一步：判断是否为模糊指令 ──
    if not is_ambiguous_instruction(user_input):
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
            "standards_used": [],
            "standards_detail": [],
        }

    # ── 第二步：解析上下文 ──
    ctx = context_resolver.resolve_context(
        conversation_context=conversation_context,
        loaded_skills=loaded_skills,
    )

    # ── 第三步：匹配行业和模糊术语 ──
    top_industry = ctx["possible_industries"][0] if ctx["possible_industries"] else None
    industry_key = top_industry[0] if top_industry else None
    industry_name = top_industry[2] if top_industry else None
    confidence = ctx["confidence"]

    # ── 第四步：查找行业特定改写 ──
    rewritten_intent = None
    if industry_key:
        rewritten_intent = industry_profiles.get_ambiguous_rewrite(industry_key, user_input.strip())

    # ── 第五步：加载本地标准 ──
    standards_detail = []
    standards_used = []
    if industry_key:
        profile = industry_profiles.get_industry(industry_key)
        standard_keys = profile.get("local_standards", []) if profile else []
        standards_detail = standards_registry.get_standards(standard_keys)
        for s in standards_detail:
            standards_used.append(s["key"])

    # ── 第六步：构建重写指令 ──
    rewritten_instruction = None
    rationale: list[str] = []
    needs_search = False
    search_queries: list[str] = []

    if industry_key and confidence >= MIN_CONFIDENCE_FOR_REWRITE:
        if rewritten_intent:
            rewritten_instruction = rewritten_intent
            rationale.append(f"匹配行业「{industry_name}」中的模糊术语")
        else:
            rewritten_instruction = (
                f"根据当前「{industry_name}」场景，"
                f"优化处理：{user_input}"
            )
            rationale.append(f"推断为「{industry_name}」场景")

        if standards_detail:
            std_names = [s["name"] for s in standards_detail]
            rationale.append(f"参考本地标准：{'、'.join(std_names[:3])}")

        rationale.append(f"上下文信号词：{', '.join(ctx['signals'][:5])}")

        # 搜索
        profile = industry_profiles.get_industry(industry_key)
        if profile and profile.get("search_templates"):
            needs_search = allow_web_search
            templates = profile["search_templates"]
            platform = ctx.get("current_file") or "默认"
            for tmpl in templates:
                query = tmpl.replace("{platform}", str(platform).replace("_", " "))
                query = query.replace("{api_name}", str(platform))
                query = query.replace("{language}", "python")
                query = query.replace("{issue}", user_input)
                query = query.replace("{doc_type}", industry_name or "文档")
                query = query.replace("{chart_type}", "数据图表")
                query = query.replace("{model}", user_input)
                query = query.replace("{provider}", user_input)
                search_queries.append(query + " 2026")

            if needs_search and search_provider:
                try:
                    search_provider(search_queries)
                except Exception:
                    pass

    # ── 第七步：决定动作 ──
    if industry_key and confidence >= MIN_CONFIDENCE_FOR_REWRITE:
        action = "rewrite"
    elif industry_key and confidence >= MIN_CONFIDENCE_FOR_ASK:
        action = "ask"
    else:
        action = "pass"

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
        "standards_used": standards_used,
        "standards_detail": standards_detail,
    }


def guardian_before_user_message(user_input: str, context: Optional[dict] = None) -> dict:
    """
    用户消息前置 hook — 在 Hermes 主循环中调用。

    参数:
        user_input: 用户原始输入
        context: 会话上下文，至少包含 loaded_skills、web_available 等

    返回:
    {
        "action": "pass" | "rewrite",
        "input": str,           # 重写后的输入（或原始输入）
        "original_input": str,  # 原始输入
        "metadata": dict,       # rewrite_plan 完整信息
    }
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
