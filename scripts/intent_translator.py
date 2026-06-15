"""Intent translator — turns fuzzy user input into clear, actionable instructions for Hermes.

Keeps the "beginner-friendly instruction completion" value without the
heavy industry-coordinate-system, web-search, or multi-source verification.
"""

from pathlib import Path
from typing import Optional

# ── Fuzzy word → (category, instruction template) ──────────────
# The instruction is a plain-text prompt that tells Hermes what to do.
VAGUE_WORDS: dict[str, tuple[str, str]] = {
    # ── Visual ──
    "太暗": ("视觉调整",
             "用户觉得当前视觉结果太暗。先判断当前对象是图片、网页还是文档；"
             "如果是图片/封面，适当提高整体亮度和标题对比度，"
             "检查缩略图和移动端可读性，避免过曝。"),
    "太亮": ("视觉调整",
             "用户觉得太亮。适当降低亮度或曝光，恢复细节层次，检查是否过曝。"),
    "不好看": ("视觉调整",
               "用户对视觉效果不满意。检查布局、留白、字体、色彩和整体风格一致性。"),
    "太乱": ("视觉调整",
             "用户觉得布局太乱。简化布局，强化视觉重心，减少信息密度。"),
    "看不清": ("视觉调整",
               "用户看不清内容。提高字体大小、对比度和元素间距，检查可读性。"),
    "不对": ("通用调整",
             "用户指出有问题。根据上下文判断问题类型（视觉/编码/内容），"
             "确认理解后再修改，避免盲目改动。"),
    "改一下": ("通用调整",
               "用户要求修改。先确认具体要改什么（内容/样式/结构），再执行最小修改。"),
    "和上次一样": ("通用调整",
                    "用户希望沿用之前的方式。如果会话历史中有操作记录，照上次流程执行。"),

    # ── Code / API ──
    "乱码": ("编码修复",
             "用户遇到乱码。检查：文件读写 encoding='utf-8'、"
             "HTTP 响应头 charset=utf-8、JSON 序列化 ensure_ascii=False、"
             "终端显示编码；修复后用最小测试验证中文正常显示。"),
    "报错": ("代码调试",
             "用户遇到报错。查看错误信息确定问题位置，提出最小可复现方案和修复建议。"),
    "跑不起来": ("运行修复",
                 "程序跑不起来。检查：依赖版本兼容性、环境变量配置、"
                 "文件路径和权限、Python 版本要求。"),
    "没反应": ("运行修复",
               "没有响应。检查是否卡在等待、超时设置过短、或需要确认交互。"),

    # ── Hermes usage ──
    "太慢": ("性能优化",
             "用户觉得响应慢。检查：模型选择（是否用了大模型）、"
             "请求内容长度、网络延迟、是否有不必要的重试。"),
    "太贵": ("成本检查",
             "用户觉得费用高。检查：是否用了高成本模型、"
             "token 用量是否合理、有无重复调用。建议性价比方案。"),
    "连不上": ("网络检查",
               "连不上服务。检查：网络连通性、代理/VPN 配置、"
               "API Key 有效性、服务是否在维护中。"),
    "没输出": ("运行修复",
               "没有输出结果。检查：是否卡在等待工具返回、"
               "API 配额是否用尽、是否需要确认交互。"),

    # ── Document / Writing ──
    "太啰嗦": ("文本精简",
               "用户觉得内容太啰嗦。简化表达，删除冗余修饰，"
               "保持核心信息密度，段落不超过 5 行。"),
    "太短": ("内容扩充",
             "用户觉得内容太短。补充细节、数据支撑、案例或扩展说明。"),
    "看不懂": ("内容简化",
               "用户看不懂。降低复杂度，用更通俗的语言解释，"
               "增加示例和步骤说明。"),
}


def translate(user_input: str, current_file: Optional[str] = None) -> dict:
    """
    Translate fuzzy user input into a clear instruction for Hermes.

    Args:
        user_input: The user's original input string
        current_file: Path of the file the user is working on (optional)

    Returns:
    {
        "should_translate": bool,   # True if a translation was applied
        "translated": str | None,   # The rewritten instruction
        "rationale": str,           # Why this translation was applied
        "category": str | None,     # The intent category
    }
    """
    stripped = user_input.strip()

    # ── Skip non-fuzzy inputs ──
    if stripped in {"yes", "no", "好", "不用", "取消", "停", "继续运行", "提交", "保存", "exit", "quit"}:
        return _passthrough(stripped)

    # ── Exact fuzzy word match ──
    if stripped in VAGUE_WORDS:
        category, instruction = VAGUE_WORDS[stripped]
        rationale = f"检测到模糊指令「{stripped}」，已翻译为具体操作方案"
        # Add context hint if available
        if current_file:
            hint = _context_hint(current_file, instruction)
            if hint:
                instruction = hint + instruction
        return {
            "should_translate": True,
            "translated": instruction,
            "rationale": rationale,
            "category": category,
        }

    # ── Short inputs (≤8 chars) without concrete object ──
    if len(stripped) <= 8:
        concrete_objects = {"文件", "图片", "代码", "标题", "表格", "页面",
                            "封面", "文章", "报告", "脚本", "数据", "邮件",
                            "文档", "笔记", "配置", "模型", "API"}
        if not any(obj in stripped for obj in concrete_objects):
            return {
                "should_translate": False,
                "translated": None,
                "rationale": f"输入「{stripped}」较短但不匹配模糊词表，不做翻译",
                "category": None,
            }

    return _passthrough(stripped)


def _context_hint(current_file: str, instruction: str) -> str:
    """Add a one-line context hint based on current file path."""
    f = current_file.lower()
    if any(t in f for t in [".png", ".jpg", ".jpeg", ".gif", ".svg", ".psd"]):
        return "当前操作对象是图片/设计文件。"
    if any(t in f for t in [".py", ".js", ".ts", ".java", ".go"]):
        return "当前操作对象是代码文件。"
    if ".md" in f or ".txt" in f:
        return "当前操作对象是文档。"
    if ".xlsx" in f or ".csv" in f:
        return "当前操作对象是数据表。"
    return ""


def _passthrough(user_input: str) -> dict:
    return {
        "should_translate": False,
        "translated": None,
        "rationale": "输入无需翻译",
        "category": None,
    }
