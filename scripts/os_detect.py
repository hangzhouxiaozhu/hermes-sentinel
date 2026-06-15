"""
Hermes Guardian — 操作系统适配层

提供跨平台抽象，屏蔽 macOS / Linux / Windows 差异。
所有硬件和网络模块通过此模块获取系统信息。

设计原则:
  - 同一函数名，跨平台返回相同结构
  - 平台不支持的字段返回 None 而非报错
  - 所有异常内部消化，上层不需要 try/except
"""

import platform
import subprocess
import re
import os
from pathlib import Path

SYSTEM = platform.system()
IS_MACOS = SYSTEM == "Darwin"
IS_LINUX = SYSTEM == "Linux"
IS_WINDOWS = SYSTEM == "Windows"


def _run(cmd, timeout=5, shell=False):
    """安全运行命令，返回 stdout 或 None"""
    try:
        if shell:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=True)
        else:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
#  内存信息
# ═══════════════════════════════════════════════════════════

def get_memory_info() -> dict:
    """
    返回:
    {
        "total_gb": float, "used_gb": float, "free_gb": float,
        "memory_pct": float,
        "swap_total_mb": float, "swap_used_mb": float, "swap_pct": float,
    }
    """
    if IS_MACOS:    return _memory_darwin()
    if IS_LINUX:    return _memory_linux()
    if IS_WINDOWS:  return _memory_windows()
    return {"error": "unsupported platform"}


def _memory_darwin():
    """macOS 内存 (sysctl + vm_stat)"""
    result = {"total_gb": 0, "used_gb": 0, "free_gb": 0, "memory_pct": 0,
              "swap_total_mb": 0, "swap_used_mb": 0, "swap_pct": 0}
    try:
        mem_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
        result["total_gb"] = round(mem_bytes / (1024**3), 2)

        page_size = 16384
        try:
            page_size = int(subprocess.check_output(["sysctl", "-n", "hw.pagesize"]).strip())
        except Exception:
            pass

        vm = subprocess.check_output(["vm_stat"]).decode()
        pages = {}
        for line in vm.split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                try:
                    pages[k.strip()] = int(v.strip().rstrip("."))
                except ValueError:
                    pass

        free_pages = pages.get("Pages free", 0)
        active = pages.get("Pages active", 0)
        inactive = pages.get("Pages inactive", 0)
        wired = pages.get("Pages wired down", 0)
        compressed = pages.get("Pages occupied by compressor", 0)

        used = active + wired + compressed
        free_total = free_pages + inactive
        total_pages = used + free_total

        result["used_gb"] = round(used * page_size / (1024**3), 2)
        result["free_gb"] = round(free_total * page_size / (1024**3), 2)
        result["memory_pct"] = round(used / total_pages * 100, 1) if total_pages > 0 else 0

        # Swap
        swap = subprocess.check_output(["sysctl", "-n", "vm.swapusage"]).decode().strip()
        tm = re.search(r'total = (\d+)', swap)
        um = re.search(r'used = (\d+)', swap)
        if tm and um:
            st = float(tm.group(1))
            su = float(um.group(1))
            result["swap_total_mb"] = st
            result["swap_used_mb"] = su
            result["swap_pct"] = round(su / st * 100, 1) if st > 0 else 0
    except Exception as e:
        result["error"] = str(e)
    return result


