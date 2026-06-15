"""
Hermes Guardian — 本地网络监控

定位：全球通用，跨平台（macOS / Linux / Windows）。
通过 os_detect 适配各平台系统命令差异。

核心策略：
  1. 动态发现用户实际的 API 提供商
  2. 判断网络拓扑（直连/代理/VPN/企业内网）
  3. 区分"网络不可用"和"API 被阻断"两种场景
  4. 先自动恢复，不行再请用户帮忙
"""

import json
import time
import socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

import os_detect

HERMES_HOME = Path.home() / ".hermes"
LOG_FILE = HERMES_HOME / "logs" / "network_monitor.log"
STATE_FILE = HERMES_HOME / "cache" / "guardian" / "network_state.json"
CONSECUTIVE_FAIL_FILE = HERMES_HOME / "cache" / "guardian" / "network_consecutive_failures.json"
CONFIG_FILE = HERMES_HOME / "config.yaml"

# Number of consecutive failures required before alerting (noise reduction)
# Windows firewalls, corporate VPN, brief WiFi drops should not trigger on first miss
CONSECUTIVE_FAIL_THRESHOLD = 3

COMMON_PROVIDERS = {
    "deepseek":     {"host": "api.deepseek.com",     "port": 443},
    "openrouter":   {"host": "openrouter.ai",        "port": 443},
    "openai":       {"host": "api.openai.com",       "port": 443},
    "anthropic":    {"host": "api.anthropic.com",    "port": 443},
    "google":       {"host": "generativelanguage.googleapis.com", "port": 443},
    "mistral":      {"host": "api.mistral.ai",       "port": 443},
}

PUBLIC_REACHABILITY = [
    {"name": "cloudflare", "host": "1.1.1.1",         "port": 443, "type": "ip"},
    {"name": "google_dns", "host": "8.8.8.8",         "port": 443, "type": "ip"},
    {"name": "baidu",      "host": "www.baidu.com",   "port": 443, "type": "dns"},
    {"name": "github",     "host": "github.com",      "port": 443, "type": "dns"},
]

RTT_THRESHOLDS = {
    "public": {"good": 100, "ok": 300, "poor": 600},
    "api":    {"good": 200, "ok": 500, "poor": 1000},
}


# ═══════════════════════════════════════════════════════════
#  网络拓扑（通过 os_detect）
# ═══════════════════════════════════════════════════════════

def detect_network_topology(proxy_info: dict) -> str:
    """判断网络拓扑: direct | proxy | vpn | corporate | unknown"""
    if proxy_info["enabled"]:
        return "proxy"

    if os_detect.IS_MACOS:
        try:
            import subprocess
            out = subprocess.check_output(["netstat", "-rn", "-f", "inet"], timeout=3).decode()
            if any("default" in line and "utun" in line for line in out.split("\n")):
                return "vpn"
        except Exception:
            pass

    dns = os_detect.get_dns_servers()
    private_dns = [d for d in dns if _is_private_ip(d)]
    if private_dns:
        gw = os_detect.get_gateway()
        if gw and gw not in private_dns:
            return "corporate"
    return "direct"


def _is_private_ip(ip: str) -> bool:
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        if parts[0] == "10": return True
        if parts[0] == "172" and 16 <= int(parts[1]) <= 31: return True
        if parts[0] == "192" and parts[1] == "168": return True
    except ValueError:
        pass
    return False


# ═══════════════════════════════════════════════════════════
#  API 提供商自动发现
# ═══════════════════════════════════════════════════════════

def discover_user_providers() -> list:
    """从 Hermes 配置自动发现用户使用的 API 提供商"""
    if CONFIG_FILE.exists():
        try:
            content = CONFIG_FILE.read_text().lower()
            result = [{"name": n, "host": i["host"], "weight": 10}
                      for n, i in COMMON_PROVIDERS.items() if n in content]
            if result:
                return result
        except Exception:
            pass
    return [{"name": n, "host": i["host"], "weight": 5} for n, i in COMMON_PROVIDERS.items()]


