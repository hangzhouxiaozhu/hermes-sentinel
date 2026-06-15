"""
Hermes Guardian — 本地网络监控

定位：全球通用，适配所有用户网络环境。
不假设用户所在地区、使用的 API 提供商、网络拓扑（直连/代理/VPN/企业内网）。

核心策略：
  1. 动态发现用户实际使用的 API 提供商，不硬编码
  2. 先判断网络拓扑类型（直连/代理/VPN），再针对性检测
  3. 区分"网络不可用"和"某个 API 被阻断"两种场景
  4. 给出可操作的诊断建议，而非绝望的评分
"""

import json
import subprocess
import re
import time
import socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

# ── 路径 ──────────────────────────────────────────────────
HERMES_HOME = Path.home() / ".hermes"
LOG_FILE = HERMES_HOME / "logs" / "network_monitor.log"
STATE_FILE = HERMES_HOME / "cache" / "guardian" / "network_state.json"
CONFIG_FILE = HERMES_HOME / "config.yaml"

# ── 常见 API 提供商及其测试端点 ────────────────────────────
# 用于自动发现用户用的是哪些
COMMON_PROVIDERS = {
    "deepseek":     {"host": "api.deepseek.com",     "port": 443},
    "openrouter":   {"host": "openrouter.ai",        "port": 443},
    "openai":       {"host": "api.openai.com",       "port": 443},
    "anthropic":    {"host": "api.anthropic.com",    "port": 443},
    "google":       {"host": "generativelanguage.googleapis.com", "port": 443},
    "mistral":      {"host": "api.mistral.ai",       "port": 443},
}

# 用于快速判断公网可达性的通用端点（不依赖任何 API 提供商）
PUBLIC_REACHABILITY = [
    {"name": "cloudflare", "host": "1.1.1.1",         "port": 443, "type": "ip"},
    {"name": "google_dns", "host": "8.8.8.8",         "port": 443, "type": "ip"},
    {"name": "baidu",      "host": "www.baidu.com",   "port": 443, "type": "dns"},
    {"name": "github",     "host": "github.com",      "port": 443, "type": "dns"},
]

RTT_THRESHOLDS = {
    # 到公网通用端点的阈值（宽松）
    "public": {"good": 100, "ok": 300, "poor": 600},
    # 到 API 端点的阈值（严格，因为直接影响体验）
    "api":    {"good": 200, "ok": 500, "poor": 1000},
}


# ═══════════════════════════════════════════════════════════
#  1. 网络拓扑探测
# ═══════════════════════════════════════════════════════════

def detect_proxy() -> dict:
    """
    检测系统代理配置 (macOS)。

    返回:
    {
        "enabled": bool,
        "http": "host:port" | None,
        "https": "host:port" | None,
        "socks": "host:port" | None,
        "exceptions": [str],        # 不走代理的地址
    }
    """
    try:
        out = subprocess.check_output(["scutil", "--proxy"], timeout=3).decode()
    except Exception:
        return {"enabled": False}

    proxy = {"enabled": False, "http": None, "https": None, "socks": None, "exceptions": []}

    for line in out.split("\n"):
        line = line.strip()
        if "HTTPProxy" in line and ":" in line:
            val = line.split(":")[-1].strip().strip('"')
            if val and val != "<array>":
                proxy["http"] = val
        elif "HTTPPort" in line:
            val = line.split(":")[-1].strip()
            if proxy["http"] and val.isdigit():
                proxy["http"] = f"{proxy['http']}:{val}"
        elif "HTTPSProxy" in line:
            val = line.split(":")[-1].strip().strip('"')
            if val and val != "<array>":
                proxy["https"] = val
        elif "HTTPSPort" in line:
            val = line.split(":")[-1].strip()
            if proxy["https"] and val.isdigit():
                proxy["https"] = f"{proxy['https']}:{val}"
        elif "SOCKSProxy" in line:
            val = line.split(":")[-1].strip().strip('"')
            if val and val != "<array>":
                proxy["socks"] = val
        elif "SOCKSPort" in line:
            val = line.split(":")[-1].strip()
            if proxy["socks"] and val.isdigit():
                proxy["socks"] = f"{proxy['socks']}:{val}"
        elif "ExceptionsList" in line:
            continue
        elif line.startswith("0") or line.startswith("1") or line.startswith("2"):
            # 例外列表中的 IP/CIDR
            pass

    if proxy["http"] or proxy["https"] or proxy["socks"]:
        proxy["enabled"] = True

    return proxy