def _memory_linux():
    """Linux 内存 (/proc/meminfo)"""
    result = {"total_gb": 0, "used_gb": 0, "free_gb": 0, "memory_pct": 0,
              "swap_total_mb": 0, "swap_used_mb": 0, "swap_pct": 0}
    try:
        info = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(":")] = int(parts[1])

        # kB → GB/MB 转换
        mem_total_kb = info.get("MemTotal", 0)
        mem_avail_kb = info.get("MemAvailable", 0)
        mem_free_kb = info.get("MemFree", 0)
        buffers_kb = info.get("Buffers", 0)
        cached_kb = info.get("Cached", 0)

        # 计算已用 = total - available (Linux 的最佳估算)
        result["total_gb"] = round(mem_total_kb / (1024**2), 2)
        if mem_avail_kb:
            result["free_gb"] = round(mem_avail_kb / (1024**2), 2)
            result["used_gb"] = round((mem_total_kb - mem_avail_kb) / (1024**2), 2)
            result["memory_pct"] = round((1 - mem_avail_kb / mem_total_kb) * 100, 1) if mem_total_kb > 0 else 0
        else:
            # fallback: free + buffers + cached
            free_total = mem_free_kb + buffers_kb + cached_kb
            result["free_gb"] = round(free_total / (1024**2), 2)
            result["used_gb"] = round((mem_total_kb - free_total) / (1024**2), 2)
            result["memory_pct"] = round((1 - free_total / mem_total_kb) * 100, 1) if mem_total_kb > 0 else 0

        # Swap
        swap_total_kb = info.get("SwapTotal", 0)
        swap_free_kb = info.get("SwapFree", 0)
        if swap_total_kb > 0:
            result["swap_total_mb"] = round(swap_total_kb / 1024, 1)
            swap_used_kb = swap_total_kb - swap_free_kb
            result["swap_used_mb"] = round(swap_used_kb / 1024, 1)
            result["swap_pct"] = round(swap_used_kb / swap_total_kb * 100, 1)
    except Exception as e:
        result["error"] = str(e)
    return result


def _memory_windows():
    """Windows 内存 (PowerShell CIM) — single combined query."""
    result = {"total_gb": 0, "used_gb": 0, "free_gb": 0, "memory_pct": 0,
              "swap_total_mb": 0, "swap_used_mb": 0, "swap_pct": 0}
    try:
        ps = (
            "&{"
            "$os=Get-CimInstance Win32_OperatingSystem;"
            "$pf=Get-CimInstance Win32_PageFileUsage;"
            "@{"
            "TotalVisibleMemoryKb=$os.TotalVisibleMemorySize;"
            "FreePhysicalMemoryKb=$os.FreePhysicalMemory;"
            "SwapTotalMb=$pf.AllocatedBaseSize;"
            "SwapUsedMb=$pf.CurrentUsage"
            "}|ConvertTo-Json"
            "}"
        )
        out = _run(["powershell", "-NoProfile", "-Command", ps], timeout=10)
        if out:
            import json as _json
            data = _json.loads(out)
            total_kb = float(data.get("TotalVisibleMemoryKb", 0))
            free_kb = float(data.get("FreePhysicalMemoryKb", 0))
            if total_kb > 0:
                used_kb = total_kb - free_kb
                result["total_gb"] = round(total_kb / (1024**2), 2)
                result["free_gb"] = round(free_kb / (1024**2), 2)
                result["used_gb"] = round(used_kb / (1024**2), 2)
                result["memory_pct"] = round(used_kb / total_kb * 100, 1)
            st = float(data.get("SwapTotalMb", 0))
            su = float(data.get("SwapUsedMb", 0))
            if st > 0:
                result["swap_total_mb"] = st
                result["swap_used_mb"] = su
                result["swap_pct"] = round(su / st * 100, 1)
    except Exception as e:
        result["error"] = str(e)
    return result


# ═══════════════════════════════════════════════════════════
#  CPU 信息
# ═══════════════════════════════════════════════════════════

def get_cpu_info() -> dict:
    """
    返回:
    {"load_1min": float, "load_5min": float, "load_15min": float, "cores": int}
    """
    if IS_MACOS:    return _cpu_darwin()
    if IS_LINUX:    return _cpu_linux()
    if IS_WINDOWS:  return _cpu_windows()
    return {}


def _cpu_darwin():
    result = {"load_1min": 0, "load_5min": 0, "load_15min": 0, "cores": 0}
    try:
        load = subprocess.check_output(["sysctl", "-n", "vm.loadavg"]).decode().strip()
        parts = load.replace("{", "").replace("}", "").split()
        if len(parts) >= 3:
            result["load_1min"] = round(float(parts[0]), 2)
            result["load_5min"] = round(float(parts[1]), 2)
            result["load_15min"] = round(float(parts[2]), 2)
    except Exception:
        pass
    # 核数独立 try/except + fallback 到 os.cpu_count()
    try:
        result["cores"] = int(subprocess.check_output(["sysctl", "-n", "hw.ncpu"]).strip())
    except Exception:
        result["cores"] = os.cpu_count() or 0
    return result