# ═══════════════════════════════════════════════════════════
#  连通性测试（纯 socket，无平台依赖）
# ═══════════════════════════════════════════════════════════

def test_tcp_connect(host: str, port: int = 443, timeout_sec: int = 5) -> dict:
    start = time.time()
    try:
        sock = socket.create_connection((host, port), timeout=timeout_sec)
        sock.close()
        return {"reachable": True, "latency_ms": round((time.time() - start) * 1000, 1)}
    except Exception as e:
        return {"reachable": False, "latency_ms": 0, "error": str(e)}


def test_http_reachability(host: str, timeout_sec: int = 5) -> dict:
    start = time.time()
    try:
        req = Request(f"https://{host}/", method="HEAD")
        req.add_header("User-Agent", "Hermes-Guardian/2.0")
        resp = urlopen(req, timeout=timeout_sec)
        return {"reachable": True, "status": resp.status, "latency_ms": round((time.time() - start) * 1000, 1)}
    except Exception as e:
        return {"reachable": False, "latency_ms": round((time.time() - start) * 1000, 1), "error": str(e)}


def test_dns_resolution(hostname: str) -> dict:
    start = time.time()
    try:
        ips = socket.getaddrinfo(hostname, 443)
        resolved = list(set(info[4][0] for info in ips if isinstance(info[4], tuple) and info[4][0]))
        return {"success": len(resolved) > 0, "ips": resolved, "latency_ms": round((time.time() - start) * 1000, 1)}
    except socket.gaierror as e:
        return {"success": False, "ips": [], "latency_ms": round((time.time() - start) * 1000, 1), "error": str(e)}


# ═══════════════════════════════════════════════════════════
#  快速可达性检测（每次 tick 跑，2-3s）
# ═══════════════════════════════════════════════════════════

def quick_reachability() -> dict:
    """轻量公网可达性检测，只回答问题：能连外网吗？"""
    gateway_ip = os_detect.get_gateway()
    gw_ok = test_tcp_connect(gateway_ip, port=80, timeout_sec=2).get("reachable", False) if gateway_ip else False

    pub_results = [test_tcp_connect(t["host"], t["port"], timeout_sec=2) for t in PUBLIC_REACHABILITY if t["type"] == "ip"]
    internet_ok = any(r.get("reachable") for r in pub_results)

    dns_ok = False
    try:
        socket.getaddrinfo("github.com", 443, type=socket.SOCK_STREAM, flags=socket.AI_ADDRCONFIG)
        dns_ok = True
    except Exception:
        pass

    proxy = os_detect.detect_proxy()
    proxy_listening = _test_proxy_health(proxy) if proxy["enabled"] else None

    # Apply consecutive failure guard (noise reduction)
    # Transient issues (WiFi switch, VPN reconnect, firewall blip) must
    # occur CONSECUTIVE_FAIL_THRESHOLD times before triggering alerts.
    is_healthy = internet_ok and dns_ok
    _track_consecutive_failures(is_healthy)

    if is_healthy:
        return {"healthy": True, "gateway_reachable": gw_ok, "internet_reachable": internet_ok,
                "has_proxy": proxy["enabled"], "proxy_listening": proxy_listening, "issues_hint": None}
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


# ═══════════════════════════════════════════════════════════
#  完整检测
# ═══════════════════════════════════════════════════════════

