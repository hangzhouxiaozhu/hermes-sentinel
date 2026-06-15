"""
Hermes Guardian — 硬件监控模块 (Phase 2)

功能: 采集内存/CPU/磁盘/GPU 数据，分级判定，自动修复。
被 guardian_core 调用，不直接输出到终端。
"""

import sys
import os
import json
import subprocess
import re
from datetime import datetime, timezone
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────
HERMES_HOME = Path(os.path.expanduser("~/.hermes"))
LOG_FILE = HERMES_HOME / "logs" / "hardware_monitor.log"

# 默认阈值 (针对 16GB Mac)
MEMORY_WARN_PCT = 70
MEMORY_DANGER_PCT = 85
SWAP_WARN_PCT = 30
SWAP_DANGER_PCT = 60
CPU_LOAD_WARN = 5.0
DISK_WARN_PCT = 90

# ── 数据采集 ──────────────────────────────────────────────

def get_memory_info():
    """采集内存和 Swap 信息 (macOS)"""
    result = {"total_gb": 0, "used_gb": 0, "free_gb": 0, "memory_pct": 0,
              "pressure": "unknown", "swap_total_mb": 0, "swap_used_mb": 0, "swap_pct": 0}

    try:
        mem_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
        result["total_gb"] = round(mem_bytes / (1024**3), 2)

        try:
            pressure = subprocess.check_output(
                ["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]
            ).strip().decode()
            pressure_map = {"1": "normal", "2": "warn", "4": "critical"}
            result["pressure"] = pressure_map.get(pressure, "unknown")
        except Exception:
            pass

        page_size = 16384
        try:
            page_size = int(subprocess.check_output(["sysctl", "-n", "hw.pagesize"]).strip())
        except Exception:
            pass

        vm = subprocess.check_output(["vm_stat"]).decode()
        pages = {}
        for line in vm.split("\n"):
            if ":" in line:
                key, val = line.split(":", 1)
                try:
                    pages[key.strip()] = int(val.strip().rstrip("."))
                except ValueError:
                    pass

        free_pages = pages.get("Pages free", 0)
        active_pages = pages.get("Pages active", 0)
        inactive_pages = pages.get("Pages inactive", 0)
        wired_pages = pages.get("Pages wired down", 0)
        compressed_pages = pages.get("Pages occupied by compressor", 0)

        used_pages = active_pages + wired_pages + compressed_pages
        free_pages_total = free_pages + inactive_pages

        result["used_gb"] = round(used_pages * page_size / (1024**3), 2)
        result["free_gb"] = round(free_pages_total * page_size / (1024**3), 2)
        result["memory_pct"] = round(used_pages / (used_pages + free_pages_total) * 100, 1) if (used_pages + free_pages_total) > 0 else 0

        swap = subprocess.check_output(["sysctl", "-n", "vm.swapusage"]).decode().strip()
        total_match = re.search(r'total = (\d+)', swap)
        used_match = re.search(r'used = (\d+)', swap)
        if total_match and used_match:
            swap_total = float(total_match.group(1))
            swap_used = float(used_match.group(1))
            result["swap_total_mb"] = swap_total
            result["swap_used_mb"] = swap_used
            result["swap_pct"] = round(swap_used / swap_total * 100, 1) if swap_total > 0 else 0
    except Exception as e:
        result["error"] = str(e)

    return result


def get_cpu_info():
    """采集 CPU 负载 (macOS)"""
    result = {"load_1min": 0, "load_5min": 0, "load_15min": 0, "cores": 0}
    try:
        load = subprocess.check_output(["sysctl", "-n", "vm.loadavg"]).decode().strip()
        parts = load.replace("{", "").replace("}", "").split()
        if len(parts) >= 3:
            result["load_1min"] = round(float(parts[0]), 2)
            result["load_5min"] = round(float(parts[1]), 2)
            result["load_15min"] = round(float(parts[2]), 2)

        cores = subprocess.check_output(["sysctl", "-n", "hw.ncpu"]).strip()
        result["cores"] = int(cores)
    except Exception as e:
        result["error"] = str(e)
    return result


def get_disk_info():
    """采集磁盘剩余空间"""
    result = {"root_total_gb": 0, "root_avail_gb": 0, "root_pct": 0,
              "home_total_gb": 0, "home_avail_gb": 0, "home_pct": 0}
    try:
        for mount, key in [("/", "root"), (os.path.expanduser("~"), "home")]:
            stat = os.statvfs(mount)
            total = stat.f_frsize * stat.f_blocks
            avail = stat.f_frsize * stat.f_bavail
            total_gb = round(total / (1024**3), 2)
            avail_gb = round(avail / (1024**3), 2)
            pct = round((1 - avail / total) * 100, 1) if total > 0 else 0
            result[f"{key}_total_gb"] = total_gb
            result[f"{key}_avail_gb"] = avail_gb
            result[f"{key}_pct"] = pct
    except Exception as e:
        result["error"] = str(e)
    return result


def get_gpu_info():
    """采集 GPU 显存信息 (macOS Metal)"""
    result = {"gpu_name": "unknown", "vram_mb": 0, "metal_supported": False}
    try:
        info = subprocess.check_output(
            ["system_profiler", "SPDisplaysDataType", "-json"],
            timeout=10
        ).decode()
        displays = json.loads(info)
        if "SPDisplaysDataType" in displays:
            for gpu in displays["SPDisplaysDataType"]:
                if gpu.get("spdisplays_device_type") == "spdisplays_gpu":
                    result["gpu_name"] = gpu.get("sppci_model", "unknown")
                    vram = gpu.get("spdisplays_vram", "0")
                    result["vram_mb"] = int(vram.replace(" MB", "").replace(" GB", "000")) if vram else 0
                    result["metal_supported"] = "Metal" in gpu.get("spdisplays_ndrvs", [])
                    break
    except Exception as e:
        try:
            subprocess.check_output(["ioreg", "-l", "-w", "0"], timeout=10)
            result["gpu_name"] = "Apple Silicon (Unified Memory)"
            result["metal_supported"] = True
        except Exception:
            result["error"] = str(e)
    return result

# ── 状态判定 ──────────────────────────────────────────────

def assess_level(mem_pct, swap_pct, cpu_load):
    """根据阈值判定风险等级"""
    if mem_pct >= MEMORY_DANGER_PCT or swap_pct >= SWAP_DANGER_PCT:
        return "danger"
    elif mem_pct >= MEMORY_WARN_PCT or swap_pct >= SWAP_WARN_PCT or cpu_load >= CPU_LOAD_WARN:
        return "warn"
    return "normal"

# ── 兜底保护 ──────────────────────────────────────────────

def emergency_protection(snapshot):
    """内存超阈值时的兜底保护"""
    mem_pct = snapshot.get("memory", {}).get("memory_pct", 0)
    swap_pct = snapshot.get("memory", {}).get("swap_pct", 0)

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
        "swap_pct": swap_pct,
        "action": "suggest_compress",
    }, indent=2))

    return emergency_file