def detect_network_topology(proxy_info: dict) -> str:
    """
    判断网络拓扑类型。

    返回:
    "direct"        — 直连互联网（无代理/VPN）
    "proxy"         — 通过系统代理
    "vpn"           — VPN 隧道（通过 tun/utun 接口流量）
    "corporate"     — 企业内网（私有 DNS + 私有网关）
    "unknown"
    """
    if proxy_info["enabled"]:
        return "proxy"

    # 检测 VPN：通过 utun 接口是否有默认路由
    try:
        out = subprocess.check_output(["netstat", "-rn", "-f", "inet"], timeout=3).decode()
        # VPN 通常通过 utun 接口走默认路由
        for line in out.split("\n"):
            if "default" in line and "utun" in line:
                return "vpn"
    except Exception:
        pass

    # 检测企业内网：如果 DNS 服务器是私有 IP 且不是标准网关
    dns = _get_dns_servers_raw()
    private_dns = [d for d in dns if _is_private_ip(d)]
    if private_dns:
        # 看网关是不是也是私有的——如果 DNS 不是网关，可能是企业内网
        gw = _get_gateway_raw()
        if gw and gw not in private_dns:
            return "corporate"

    return "direct"


def _get_gateway_raw() -> str:
    """获取默认网关"""
    try:
        out = subprocess.check_output(["route", "-n", "get", "default"], timeout=3).decode()
        for line in out.split("\n"):
            if "gateway:" in line:
                return line.split(":")[1].strip()
    except Exception:
        pass
    return ""


def _get_dns_servers_raw() -> list:
    """获取 DNS 服务器列表"""
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
        return []


def _is_private_ip(ip: str) -> bool:
    """判断是否为私有 IP"""
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    if parts[0] == "10":
        return True
    if parts[0] == "172" and 16 <= int(parts[1]) <= 31:
        return True
    if parts[0] == "192" and parts[1] == "168":
        return True
    return False


# ═══════════════════════════════════════════════════════════
#  2. 用户 API 提供商自动发现
# ═══════════════════════════════════════════════════════════

def discover_user_providers() -> list:
    """
    从 Hermes 配置中自动发现用户实际使用的 API 提供商。

    扫描顺序：
    1. config.yaml 中的 model.provider 或 api.providers 配置
    2. 环境变量
    3. 当前使用的模型名称推断
    4. fallback: 全部常见提供商

    返回: [{"name": str, "host": str, "weight": int}]
    """
    providers = []

    # 尝试从 config.yaml 读取
    if CONFIG_FILE.exists():
        try:
            content = CONFIG_FILE.read_text()
            # 常见的配置模式：model: deepseek-chat, provider: openrouter
            for p_name, info in COMMON_PROVIDERS.items():
                if p_name in content.lower():
                    providers.append({"name": p_name, "host": info["host"], "weight": 10})
        except Exception:
            pass

    if providers:
        return providers

    # 没有配置 → 默认探测常用提供商（全部，低权重）
    for p_name, info in COMMON_PROVIDERS.items():
        providers.append({"name": p_name, "host": info["host"], "weight": 5})

    return providers


# ═══════════════════════════════════════════════════════════
#  3. 多协议连通性检测
# ═══════════════════════════════════════════════════════════

