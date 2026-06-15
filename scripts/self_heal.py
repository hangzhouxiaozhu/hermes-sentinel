"""
Hermes Guardian — 故障检测 (Phase 2)

功能: API 连通性快速检查 + 自动恢复。
被 guardian_core 调用，不直接输出到终端。
"""

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
LOG_FILE = HERMES_HOME / "logs" / "self_heal.log"
SKILLS_DIR = HERMES_HOME / "skills"


def _log(action, detail, success=True):
    """写内部日志（静默）"""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "detail": detail,
        "success": success,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _check_api():
    """检查 API Provider 连通性"""
    results = []
    tests = {
        "deepseek": "https://api.deepseek.com",
        "openrouter": "https://openrouter.ai",
    }

    for provider, url in tests.items():
        try:
            r = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "10", url],
                capture_output=True, text=True, timeout=15
            )
            status = int(r.stdout.strip()) if r.stdout.strip().isdigit() else 0
            ok = 200 <= status < 300
            results.append({"provider": provider, "reachable": ok, "http_status": status})
            if not ok:
                _log("check_api", f"{provider}: HTTP {status}", success=False)
        except Exception as e:
            results.append({"provider": provider, "reachable": False, "error": str(e)})
            _log("check_api", f"{provider}: unreachable - {e}", success=False)

    return results


def _check_skills():
    """检查已安装 skill 的 YAML frontmatter 完整性"""
    results = []
    if not SKILLS_DIR.exists():
        return results

    for skill_md in SKILLS_DIR.rglob("SKILL.md"):
        try:
            content = skill_md.read_text()
            if not content.startswith("---"):
                results.append({"skill": str(skill_md.relative_to(SKILLS_DIR)), "status": "broken", "reason": "no frontmatter"})
                _log("check_skills", f"{skill_md}: no frontmatter", success=False)
                continue

            parts = content.split("---", 2)
            if len(parts) < 3:
                results.append({"skill": str(skill_md.relative_to(SKILLS_DIR)), "status": "broken", "reason": "malformed frontmatter"})
                _log("check_skills", f"{skill_md}: malformed frontmatter", success=False)
                continue

            frontmatter = parts[1].strip()
            if "name:" not in frontmatter:
                results.append({"skill": str(skill_md.relative_to(SKILLS_DIR)), "status": "broken", "reason": "missing 'name' field"})
                _log("check_skills", f"{skill_md}: missing name", success=False)
                continue

            results.append({"skill": str(skill_md.relative_to(SKILLS_DIR)), "status": "ok"})
        except Exception as e:
            results.append({"skill": str(skill_md.relative_to(SKILLS_DIR)), "status": "broken", "reason": str(e)})
            _log("check_skills", f"{skill_md}: exception - {e}", success=False)

    return results


# ── 对外接口（供 guardian_core 调用） ─────────────────────

def quick_check() -> dict:
    """
    快速健康检查。

    返回:
        正常: {"healthy": True}
        异常: {"healthy": False, "issue": str, "severity": "warn"|"danger"}
    """
    apis = _check_api()
    unreachable = [a for a in apis if not a.get("reachable")]

    if unreachable:
        _log("quick_check", f"API unreachable: {[u['provider'] for u in unreachable]}", success=False)
        return {"healthy": False, "issue": "network_unreachable", "severity": "danger"}

    # 所有 API 可达 → 健康
    return {"healthy": True}


def auto_recover(issue: str) -> bool:
    """
    自动恢复尝试。

    参数:
        issue: quick_check() 返回的 issue 字段

    返回:
        True → 已恢复
        False → 无法恢复
    """
    if "network" not in issue:
        return False

    # 重试策略：最多 3 次，间隔递增
    for attempt in range(3):
        delay = (attempt + 1) * 3  # 3s, 6s, 9s
        _log("auto_recover", f"retry #{attempt + 1} after {delay}s", success=True)
        time.sleep(delay)

        apis = _check_api()
        if all(a.get("reachable") for a in apis):
            _log("auto_recover", "network recovered", success=True)
            return True

    _log("auto_recover", "network unreachable after 3 retries", success=False)
    return False