# ── 日志记录 ──────────────────────────────────────────────

def write_log(snapshot):
    """追加一行 JSONL 到日志文件"""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    snapshot["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")

# ── 对外接口（供 guardian_core 调用） ─────────────────────

def check() -> dict:
    """
    执行一次完整硬件巡检。

    返回（机器可读，不给用户看）:
    {
        "level": "normal"|"warn"|"danger",
        "memory": {...},
        "cpu": {...},
        "disk": {...},
        "gpu": {...},
        "auto_actions_taken": [...],
    }
    """
    mem = get_memory_info()
    cpu = get_cpu_info()
    disk = get_disk_info()
    gpu = get_gpu_info()

    level = assess_level(mem.get("memory_pct", 0), mem.get("swap_pct", 0), cpu.get("load_1min", 0))

    snapshot = {
        "level": level,
        "memory": mem,
        "cpu": cpu,
        "disk": disk,
        "gpu": gpu,
    }

    # 日志写文件（静默）
    write_log(snapshot)

    # 兜底保护
    snapshot["auto_actions_taken"] = []
    if level == "danger":
        emergency_protection(snapshot)
        snapshot["auto_actions_taken"].append("emergency_saved")
        snapshot["auto_actions_taken"].append("compressed")

    return snapshot


def auto_remediate(result: dict) -> list:
    """
    自动修复可处理的问题。

    参数:
        result: check() 的返回值

    返回:
        actions_taken: [str, ...]  给 narrator 参考
        例如: ["cleaned_logs"], ["compressed"]
    """
    actions = []
    disk = result.get("disk", {})

    # 磁盘预警 → 自动清理过期日志
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
    """清理 30 天前的日志，返回释放的空间 (GB)"""
    freed = 0.0
    log_dir = HERMES_HOME / "logs"
    if not log_dir.exists():
        return 0

    cutoff = datetime.now().timestamp() - (30 * 86400)
    for f in log_dir.glob("*.log"):
        try:
            mtime = f.stat().st_mtime
            if mtime < cutoff:
                freed += f.stat().st_size
                f.unlink()
        except Exception:
            continue

    return freed / (1024**3)


def history_summary() -> dict:
    """
    读取日志汇总（给 daily_report 用）。

    返回:
        {"warn_count": int, "danger_count": int, "total_samples": int}
    """
    if not LOG_FILE.exists():
        return {"warn_count": 0, "danger_count": 0, "total_samples": 0}

    warn = 0
    danger = 0
    total = 0
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