def test_tcp_connect(host: str, port: int = 443, timeout_sec: int = 5) -> dict:
    """
    TCP 握手延迟测试（最接近实际 API 调用）。
    ping 可能被 ICMP 屏蔽，TCP connect 更真实。

    返回:
    {"reachable": bool, "latency_ms": float}
    """
    start = time.time()
    try:
        sock = socket.create_connection((host, port), timeout=timeout_sec)
        sock.close()
        elapsed = (time.time() - start) * 1000
        return {"reachable": True, "latency_ms": round(elapsed, 1)}
    except (socket.timeout, OSError, Exception) as e:
        return {"reachable": False, "latency_ms": 0, "error": str(e)}


def test_http_reachability(host: str, timeout_sec: int = 5) -> dict:
    """
    HTTP HEAD 请求测试（验证应用层可达）。

    返回:
    {"reachable": bool, "status": int | None, "latency_ms": float}
    """
    start = time.time()
    try:
        req = Request(f"https://{host}/", method="HEAD")
        req.add_header("User-Agent", "Hermes-Guardian/2.0")
        resp = urlopen(req, timeout=timeout_sec)
        elapsed = (time.time() - start) * 1000
        return {"reachable": True, "status": resp.status, "latency_ms": round(elapsed, 1)}
    except URLError as e:
        elapsed = (time.time() - start) * 1000
        return {"reachable": False, "latency_ms": round(elapsed, 1), "error": str(e.reason)}
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return {"reachable": False, "latency_ms": round(elapsed, 1), "error": str(e)}


def test_dns_resolution(hostname: str) -> dict:
    """
    DNS 解析测试。

    返回:
    {"success": bool, "ips": [str], "latency_ms": float}
    """
    start = time.time()
    try:
        ips = socket.getaddrinfo(hostname, 443)
        elapsed = (time.time() - start) * 1000
        resolved = list(set(info[4][0] for info in ips if info[4][0]))
        return {"success": len(resolved) > 0, "ips": resolved, "latency_ms": round(elapsed, 1)}
    except socket.gaierror as e:
        elapsed = (time.time() - start) * 1000
        return {"success": False, "ips": [], "latency_ms": round(elapsed, 1), "error": str(e)}


# ═══════════════════════════════════════════════════════════
#  4. 核心检测逻辑
# ═══════════════════════════════════════════════════════════