def _cpu_linux():
    result = {"load_1min": 0, "load_5min": 0, "load_15min": 0, "cores": 0}
    try:
        load = open("/proc/loadavg", encoding="utf-8").read().strip()
        parts = load.split()
        if len(parts) >= 3:
            result["load_1min"] = round(float(parts[0]), 2)
            result["load_5min"] = round(float(parts[1]), 2)
            result["load_15min"] = round(float(parts[2]), 2)
        result["cores"] = os.cpu_count() or 0
    except Exception:
        pass
    return result


def _cpu_windows():
    result = {"load_1min": 0, "load_5min": 0, "load_15min": 0, "cores": 0}
    try:
        result["cores"] = os.cpu_count() or 0
        out = _run(["powershell", "-NoProfile", "-Command",
            "&{$cpu=Get-CimInstance Win32_Processor; $cpu.LoadPercentage|ConvertTo-Json}"],
            timeout=10)
        if out:
            import json as _json
            data = _json.loads(out)
            if isinstance(data, list):
                avg = sum(float(v) for v in data if v is not None) / max(len(data), 1)
                result["load_1min"] = round(avg, 2)
            elif isinstance(data, (int, float)):
                result["load_1min"] = round(float(data), 2)
    except Exception:
        pass
    return result


# ═══════════════════════════════════════════════════════════
#  磁盘信息
# ═══════════════════════════════════════════════════════════

def get_disk_info() -> dict:
    """
    返回:
    {
        "root_total_gb": float, "root_avail_gb": float, "root_pct": float,
        "home_total_gb": float, "home_avail_gb": float, "home_pct": float,
    }
    """
    result = {"root_total_gb": 0, "root_avail_gb": 0, "root_pct": 0,
              "home_total_gb": 0, "home_avail_gb": 0, "home_pct": 0}
    try:
        for mount, key in [("/", "root"), (str(Path.home()), "home")]:
            stat = os.statvfs(mount) if not IS_WINDOWS else None
            if stat:
                total = stat.f_frsize * stat.f_blocks
                avail = stat.f_frsize * stat.f_bavail
            elif IS_WINDOWS:
                import ctypes
                free_bytes = ctypes.c_ulonglong(0)
                total_bytes = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    mount.encode() if IS_WINDOWS else mount,
                    None, ctypes.byref(total_bytes), ctypes.byref(free_bytes))
                total = total_bytes.value
                avail = free_bytes.value
            else:
                continue
            result[f"{key}_total_gb"] = round(total / (1024**3), 2)
            result[f"{key}_avail_gb"] = round(avail / (1024**3), 2)
            result[f"{key}_pct"] = round((1 - avail / total) * 100, 1) if total > 0 else 0
    except Exception:
        pass
    return result


# ═══════════════════════════════════════════════════════════
#  GPU 信息
# ═══════════════════════════════════════════════════════════

def get_gpu_info() -> dict:
    """
    返回:
    {"gpu_name": str, "vram_mb": int, "available": bool}
    """
    if IS_MACOS:    return _gpu_darwin()
    if IS_LINUX:    return _gpu_linux()
    if IS_WINDOWS:  return _gpu_windows()
    return {"gpu_name": "unknown", "vram_mb": 0, "available": False}


def _gpu_darwin():
    result = {"gpu_name": "unknown", "vram_mb": 0, "available": False}
    try:
        out = subprocess.check_output(["system_profiler", "SPDisplaysDataType", "-json"], timeout=10).decode()
        import json as _json
        displays = _json.loads(out)
        if "SPDisplaysDataType" in displays:
            for gpu in displays["SPDisplaysDataType"]:
                if gpu.get("spdisplays_device_type") == "spdisplays_gpu":
                    result["gpu_name"] = gpu.get("sppci_model", "unknown")
                    vram = gpu.get("spdisplays_vram", "0")
                    result["vram_mb"] = int(vram.replace(" MB", "").replace(" GB", "000")) if vram else 0
                    result["available"] = True
                    break
    except Exception:
        try:
            subprocess.check_output(["ioreg", "-l", "-w", "0"], timeout=10)
            result["gpu_name"] = "Apple Silicon (Unified Memory)"
            result["available"] = True
        except Exception:
            pass
    return result


