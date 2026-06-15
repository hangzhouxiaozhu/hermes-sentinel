"""
Hermes Guardian — Skill 安全审查 (Phase 2)

功能: 静态扫描高危指令/硬编码密钥/恶意模式，静默判定放行/阻止。
被 guardian_core 调用，不直接输出到终端。
"""

import json
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
LOG_FILE = HERMES_HOME / "logs" / "skill_audit.log"

TRUSTED_SOURCES = [
    "agentskills.io",
    "github.com/NousResearch",
    "github.com/nousresearch",
]

# ── 高危模式库 ────────────────────────────────────────────

HIGH_RISK_PATTERNS = {
    "dangerous_shell": [
        (r"rm\s+-rf\s+/", "FATAL: rm -rf / detected"),
        (r"rm\s+-rf\s+~", "FATAL: rm -rf ~ detected"),
        (r":\(\)\s*\{\s*:\|:&\s*\};:", "FATAL: fork bomb detected"),
        (r"curl.*\|\s*(ba)?sh", "HIGH: curl-pipe-shell pattern"),
        (r"wget.*\|\s*(ba)?sh", "HIGH: wget-pipe-shell pattern"),
        (r"sudo\s+chmod\s+777\s+/", "MEDIUM: world-writable system path"),
    ],
    "hardcoded_secrets": [
        (r'sk-[a-zA-Z0-9]{20,}', "HIGH: OpenAI API key"),
        (r'sk-proj-[a-zA-Z0-9]{20,}', "HIGH: OpenAI project key"),
        (r'ghp_[a-zA-Z0-9]{36}', "HIGH: GitHub personal access token"),
        (r'gho_[a-zA-Z0-9]{36}', "HIGH: GitHub OAuth token"),
        (r'xox[bprs]-[a-zA-Z0-9]+', "HIGH: Slack token"),
        (r'tvly-[a-zA-Z0-9_-]+', "MEDIUM: Tavily API key"),
        (r'AIza[0-9A-Za-z\-_]{35}', "HIGH: Google API key"),
        (r'(?i)(api[_-]?key|apikey)\s*[:=]\s*["\']?[a-zA-Z0-9_-]{20,}', "HIGH: Generic API key assignment"),
        (r'(?i)(secret|password|token)\s*[:=]\s*["\']?[a-zA-Z0-9_-]{20,}', "HIGH: Generic secret assignment"),
        (r'(?i)(appsecret|app_secret)\s*[:=]\s*["\']?[a-zA-Z0-9]{20,}', "CRITICAL: AppSecret hardcoded"),
    ],
    "privacy_leak": [
        (r'~/.hermes/\.env', "MEDIUM: References .env path"),
        (r'HERMES_HOME.*\.env', "MEDIUM: References HERMES_HOME/.env"),
        (r'curl.*POST.*api\.telegram\.org.*token', "HIGH: Telegram bot token exfiltration"),
        (r'(upload|send).*(\.env|auth\.json|config\.yaml)', "HIGH: Potential config exfiltration"),
    ],
    "malicious_loop": [
        (r'while\s+True\s*:', "MEDIUM: Potential infinite loop"),
        (r'for\s+.*in\s+itertools\.cycle', "MEDIUM: itertools.cycle without bound"),
        (r'recursion.*depth.*\d{4,}', "MEDIUM: Excessive recursion"),
    ],
    "code_execution": [
        (r'eval\s*\(', "MEDIUM: eval() call"),
        (r'exec\s*\(', "MEDIUM: exec() call"),
        (r'__import__\s*\(', "LOW: dynamic import"),
        (r'subprocess\.(call|Popen|run)\s*\(', "INFO: subprocess call"),
        (r'os\.system\s*\(', "MEDIUM: os.system() call"),
    ],
}


def _log(action, detail, severity="INFO"):
    """写审计日志"""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "severity": severity,
        "detail": detail,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── 外部接口 ──────────────────────────────────────────────

def scan(skill_path: str) -> dict:
    """
    扫描 skill 路径，静默返回判定结果。

    返回:
    {
        "approved": True|False,
        "reason": str,           # 详细原因（写内部日志）
        "user_reason": str|None, # 用户看到的人话（approved=False 时必填）
    }
    """
    skill_path = Path(skill_path)
    skill_name = skill_path.name

    if not skill_path.exists():
        _log("scan", f"{skill_name}: not found", "ERROR")
        return {"approved": False, "reason": "Path not found", "user_reason": "找不到这个路径。"}

    all_findings = []
    scan_patterns = ["*.md", "*.py", "*.sh", "*.bash", "*.yaml", "*.yml", "*.json", "*.toml"]
    for pattern in scan_patterns:
        for f in skill_path.rglob(pattern):
            if "__pycache__" in str(f):
                continue
            findings = _scan_file(str(f))
            all_findings.extend(findings)

    # 分级判定
    severity_scores = {"FATAL": 100, "CRITICAL": 90, "HIGH": 70, "MEDIUM": 30, "LOW": 10, "INFO": 0, "ERROR": 50}
    max_severity = max((severity_scores.get(f["severity"], 0) for f in all_findings), default=0)

    source = _classify_source(str(skill_path))

    if max_severity >= 90:
        verdict = "BLOCKED"
    elif max_severity >= 50 and source != "trusted":
        verdict = "BLOCKED"
    else:
        verdict = "PASS"

    _log("scan", f"{skill_name}: {verdict} ({len(all_findings)} findings, source={source})", verdict)

    if verdict == "BLOCKED":
        reasons = [f["message"] for f in all_findings if f["severity"] in ("FATAL", "CRITICAL", "HIGH")]
        top_reason = reasons[0] if reasons else "存在安全风险"
        return {
            "approved": False,
            "reason": f"Blocked: {', '.join(reasons[:3])}",
            "user_reason": f"这个插件不太安全（{top_reason.split(':')[0].strip()}风险），我没让它装上。",
        }

    return {"approved": True, "reason": None, "user_reason": None}


def check_skill_manifest(skill_name: str) -> list:
    """
    检查已安装 skill 的 manifest 风险（env 访问等）。

    返回: [{"type": str, "severity": str, "detail": str}, ...]
    """
    warnings = []
    skill_md = HERMES_HOME / "skills" / skill_name / "SKILL.md"
    if skill_md.exists():
        content = skill_md.read_text()
        if re.search(r'\.env|getenv|environ', content, re.IGNORECASE):
            warnings.append({
                "type": "env_access",
                "severity": "MEDIUM",
                "detail": "Skill references .env or environment variable access",
            })
    return warnings


# ── 内部函数 ──────────────────────────────────────────────

def _scan_file(filepath):
    """扫描单个文件，返回发现的问题"""
    findings = []
    try:
        content = Path(filepath).read_text()
    except Exception as e:
        return [{"file": str(filepath), "severity": "ERROR", "message": f"Cannot read: {e}"}]

    for category, patterns in HIGH_RISK_PATTERNS.items():
        for pattern, message in patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                line_num = content[:match.start()].count("\n") + 1
                severity_level = message.split(":")[0].strip()
                findings.append({
                    "file": str(filepath),
                    "line": line_num,
                    "category": category,
                    "severity": severity_level,
                    "message": message,
                })

    return findings


def _classify_source(skill_path_or_url: str) -> str:
    """判定来源类型: "trusted" | "third_party" | "unknown" """
    url_lower = str(skill_path_or_url).lower()
    for source in TRUSTED_SOURCES:
        if source.lower() in url_lower:
            return "trusted"
    if "github.com" in url_lower:
        return "third_party"
    return "unknown"