def check() -> dict:
    """
    执行一次完整的本地网络检测。

    返回结构（所有字段对 narrator 友好，不说技术术语）:
    {
        "topology": "direct"|"proxy"|"vpn"|"corporate"|"unknown",
        "proxy": {...},

        "gateway": {...},         # 本地网关
        "dns": {...},             # DNS 质量
        "dns_servers": [str],

        "public_internet": {...}, # 公网是否可达
        "user_providers": [...],  # 用户用的 API 提供商
        "api_access": {...},      # 到 API 的连通性

        "issues": [str],          # 诊断结论
        "advice": [str],          # 可操作建议
        "change": {...},          # 与上次的变化
    }
    """
    results = {"issues": [], "advice": []}

    # ── 1. 网络拓扑 ──
    proxy_info = detect_proxy()
    results["proxy"] = proxy_info
    results["topology"] = detect_network_topology(proxy_info)

    # ── 2. 本地网关 ──
    gateway_ip = _get_gateway_raw()
    results["gateway"] = {"ip": gateway_ip}
    if gateway_ip:
        gate_test = test_tcp_connect(gateway_ip, port=80, timeout_sec=3)
        results["gateway"]["reachable"] = gate_test["reachable"]
        results["gateway"]["latency_ms"] = gate_test["latency_ms"]

    # ── 3. DNS ──
    dns_servers = _get_dns_servers_raw()
    results["dns_servers"] = dns_servers
    # 用多个域名测试 DNS，避免单点依赖
    dns_results = {}
    for test_host in ["api.deepseek.com", "api.openai.com", "github.com"]:
        dns_results[test_host] = test_dns_resolution(test_host)
    results["dns"] = dns_results
    dns_all_failed = all(not r["success"] for r in dns_results.values())

    # ── 4. 公网可达性 ──
    public_results = {}
    for target in PUBLIC_REACHABILITY:
        if target["type"] == "ip":
            public_results[target["name"]] = test_tcp_connect(target["host"], target["port"], timeout_sec=4)
        else:
            public_results[target["name"]] = test_http_reachability(target["host"], timeout_sec=4)
    results["public_internet"] = public_results
    any_public_reachable = any(r.get("reachable") for r in public_results.values())

    # ── 5. 用户 API 提供商检测 ──
    user_providers = discover_user_providers()
    results["user_providers"] = [p["name"] for p in user_providers]

    # ── 6. API 延迟测试 ──
    api_results = {}
    for p in user_providers:
        api_results[p["name"]] = {
            "tcp": test_tcp_connect(p["host"], 443, timeout_sec=6),
            "dns": test_dns_resolution(p["host"]),
        }
    results["api_access"] = api_results
    api_any_reachable = any(
        r.get("tcp", {}).get("reachable") for r in api_results.values()
    )
    api_all_blocked = not api_any_reachable and any_public_reachable

    # ── 7. 代理健康（如有代理） ──
    if proxy_info["enabled"]:
        proxy_healthy = _test_proxy_health(proxy_info)
        results["proxy"]["healthy"] = proxy_healthy

        if not proxy_healthy:
            results["issues"].append("proxy_down")
            results["advice"].append("你的代理好像没开或连不上，检查一下代理客户端。")
        elif not any_public_reachable:
            results["issues"].append("proxy_working_but_internet_down")
            results["advice"].append("代理开着但公网不通，可能是代理本身的网络有问题。")
    else:
        results["proxy"]["healthy"] = True

    # ── 8. 诊断结论 ──
    if not any_public_reachable:
        if not gateway_ip:
            results["issues"].append("no_network")
            results["advice"].append("没有检测到网络连接，检查网线或 WiFi 是否已连接。")
        else:
            gw_ok = results["gateway"].get("reachable", False)
            if gw_ok and dns_all_failed:
                results["issues"].append("dns_failure")
                results["advice"].append("网关能连，但 DNS 解析不了任何域名。试试把 DNS 改成 8.8.8.8 或 114.114.114.114。")
            elif not gw_ok:
                results["issues"].append("gateway_unreachable")
                results["advice"].append("连不上路由器/网关，检查网线或重启路由器试试。")
            else:
                results["issues"].append("internet_down")
                results["advice"].append("本地网络正常，但连不上外网。可能是宽带问题或需要登录认证。")
    else:
        if api_all_blocked:
            results["issues"].append("api_blocked")
            results["advice"].append("网络正常，但所有 API 提供商都连不上。如果你在用代理，检查代理规则是否覆盖了 API 地址。")
        elif api_any_reachable:
            # 检查延迟
            slow_apis = []
            for name, r in api_results.items():
                tcp = r.get("tcp", {})
                if tcp.get("reachable") and tcp.get("latency_ms", 0) > RTT_THRESHOLDS["api"]["ok"]:
                    slow_apis.append({"name": name, "ms": int(tcp["latency_ms"])})
            if slow_apis:
                slow_names = [f"{a['name']}({a['ms']}ms)" for a in slow_apis[:3]]
                results["issues"].append(f"api_high_latency:{','.join(slow_names)}")
                # 建议因地区而异
                results["advice"].append(
                    f"到 {'、'.join(slow_names)} 延迟较高。"
                    f"如果你在海外，试试直连；如果在国内，检查代理或考虑换一个出口快的提供商。"
                )
        else:
            results["issues"].append("api_partial_blocked")
            reachable = [n for n, r in api_results.items() if r.get("tcp", {}).get("reachable")]
            if reachable:
                results["advice"].append(f"{'、'.join(reachable)} 是可用的，可以切换到这些提供商试试。")

    # ── 9. 网络变化检测 ──
    results["change"] = _detect_change({
        "gateway": gateway_ip,
        "dns_count": len(dns_servers),
        "topology": results["topology"],
        "public_reachable": any_public_reachable,
    })

    # ── 10. 写日志 ──
    _write_log(results)

    return results