def _gpu_linux():
    result = {"gpu_name": "unknown", "vram_mb": 0, "available": False}
    try:
        out = subprocess.check_output(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], timeout=10).decode().strip()
        if out:
            name = out.split(",")[0].strip()
            result["gpu_name"] = name
            result["available"] = True
            # 尝试解析显存（如 "12288 MiB"）
            mem_part = out.split(",")[1].strip() if "," in out else ""
            m = re.search(r'(\d+)', mem_part)
            if m:
                result["vram_mb"] = int(m.group(1))
    except Exception:
        # 尝试 AMD GPU (rocm-smi)
        try:
            out = subprocess.check_output(["rocm-smi", "--showproductname", "--json"], timeout=10).decode()
            import json as _json
            data = _json.loads(out)
            for gid, ginfo in data.items():
                if isinstance(ginfo, dict) and "GPU ID" in ginfo:
                    result["gpu_name"] = ginfo.get("Product Name", "AMD GPU")
                    result["available"] = True
                    break
        except Exception:
            pass
    return result


def _gpu_windows():
    result = {"gpu_name": "unknown", "vram_mb": 0, "available": False}
    try:
        out = _run(["powershell", "-NoProfile", "-Command",
            "&{Get-CimInstance Win32_VideoController|Select-Object Name,AdapterRAM|ConvertTo-Json}"],
            timeout=10)
        if out:
            import json as _json
            data = _json.loads(out)
            if isinstance(data, dict):
                data = [data]
            if isinstance(data, list):
                for gpu in data:
                    name = (gpu.get("Name") or "").strip()
                    if name:
                        result["gpu_name"] = name
                        result["available"] = True
                        ram_bytes = gpu.get("AdapterRAM") or 0
                        result["vram_mb"] = int(ram_bytes) // (1024 * 1024)
                        break
    except Exception:
        pass
    return result


# ═══════════════════════════════════════════════════════════
#  网络 — 代理检测
# ═══════════════════════════════════════════════════════════

def detect_proxy() -> dict:
    """
    检测系统代理配置。

    返回:
    {"enabled": bool, "http": str|None, "https": str|None, "socks": str|None}
    """
    if IS_MACOS:    return _proxy_darwin()
    if IS_LINUX:    return _proxy_linux()
    if IS_WINDOWS:  return _proxy_windows()
    return {"enabled": False}


def _proxy_darwin():
    proxy = {"enabled": False, "http": None, "https": None, "socks": None}
    try:
        out = subprocess.check_output(["scutil", "--proxy"], timeout=3).decode()
        http_host, http_port, https_host, https_port, socks_host, socks_port = None, None, None, None, None, None
        for line in out.split("\n"):
            ls = line.strip()
            if "HTTPProxy" in ls and ":" in ls:
                http_host = ls.split(":")[-1].strip().strip("\"")
            elif "HTTPPort" in ls:
                p = ls.split(":")[-1].strip()
                if http_host and p.isdigit(): http_port = p
            elif "HTTPSProxy" in ls:
                https_host = ls.split(":")[-1].strip().strip("\"")
            elif "HTTPSPort" in ls:
                p = ls.split(":")[-1].strip()
                if https_host and p.isdigit(): https_port = p
            elif "SOCKSProxy" in ls:
                socks_host = ls.split(":")[-1].strip().strip("\"")
            elif "SOCKSPort" in ls:
                p = ls.split(":")[-1].strip()
                if socks_host and p.isdigit(): socks_port = p
        if http_host and http_port: proxy["http"] = f"{http_host}:{http_port}"
        if https_host and https_port: proxy["https"] = f"{https_host}:{https_port}"
        if socks_host and socks_port: proxy["socks"] = f"{socks_host}:{socks_port}"
        if proxy["http"] or proxy["https"] or proxy["socks"]:
            proxy["enabled"] = True
    except Exception:
        pass
    return proxy


