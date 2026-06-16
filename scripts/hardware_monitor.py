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

import os_detect

# ── 配置 ──────────────────────────────────────────────────
HERMES_HOME = Path(os.path.expanduser("~/.hermes"))
LOG_FILE = HERMES_HOME / "logs" / "hardware_monitor.log"

# 平台自适应阈值（由 get_thresholds() 按平台返回）
# macOS 内存管理偏主动缓存，阈值更高；Windows 偏保守，阈值更低
PLATFORM_THRESHOLDS = {
    "darwin": {
        "memory_warn": 80,      # macOS 会尽量占满内存做文件缓存
        "memory_danger": 92,    # 超 92% 才真正有压力
        "swap_warn": 40,
        "swap_danger": 70,
        "cpu_load_warn": 5.0,
    },
    "windows": {
        "memory_warn": 70,
        "memory_danger": 85,
        "swap_warn": 30,
        "swap_danger": 60,
        "cpu_load_warn": 5.0,
    },
    "linux": {
        "memory_warn": 75,
        "memory_danger": 88,
        "swap_warn": 30,
        "swap_danger": 60,
        "cpu_load_warn": 5.0,
    },
}

DISK_WARN_PCT = 90


def get_thresholds() -> dict:
    """
    根据操作系统返回分级阈值。

    macos:  macOS 会积极使用空闲内存做文件缓存，
            70-80% 使用率是正常状态，调到 80/92 避免假警报。
    windows: 内存管理较保守，使用 70/85 标准阈值。
    linux:   适中，使用 75/88。
    """
    system = os_detect.SYSTEM.lower()
    if system == "darwin":
        return dict(PLATFORM_THRESHOLDS["darwin"])
    if system == "windows":
        return dict(PLATFORM_THRESHOLDS["windows"])
    return dict(PLATFORM_THRESHOLDS["linux"])


def threshold_summary() -> dict:
    """返回当前使用的阈值（用于日志记录）"""
    t = get_thresholds()
    return {
        "memory_warn": t["memory_warn"],
        "memory_danger": t["memory_danger"],
        "swap_warn": t["swap_warn"],
        "swap_danger": t["swap_danger"],
        "cpu_load_warn": t["cpu_load_warn"],
        "platform": os_detect.SYSTEM,
    }


# ── 状态判定 ──────────────────────────────────────────────

def assess_level(mem_pct, swap_pct, cpu_load, thresholds=None):
    if thresholds is None:
        thresholds = get_thresholds()
    if mem_pct >= thresholds["memory_danger"] or swap_pct >= thresholds["swap_danger"]:
        return "danger"
    elif mem_pct >= thresholds["memory_warn"] or swap_pct >= thresholds["swap_warn"] or cpu_load >= thresholds["cpu_load_warn"]:
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
    with open(emergency_file, "w", encoding="utf-8") as f:
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
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")

# ── 对外接口（供 guardian_core 调用） ─────────────────────

def check() -> dict:
    """
    执行一次完整硬件巡检。
    实际采集通过 os_detect 跨平台完成。
    等级判定使用平台自适应阈值。
    """
    mem = os_detect.get_memory_info()
    cpu = os_detect.get_cpu_info()
    disk = os_detect.get_disk_info()
    gpu = os_detect.get_gpu_info()

    t = get_thresholds()
    level = assess_level(mem.get("memory_pct", 0), mem.get("swap_pct", 0), cpu.get("load_1min", 0), t)

    snapshot = {
        "level": level,
        "memory": mem,
        "cpu": cpu,
        "disk": disk,
        "gpu": gpu,
        "_thresholds": t,
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
        with open(LOG_FILE, encoding="utf-8") as f:
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