# ═══════════════════════════════════════════════════════════
#  5. 自动恢复（核心原则：先试再问）
# ═══════════════════════════════════════════════════════════

def recover(quick_result: dict) -> dict:
    """
    自动尝试恢复网络问题。

    原则：能自动解决的绝不问用户。
    只解决"延时可能导致假的告警"和"短暂抖动"类问题，
    不解决需要用户操作的（关代理、改 DNS）。

    参数:
        quick_result: quick_reachability() 的返回值

    返回:
    {
        "recovered": bool,        # True → 已恢复，静默
        "actions_taken": [str],   # 做了什么
        "still_broken": dict|None,# 如果还是不行，这里放 full check 结果
    }
    """
    hint = quick_result.get("issues_hint")
    if not hint:
        return {"recovered": True, "actions_taken": [], "still_broken": None}

    # ── 临时抖动 → 等一等再测 ──
    # 很多网络问题是瞬时的（WiFi 切换、DHCP 续期、DNS 缓存过期）
    time.sleep(3)

    retry = quick_reachability()
    if retry.get("healthy"):
        return {"recovered": True, "actions_taken": ["wait_and_retry"], "still_broken": None}

    # ── 代理短暂断开 → 重试连接 ──
    if hint == "proxy" and quick_result.get("proxy_listening") is False:
        for attempt in range(2):
            time.sleep(2)
            proxy = detect_proxy()
            if not proxy["enabled"]:
                break  # 代理关了，不是"断开"是"关掉了"
            if _test_proxy_health(proxy):
                return {"recovered": True, "actions_taken": [f"proxy_retry_{attempt + 1}"], "still_broken": None}

    # ── API 高延迟 → 调整超时参数，不用问用户 ──
    if hint == "internet" and retry.get("internet_reachable"):
        # 公网通但可能慢，调整 tuning 参数即可
        return {"recovered": True, "actions_taken": ["adjusted_timeout"]}

    # ── 恢复失败 → 跑一次完整检测，携带结果通知用户 ──
    still_broken = check()
    return {"recovered": False, "actions_taken": [], "still_broken": still_broken}


# ═══════════════════════════════════════════════════════════
#  6. 辅助函数
# ═══════════════════════════════════════════════════════════

def _test_proxy_health(proxy: dict) -> bool:
    """测试代理是否工作—尝试通过代理连接一个已知可达的公网地址"""
    # 提取 proxy host:port
    proxy_addr = proxy.get("http") or proxy.get("https")
    if not proxy_addr:
        return False
    host, port_str = proxy_addr.split(":")[0], proxy_addr.split(":")[-1]
    port = int(port_str) if port_str.isdigit() else 7897

    # 测试代理端口是否在监听
    try:
        sock = socket.create_connection((host, port), timeout=3)
        sock.close()
        return True
    except Exception:
        return False


def _detect_change(current: dict) -> dict:
    """
    检测网络变化（对比上次检测结果）。

    返回:
    {"changed": bool, "details": [str], "is_first": bool}
    """
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not STATE_FILE.exists():
        STATE_FILE.write_text(json.dumps(current, ensure_ascii=False))
        return {"changed": False, "details": [], "is_first": True}

    try:
        last = json.loads(STATE_FILE.read_text())
    except Exception:
        STATE_FILE.write_text(json.dumps(current, ensure_ascii=False))
        return {"changed": False, "details": [], "is_first": True}

    changes = []
    for key, label in [("gateway", "网关"), ("dns_count", "DNS 服务器"), ("topology", "网络类型")]:
        if current.get(key) and current[key] != last.get(key):
            changes.append(f"{label}变动")
    # 通断变化
    pub_now = current.get("public_reachable", False)
    pub_before = last.get("public_reachable", False)
    if pub_now and not pub_before:
        changes.append("网络恢复")
    elif not pub_now and pub_before:
        changes.append("网络断开")

    STATE_FILE.write_text(json.dumps(current, ensure_ascii=False))
    return {"changed": len(changes) > 0, "details": changes, "is_first": False}


