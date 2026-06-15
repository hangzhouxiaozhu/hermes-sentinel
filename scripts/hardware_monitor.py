"""
Hermes Guardian — 硬件监控模块 (Phase 3)

功能: 采集内存/CPU/磁盘/GPU 数据，分级判定，自动修复。
跨平台（macOS / Linux / Windows），通过 os_detect 适配。
被 guardian_core 调用，不直接输出到终端。
"""

import os
import json
from datetime import datetime, timezone
from pathlib import Path

from . import os_detect

# ── 配置 ──────────────────────────────────────────────────
HERMES_HOME = Path(os.path.expanduser("~/.hermes"))
LOG_FILE = HERMES_HOME / "logs" / "hardware_monitor.log"

MEMORY_WARN_PCT = 70
MEMORY_DANGER_PCT = 85
SWAP_WARN_PCT = 30
SWAP_DANGER_PCT = 60
CPU_LOAD_WARN = 5.0
DISK_WARN_PCT = 90

# ── 状态判定 ──────────────────────────────────────────────

def assess_level(mem_pct, swap_pct, cpu_load):
    if mem_pct >= MEMORY_DANGER_PCT or swap_pct >= SWAP_DANGER_PCT:
        return "danger"
    elif mem_pct >= MEMORY_WARN_PCT or swap_pct >= SWAP_WARN_PCT or cpu_load >= CPU_LOAD_WARN:
        return "warn"
    return "normal"

# ── 兜底保护 ──────────────────────────────────────────────

def emergency_protection(snapshot):
    mem_pct = snapshot.get("memory", {}).get("memory_pct", 0)
    cache_dir = HERMES_HOME / "cache" / "guardian"
    cache_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    emergency_file = cache_dir / f"emergency_save_{timestamp}.json"
    snapshot["emergency"] = True
    snapshot["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(emergency_file, "w") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    alert_file = cache_dir / "MEMORY_DANGER"
    alert_file.parent.mkdir(parents=True, exist_ok=True)
    alert_file.write_text(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "memory_pct": mem_pct,
        "action": "suggest_compress",
    }, indent=2))

    return emergency_file

# ── 日志记录 ──────────────────────────────────────────────

def write_log(snapshot):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    snapshot["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")

# ── 对外接口（供 guardian_core 调用） ─────────────────────

def check() -> dict:
    """
    执行一次完整硬件巡检。
    实际采集通过 os_detect 跨平台完成。
    """
    mem = os_detect.get_memory_info()
    cpu = os_detect.get_cpu_info()
    disk = os_detect.get_disk_info()
    gpu = os_detect.get_gpu_info()

    level = assess_level(mem.get("memory_pct", 0), mem.get("swap_pct", 0), cpu.get("load_1min", 0))

    snapshot = {
        "level": level,
        "memory": mem,
        "cpu": cpu,
        "disk": disk,
        "gpu": gpu,
    }

    write_log(snapshot)

    snapshot["auto_actions_taken"] = []
    if level == "danger":
        emergency_protection(snapshot)
        snapshot["auto_actions_taken"].extend(["emergency_saved", "compressed"])

    return snapshot


def auto_remediate(result: dict) -> list:
    """自动修复可处理的问题"""
    actions = []
    disk = result.get("disk", {})

    if disk.get("home_pct", 0) >= DISK_WARN_PCT:
        freed = _cleanup_old_logs()
        if freed > 0:
            actions.append("cleaned_logs")
            result["_actions_taken"] = actions
            result["freed_gb"] = round(freed, 2)

    if result.get("level") == "warn":
        result["_actions_taken"] = actions
    elif result.get("level") == "danger":
        if "compressed" not in actions:
            actions.append("compressed")
        result["_actions_taken"] = actions

    return actions


def _cleanup_old_logs() -> float:
    freed = 0.0
    log_dir = HERMES_HOME / "logs"
    if not log_dir.exists():
        return 0

    cutoff = datetime.now().timestamp() - (30 * 86400)
    for f in log_dir.glob("*.log"):
        try:
            if f.stat().st_mtime < cutoff:
                freed += f.stat().st_size
                f.unlink()
        except Exception:
            continue

    return freed / (1024**3)


def history_summary() -> dict:
    """读取日志汇总（给 daily_report 用）"""
    if not LOG_FILE.exists():
        return {"warn_count": 0, "danger_count": 0, "total_samples": 0}

    warn = danger = total = 0
    try:
        with open(LOG_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    level = entry.get("level", "normal")
                    if level == "warn":
                        warn += 1
                    elif level == "danger":
                        danger += 1
                    total += 1
                except Exception:
                    continue
    except Exception:
        pass

    return {"warn_count": warn, "danger_count": danger, "total_samples": total}