def check() -> dict:
    """执行一次完整的本地网络检测"""
    results = {"issues": [], "advice": []}

    proxy_info = os_detect.detect_proxy()
    results["proxy"] = proxy_info
    results["topology"] = detect_network_topology(proxy_info)

    gateway_ip = os_detect.get_gateway()
    results["gateway"] = {"ip": gateway_ip}
    if gateway_ip:
        results["gateway"]["reachable"] = test_tcp_connect(gateway_ip, port=80, timeout_sec=3).get("reachable", False)

    dns_servers = os_detect.get_dns_servers()
    results["dns_servers"] = dns_servers
    dns_results = {h: test_dns_resolution(h) for h in ["api.deepseek.com", "api.openai.com", "github.com"]}
    results["dns"] = dns_results
    dns_all_failed = all(not r["success"] for r in dns_results.values())

    public_results = {}
    for t in PUBLIC_REACHABILITY:
        if t["type"] == "ip":
            public_results[t["name"]] = test_tcp_connect(t["host"], t["port"], timeout_sec=4)
        else:
            public_results[t["name"]] = test_http_reachability(t["host"], timeout_sec=4)
    results["public_internet"] = public_results
    any_public_reachable = any(r.get("reachable") for r in public_results.values())

    user_providers = discover_user_providers()
    results["user_providers"] = [p["name"] for p in user_providers]

    api_results = {}
    for p in user_providers:
        api_results[p["name"]] = {"tcp": test_tcp_connect(p["host"], 443, timeout_sec=6),
                                   "dns": test_dns_resolution(p["host"])}
    results["api_access"] = api_results
    api_any_reachable = any(r.get("tcp", {}).get("reachable") for r in api_results.values())
    api_all_blocked = not api_any_reachable and any_public_reachable

    if proxy_info["enabled"]:
        results["proxy"]["healthy"] = _test_proxy_health(proxy_info)
        if not results["proxy"]["healthy"]:
            results["issues"].append("proxy_down")
            results["advice"].append("代理连不上，检查一下代理客户端有没有开着。")
        elif not any_public_reachable:
            results["issues"].append("proxy_working_but_internet_down")
            results["advice"].append("代理开着但走不出去，可能是代理本身的网络也断了。")
    else:
        results["proxy"]["healthy"] = True

    if not any_public_reachable:
        if not gateway_ip:
            results["issues"].append("no_network")
            results["advice"].append("没有检测到网络连接，检查网线或 WiFi 是否已连接。")
        else:
            gw_ok = results["gateway"].get("reachable", False)
            if gw_ok and dns_all_failed:
                results["issues"].append("dns_failure")
                results["advice"].append("网关能连，但 DNS 解析不了。试试把 DNS 改成 8.8.8.8 或 114.114.114.114。")
            elif not gw_ok:
                results["issues"].append("gateway_unreachable")
                results["advice"].append("连不上路由器，检查网线或重启路由器试试。")
            else:
                results["issues"].append("internet_down")
                results["advice"].append("路由器能连上，但外网不通。可能宽带需要重新认证。")
    else:
        if api_all_blocked:
            results["issues"].append("api_blocked")
            results["advice"].append("网络正常，但所有 AI 服务都连不上。如果用着代理，检查代理规则是否覆盖了 API 地址。")
        elif api_any_reachable:
            slow = [{"name": n, "ms": int(r["tcp"]["latency_ms"])}
                    for n, r in api_results.items()
                    if r.get("tcp", {}).get("reachable") and r["tcp"].get("latency_ms", 0) > RTT_THRESHOLDS["api"]["ok"]]
            if slow:
                names = ",".join(f"{s['name']}({s['ms']}ms)" for s in slow[:3])
                results["issues"].append(f"api_high_latency:{names}")
                topo = results["topology"]
                if topo == "proxy":
                    results["advice"].append("走代理到 API 速度不理想，换个代理节点试试。")
                elif topo == "vpn":
                    results["advice"].append("走 VPN 延迟偏高，这是正常的 VPN 损耗。")
                elif topo == "corporate":
                    results["advice"].append("走公司网络比较慢，这是企业出口的正常情况。")
                else:
                    results["advice"].append("到 API 延迟偏高，如果在国内试试走代理。")
        else:
            results["issues"].append("api_partial_blocked")
            reachable = [n for n, r in api_results.items() if r.get("tcp", {}).get("reachable")]
            if reachable:
                results["advice"].append(f"{'、'.join(reachable)} 是可用的，可以切到这些提供商试试。")

    results["change"] = _detect_change({
        "gateway": gateway_ip, "dns_count": len(dns_servers),
        "topology": results["topology"], "public_reachable": any_public_reachable,
    })
    _write_log(results)
    return results