def _proxy_linux():
    proxy = {"enabled": False, "http": None, "https": None, "socks": None}
    # 环境变量是跨平台标准，Linux 最常用
    http = os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY")
    https = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    all_proxy = os.environ.get("all_proxy") or os.environ.get("ALL_PROXY")
    if http:
        proxy["http"] = http.replace("http://", "")
        proxy["enabled"] = True
    if https:
        proxy["https"] = https.replace("http://", "").replace("https://", "")
        proxy["enabled"] = True
    if all_proxy and not proxy["enabled"]:
        proxy["https"] = all_proxy.replace("http://", "").replace("https://", "")
        proxy["enabled"] = True
    # socks proxy via env
    socks = os.environ.get("SOCKS_PROXY") or os.environ.get("socks_proxy")
    if socks:
        proxy["socks"] = socks
        proxy["enabled"] = True
    # GSettings (GNOME)
    if not proxy["enabled"]:
        try:
            out = subprocess.check_output(["gsettings", "get", "org.gnome.system.proxy", "mode"], timeout=2).decode().strip()
            if "manual" in out:
                host = subprocess.check_output(["gsettings", "get", "org.gnome.system.proxy.http", "host"], timeout=2).decode().strip().strip("'")
                port = subprocess.check_output(["gsettings", "get", "org.gnome.system.proxy.http", "port"], timeout=2).decode().strip()
                if host and port.isdigit():
                    proxy["http"] = f"{host}:{port}"
                    proxy["enabled"] = True
        except Exception:
            pass
    return proxy


def _proxy_windows():
    proxy = {"enabled": False, "http": None, "https": None, "socks": None}

    # Priority 1: Environment variables (fastest, most portable)
    for env_key, proto in [("http_proxy", "http"), ("https_proxy", "https"),
                            ("HTTP_PROXY", "http"), ("HTTPS_PROXY", "https")]:
        val = os.environ.get(env_key)
        if val and not proxy[proto]:
            clean = val.replace("http://", "").replace("https://", "")
            proxy[proto] = clean
            proxy["enabled"] = True

    if proxy["enabled"]:
        return proxy

    # Priority 2: Registry (Internet Settings)
    try:
        out = _run(["powershell", "-NoProfile", "-Command",
            "&{$is=Get-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings'; @{ProxyEnable=$is.ProxyEnable;ProxyServer=$is.ProxyServer}|ConvertTo-Json}"],
            timeout=5)
        if out:
            import json as _json
            data = _json.loads(out)
            if data.get("ProxyEnable"):
                proxy["enabled"] = True
                server = data.get("ProxyServer", "")
                if "=" in server:
                    for part in server.split(";"):
                        if "=" in part:
                            k, v = part.split("=", 1)
                            k = k.strip().lower()
                            if k in ("http", "https"):
                                proxy[k] = v
                else:
                    proxy["http"] = proxy["https"] = server
    except Exception:
        pass

    # Priority 3: WinHTTP (corporate networks)
    if not proxy["enabled"]:
        try:
            out = _run(["netsh", "winhttp", "show", "proxy"], timeout=5)
            if out and "直接" not in out and "No proxy" not in out:
                for line in out.split("\n"):
                    if "Proxy Server" in line:
                        val = line.split(":")[-1].strip()
                        if val:
                            proxy["http"] = proxy["https"] = val
                            proxy["enabled"] = True
                            break
        except Exception:
            pass

    return proxy


# ═══════════════════════════════════════════════════════════
#  网络 — 接口与网关
# ═══════════════════════════════════════════════════════════

def get_active_interface() -> str:
    """获取默认路由的网卡名称"""
    if IS_MACOS:    return _iface_darwin()
    if IS_LINUX:    return _iface_linux()
    if IS_WINDOWS:  return _iface_windows()
    return "unknown"


def _iface_darwin():
    try:
        out = subprocess.check_output(["route", "-n", "get", "default"], timeout=3).decode()
        for line in out.split("\n"):
            if "interface:" in line:
                return line.split(":")[1].strip()
    except Exception:
        pass
    return "unknown"


def _iface_linux():
    try:
        out = subprocess.check_output(["ip", "route"], timeout=3).decode()
        for line in out.split("\n"):
            if line.startswith("default"):
                parts = line.split()
                idx = parts.index("dev") if "dev" in parts else -1
                if idx >= 0 and idx + 1 < len(parts):
                    return parts[idx + 1]
    except Exception:
        pass
    return "unknown"


def _iface_windows():
    try:
        out = _run(["powershell", "-NoProfile", "-Command",
            "&{Get-NetRoute -DestinationPrefix '0.0.0.0/0'|Select-Object -First 1 InterfaceAlias|ConvertTo-Json}"],
            timeout=5)
        if out:
            import json as _json
            data = _json.loads(out)
            if isinstance(data, dict):
                return data.get("InterfaceAlias", "unknown")
            if isinstance(data, list) and data:
                return data[0].get("InterfaceAlias", "unknown")
    except Exception:
        pass
    return "unknown"


