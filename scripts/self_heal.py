"""
Hermes Sentinel — 故障检测与自愈

功能: Skill 完整性检查 + 日志健康。
不复制 network_monitor 的网络检测，专注在应用层。
跨平台（macOS / Linux / Windows）。

与 network_monitor 的分工：
  network_monitor — 网络连通性（TCP/DNS/公网/API）
  self_heal       — 文件完整性（Skill 元数据）、日志系统健康
"""

import json
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


def _check_skills():
    """检查已安装 skill 的 YAML frontmatter 完整性"""
    results = []
    if not SKILLS_DIR.exists() or not SKILLS_DIR.is_dir():
        return results

    for skill_md in sorted(SKILLS_DIR.rglob("SKILL.md")):
        try:
            content = skill_md.read_text()
            name = str(skill_md.relative_to(SKILLS_DIR))

            if not content.startswith("---"):
                results.append({"skill": name, "status": "broken", "reason": "no frontmatter"})
                _log("check_skills", f"{skill_md}: no frontmatter", success=False)
                continue

            parts = content.split("---", 2)
            if len(parts) < 3:
                results.append({"skill": name, "status": "broken", "reason": "malformed frontmatter"})
                _log("check_skills", f"{skill_md}: malformed frontmatter", success=False)
                continue

            if "name:" not in parts[1]:
                results.append({"skill": name, "status": "broken", "reason": "missing 'name' field"})
                _log("check_skills", f"{skill_md}: missing name", success=False)
                continue

            results.append({"skill": name, "status": "ok"})
        except Exception as e:
            results.append({"skill": str(skill_md.relative_to(SKILLS_DIR)), "status": "broken", "reason": str(e)})
            _log("check_skills", f"{skill_md}: {e}", success=False)

    return results


def _check_log_health() -> dict:
    """检查日志目录是否可写"""
    log_dir = HERMES_HOME / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        test_file = log_dir / ".health_check"
        test_file.write_text("ok")
        test_file.unlink()
        return {"healthy": True}
    except Exception as e:
        return {"healthy": False, "error": str(e)}


# ── 对外接口（供 guardian_core 调用） ─────────────────────

def quick_check() -> dict:
    """
    快速健康检查。

    检查项：
    - Skill 完整性（YAML frontmatter）
    - 日志目录可写

    返回:
        {"healthy": bool, "issues": [str], "severity": "warn"|"danger"}
    """
    issues = []

    skills = _check_skills()
    broken = [s for s in skills if s["status"] != "ok"]
    if broken:
        issues.append(f"{len(broken)} broken skills")

    log_health = _check_log_health()
    if not log_health["healthy"]:
        issues.append("log_unwritable")

    if issues:
        sev = "danger" if any("log" in i for i in issues) else "warn"
        return {"healthy": False, "issues": issues, "severity": sev}

    return {"healthy": True, "issues": [], "severity": "none"}