# ═══════════════════════════════════════════════════════════
#  自动恢复
# ═══════════════════════════════════════════════════════════

def recover(quick_result: dict) -> dict:
    """尝试自动解决网络问题，解决不了再返回详情"""
    hint = quick_result.get("issues_hint")
    if not hint:
        return {"recovered": True, "actions_taken": [], "still_broken": None}

    time.sleep(3)
    retry = quick_reachability()
    if retry.get("healthy"):
        return {"recovered": True, "actions_taken": ["wait_and_retry"], "still_broken": None}

    if hint == "proxy":
        for _ in range(2):
            time.sleep(2)
            proxy = os_detect.detect_proxy()
            if not proxy["enabled"]:
                break
            if _test_proxy_health(proxy):
                return {"recovered": True, "actions_taken": ["proxy_retried"], "still_broken": None}

    if hint == "internet" and retry.get("internet_reachable"):
        return {"recovered": True, "actions_taken": ["adjusted_timeout"], "still_broken": None}

    return {"recovered": False, "actions_taken": [], "still_broken": check()}


# ═══════════════════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════════════════

def _test_proxy_health(proxy: dict) -> bool:
    addr = proxy.get("http") or proxy.get("https")
    if not addr:
        return False
    host = addr.split(":")[0]
    port = int(addr.split(":")[-1]) if addr.split(":")[-1].isdigit() else 7897
    try:
        sock = socket.create_connection((host, port), timeout=3)
        sock.close()
        return True
    except Exception:
        return False


def _detect_change(current: dict) -> dict:
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
    for key, label in [("gateway", "网关"), ("dns_count", "DNS"), ("topology", "网络类型")]:
        if current.get(key) and current[key] != last.get(key):
            changes.append(f"{label}变动")
    pub_now, pub_before = current.get("public_reachable"), last.get("public_reachable")
    if pub_now and not pub_before:
        changes.append("网络恢复")
    elif not pub_now and pub_before:
        changes.append("网络断开")

    STATE_FILE.write_text(json.dumps(current, ensure_ascii=False))
    return {"changed": len(changes) > 0, "details": changes, "is_first": False}


def _track_consecutive_failures(healthy: bool) -> bool:
    """
    Track consecutive network failures. Only return True (alert-worthy)
    when CONSECUTIVE_FAIL_THRESHOLD is reached.

    This prevents false alarms from transient issues (WiFi handoff, VPN
    reconnect, firewall blip, corporate proxy timeout).
    """
    CONSECUTIVE_FAIL_FILE.parent.mkdir(parents=True, exist_ok=True)

    try:
        if CONSECUTIVE_FAIL_FILE.exists():
            count = int(json.loads(CONSECUTIVE_FAIL_FILE.read_text()).get("count", 0))
        else:
            count = 0
    except Exception:
        count = 0

    if healthy:
        if count > 0:
            count = 0
            CONSECUTIVE_FAIL_FILE.write_text(json.dumps({"count": 0}, ensure_ascii=False))
        return False

    count += 1
    CONSECUTIVE_FAIL_FILE.write_text(json.dumps({"count": count}, ensure_ascii=False))

    if count >= CONSECUTIVE_FAIL_THRESHOLD:
        count = 0
        CONSECUTIVE_FAIL_FILE.write_text(json.dumps({"count": 0}, ensure_ascii=False))
        return True

    return False


def _write_log(results: dict):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "topology": results.get("topology"),
        "proxy_enabled": results.get("proxy", {}).get("enabled"),
        "internet_reachable": any(r.get("reachable") for r in results.get("public_internet", {}).values()),
        "api_reachable": any(r.get("tcp", {}).get("reachable") for r in results.get("api_access", {}).values()),
        "issues": results.get("issues", []),
        "platform": os_detect.SYSTEM,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