def get_interface_type(iface: str) -> str:
    """判断接口类型: "ethernet" | "wifi" | "unknown" """
    if IS_MACOS:    return _iface_type_darwin(iface)
    if IS_LINUX:    return _iface_type_linux(iface)
    if IS_WINDOWS:  return _iface_type_windows(iface)
    return "unknown"


def _iface_type_darwin(iface):
    try:
        out = subprocess.check_output(["networksetup", "-listallhardwareports"], timeout=3).decode()
        current_type = None
        for line in out.split("\n"):
            if line.startswith("Hardware Port:"):
                pn = line.split(":")[1].strip().lower()
                current_type = "wifi" if ("wi-fi" in pn or "airport" in pn) else "ethernet"
            elif line.startswith("Device:") and iface in line:
                return current_type or "ethernet"
    except Exception:
        pass
    return "unknown"


def _iface_type_linux(iface):
    try:
        # 检查 /sys/class/net/ 下的 type 和无线子目录
        sys_path = Path(f"/sys/class/net/{iface}")
        if not sys_path.exists():
            return "unknown"
        # 有 wireless 子目录 = WiFi
        if (sys_path / "wireless").exists():
            return "wifi"
        # 检查设备类型
        dev_type = _run(["cat", f"/sys/class/net/{iface}/type"])
        if dev_type == "1":  # ARPHRD_ETHER
            return "ethernet"
    except Exception:
        pass
    return "unknown"


def _iface_type_windows(iface):
    iface_lower = iface.lower()
    if "wi-fi" in iface_lower or "wireless" in iface_lower or "wlan" in iface_lower:
        return "wifi"
    if "eth" in iface_lower or "ethernet" in iface_lower:
        return "ethernet"
    return "unknown"


def get_ip_address(iface: str) -> str:
    """获取指定网卡的 IP 地址"""
    if IS_WINDOWS:
        try:
            out = _run(["powershell", "-Command",
                f"Get-NetIPAddress -InterfaceAlias '{iface}' -AddressFamily IPv4 | Select-Object -First 1 IPAddress | ConvertTo-Json"],
                timeout=5)
            if out:
                import json as _json
                data = _json.loads(out)
                return data.get("IPAddress", "")
        except Exception:
            pass
        return ""
    # macOS/Linux: ifconfig
    try:
        out = subprocess.check_output(["ifconfig", iface], timeout=3).decode()
        for line in out.split("\n"):
            if "inet " in line:
                return line.strip().split()[1]
    except Exception:
        pass
    return ""


def get_gateway() -> str:
    """获取默认网关 IP"""
    if IS_MACOS:
        try:
            out = subprocess.check_output(["route", "-n", "get", "default"], timeout=3).decode()
            for line in out.split("\n"):
                if "gateway:" in line:
                    return line.split(":")[1].strip()
        except Exception:
            pass
        return ""
    if IS_LINUX:
        try:
            out = subprocess.check_output(["ip", "route"], timeout=3).decode()
            for line in out.split("\n"):
                if line.startswith("default"):
                    parts = line.split()
                    idx = parts.index("via") if "via" in parts else -1
                    if idx >= 0 and idx + 1 < len(parts):
                        return parts[idx + 1]
        except Exception:
            pass
        return ""
    if IS_WINDOWS:
        try:
            out = _run(["powershell", "-NoProfile", "-Command",
                "&{Get-NetRoute -DestinationPrefix '0.0.0.0/0'|Select-Object -First 1 NextHop|ConvertTo-Json}"],
                timeout=5)
            if out:
                import json as _json
                data = _json.loads(out)
                if isinstance(data, dict):
                    return data.get("NextHop", "")
                if isinstance(data, list) and data:
                    return data[0].get("NextHop", "")
        except Exception:
            pass
    return ""