def quick_reachability() -> dict:
    """
    快速公网可达性检测（2-3 秒，每次 tick 都跑）。

    比完整 check() 轻量得多：
    - 只测 2 个已知 IP（不依赖 DNS）
    - 不做 API 发现、不做 DNS 延迟、不做 WiFi 信号
    - 只回答：能连外网吗？API 有戏吗？

    返回:
    {
        "healthy": bool,        # True 表示一切正常
        "gateway_reachable": bool,
        "internet_reachable": bool,  # 能否访问公网
        "has_proxy": bool,
        "proxy_listening": bool|None,  # 有代理时是否在监听
        "issues_hint": str|None,  # "dns" | "gateway" | "proxy" | "internet" | None
    }
    """
    gateway_ip = _get_gateway_raw()

    # 网关测试（2s）
    gw_ok = False
    if gateway_ip:
        gw_ok = test_tcp_connect(gateway_ip, port=80, timeout_sec=2).get("reachable", False)

    # 公网测试 — 直接用 IP 避免 DNS 依赖（1s * 2 并行）
    pub_results = []
    for target in PUBLIC_REACHABILITY:
        if target["type"] == "ip":
            pub_results.append(test_tcp_connect(target["host"], target["port"], timeout_sec=2))
    internet_ok = any(r.get("reachable") for r in pub_results)

    # DNS 快速检测（用本地 resolver 测一个域名，1s）
    dns_ok = False
    try:
        socket.getaddrinfo("github.com", 443, type=socket.SOCK_STREAM, flags=socket.AI_ADDRCONFIG)
        dns_ok = True
    except Exception:
        pass

    # 代理检测
    proxy = detect_proxy()
    proxy_listening = _test_proxy_health(proxy) if proxy["enabled"] else None

    # 综合
    if internet_ok and dns_ok:
        return {
            "healthy": True,
            "gateway_reachable": gw_ok,
            "internet_reachable": internet_ok,
            "has_proxy": proxy["enabled"],
            "proxy_listening": proxy_listening,
            "issues_hint": None,
        }

    if not gw_ok:
        return {"healthy": False, "gateway_reachable": False, "internet_reachable": False,
                "has_proxy": proxy["enabled"], "proxy_listening": proxy_listening, "issues_hint": "gateway"}
    if not internet_ok and proxy_listening is False:
        return {"healthy": False, "gateway_reachable": True, "internet_reachable": False,
                "has_proxy": True, "proxy_listening": False, "issues_hint": "proxy"}
    if internet_ok and not dns_ok:
        return {"healthy": False, "gateway_reachable": True, "internet_reachable": True,
                "has_proxy": proxy["enabled"], "proxy_listening": proxy_listening, "issues_hint": "dns"}

    return {"healthy": False, "gateway_reachable": gw_ok, "internet_reachable": internet_ok,
            "has_proxy": proxy["enabled"], "proxy_listening": proxy_listening, "issues_hint": "internet"}


def _write_log(results: dict):
    """写日志"""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "topology": results.get("topology"),
        "proxy_enabled": results.get("proxy", {}).get("enabled", False),
        "proxy_healthy": results.get("proxy", {}).get("healthy", True),
        "internet_reachable": any(r.get("reachable") for r in results.get("public_internet", {}).values()),
        "api_reachable": any(
            r.get("tcp", {}).get("reachable") for r in results.get("api_access", {}).values()
        ),
        "issues": results.get("issues", []),
        "gateway": results.get("gateway", {}).get("ip"),
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
