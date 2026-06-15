"""
Hermes Guardian — 隐私数据隔离 (Phase 2)

功能: 联网传输前自动过滤隐私字段 + 自动清理过期日志。
被 guardian_core 调用，不直接输出到终端。
"""

import re
import json
from datetime import datetime, timedelta
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
LOGS_DIR = HERMES_HOME / "logs"


# ── 文本脱敏 ──────────────────────────────────────────────

def sanitize_text(text: str):
    """
    对文本中的隐私字段进行脱敏。

    返回: (脱敏后文本, 发现的隐私类型列表)
    """
    findings = []

    # 身份证号（优先级最高，避免被手机号模式匹配）
    id_mask = re.sub(r'(\d{6})\d{8}(\d{4})', r'\1********\2', text)
    if id_mask != text:
        findings.append("id_card")
        text = id_mask

    # 手机号
    phone_count = len(re.findall(r'1[3-9]\d{9}', text))
    if phone_count > 0:
        findings.append(f"phone({phone_count})")
    text = re.sub(r'(1[3-9])(\d{4})(\d{4})', r'\1****\3', text)

    # 邮箱
    email_count = len(re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text))
    if email_count > 0:
        findings.append(f"email({email_count})")
    text = re.sub(
        r'([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        lambda m: f"{m.group(1)[:2]}***@{m.group(2)}",
        text
    )

    # 银行卡号
    bank_count = len(re.findall(r'\b\d{16,19}\b', text))
    if bank_count > 0:
        findings.append(f"bank_card({bank_count})")
    text = re.sub(r'\b(\d{4})\d{8,11}(\d{4})\b', r'\1 **** **** \2', text)

    return text, findings


def _sanitize_json(data):
    """递归脱敏 JSON 数据"""
    if isinstance(data, str):
        text, findings = sanitize_text(data)
        return text, findings

    if isinstance(data, dict):
        findings = []
        sanitized = {}
        for key, value in data.items():
            if isinstance(value, str):
                san_val, f = sanitize_text(value)
                sanitized[key] = san_val
                findings.extend(f)
            elif isinstance(value, (dict, list)):
                san_val, f = _sanitize_json(value)
                sanitized[key] = san_val
                findings.extend(f)
            else:
                sanitized[key] = value
        return sanitized, findings

    if isinstance(data, list):
        findings = []
        sanitized = []
        for item in data:
            if isinstance(item, str):
                san_item, f = sanitize_text(item)
                sanitized.append(san_item)
                findings.extend(f)
            elif isinstance(item, (dict, list)):
                san_item, f = _sanitize_json(item)
                sanitized.append(san_item)
                findings.extend(f)
            else:
                sanitized.append(item)
        return sanitized, findings

    return data, []


# ── 联网传输过滤（供 guardian_core 调用） ─────────────────

def filter_outgoing_data(data, task_description=""):
    """
    过滤联网传输数据中的隐私字段。
    对值做脱敏，不删除 key。

    返回:
        {"filtered": bool, "data": ...}
    """
    if isinstance(data, str):
        text, findings = sanitize_text(data)
        return {"filtered": len(findings) > 0, "data": text}

    if isinstance(data, (dict, list)):
        sanitized, findings = _sanitize_json(data)
        return {"filtered": len(findings) > 0, "data": sanitized}

    return {"filtered": False, "data": data}


# ── 日志清理（供 hardware_monitor.auto_remediate 用） ─────

def sanitize_logs(log_dir=None, days=30) -> int:
    """
    清理超过指定天数的旧日志。

    返回: 删除的文件数
    """
    log_dir = Path(log_dir or LOGS_DIR)
    if not log_dir.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=days)
    deleted = 0
    for log_file in log_dir.glob("*.log"):
        try:
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            if mtime < cutoff:
                log_file.unlink()
                deleted += 1
        except Exception:
            continue

    return deleted