def get_dns_servers() -> list:
    """获取当前 DNS 服务器列表"""
    if IS_MACOS:
        try:
            out = subprocess.check_output(["scutil", "--dns"], timeout=3).decode()
            servers = []
            for line in out.split("\n"):
                if "nameserver" in line:
                    ns = line.split(":")[-1].strip()
                    if ns and ns not in servers:
                        servers.append(ns)
            return servers
        except Exception:
            pass
    if IS_LINUX:
        servers = []
        try:
            with open("/etc/resolv.conf", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("nameserver"):
                        parts = line.split()
                        if len(parts) >= 2:
                            servers.append(parts[1])
        except Exception:
            pass
        return servers
    if IS_WINDOWS:
        try:
            out = _run(["powershell", "-NoProfile", "-Command",
                "&{Get-DnsClientServerAddress -AddressFamily IPv4|Select-Object -ExpandProperty ServerAddresses|ConvertTo-Json}"],
                timeout=5)
            if out:
                import json as _json
                data = _json.loads(out)
                return data if isinstance(data, list) else [data]
        except Exception:
            pass
    return []


def get_wifi_info() -> dict:
    """
    获取 WiFi 信号信息（仅在对应平台可用时）。

    返回:
    {"available": bool, "ssid": str|None, "rssi": int|None, "snr": int|None}
    """
    if IS_MACOS:    return _wifi_darwin()
    if IS_LINUX:    return _wifi_linux()
    if IS_WINDOWS:  return _wifi_windows()
    return {"available": False}


def _wifi_darwin():
    airport = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
    out = _run([airport, "-I"], timeout=3)
    if not out:
        return {"available": False}

    info = {"available": True, "ssid": None, "rssi": None, "snr": None}
    for line in out.split("\n"):
        ls = line.strip()
        if "SSID:" in ls and "none" not in ls.lower():
            info["ssid"] = ls.split("SSID:")[-1].strip()
        elif "agrCtlRSSI:" in ls:
            try: info["rssi"] = int(ls.split(":")[-1].strip())
            except ValueError: pass
        elif "agrCtlNoise:" in ls:
            try:
                noise = int(ls.split(":")[-1].strip())
                if info["rssi"] is not None:
                    info["snr"] = info["rssi"] - noise
            except ValueError: pass
    return info


def _wifi_linux():
    info = {"available": False}
    try:
        out = subprocess.check_output(["iwconfig"], timeout=3).decode()
        if out.strip():
            info = {"available": True, "ssid": None, "rssi": None, "snr": None}
            for line in out.split("\n"):
                m = re.search(r'ESSID:"([^"]+)"', line)
                if m: info["ssid"] = m.group(1)
                m = re.search(r'Signal level=(-?\d+)', line)
                if m: info["rssi"] = int(m.group(1))
                m = re.search(r'Noise level=(-?\d+)', line)
                if m:
                    noise = int(m.group(1))
                    if info["rssi"] is not None:
                        info["snr"] = info["rssi"] - noise
    except Exception:
        # 尝试 nmcli
        try:
            out = subprocess.check_output(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "device", "wifi"], timeout=5).decode()
            for line in out.split("\n"):
                if line.startswith("yes:"):
                    parts = line.split(":")
                    info = {"available": True, "ssid": parts[1], "rssi": None, "snr": None,
                            "signal_pct": int(parts[2]) if parts[2].isdigit() else None}
                    break
        except Exception:
            pass
    return info


def _wifi_windows():
    info = {"available": False}
    try:
        out = _run(["netsh", "wlan", "show", "interfaces"], timeout=5)
        if out:
            info = {"available": True, "ssid": None, "rssi": None, "snr": None}
            for line in out.split("\n"):
                ls = line.strip()
                m = re.search(r'SSID\s+:\s+(.+)', ls)
                if m: info["ssid"] = m.group(1).strip()
                m = re.search(r'Signal\s+:\s+(\d+)%', ls)
                if m: info["signal_pct"] = int(m.group(1))
    except Exception:
        pass
    return info


# ═══════════════════════════════════════════════════════════
#  辅助
# ═══════════════════════════════════════════════════════════

def get_platform_name() -> str:
    """返回人类可读的平台名称"""
    if IS_MACOS:
        ver = platform.mac_ver()[0]
        return f"macOS {ver}" if ver else "macOS"
    if IS_LINUX:
        try:
            out = subprocess.check_output(["lsb_release", "-ds"], timeout=2).decode().strip().strip("\"")
            return out if out else "Linux"
        except Exception:
            return "Linux"
    if IS_WINDOWS:
        return f"Windows {platform.win32_ver()[0]}"
    return platform.system() or "Unknown"


def get_python_version() -> str:
    return platform.python_version()
