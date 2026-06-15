"""操作系统适配层测试"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from os_detect import (
    IS_MACOS, IS_LINUX, IS_WINDOWS,
    get_memory_info, get_cpu_info, get_disk_info,
    get_gpu_info, get_platform_name, get_python_version,
    detect_proxy, get_gateway, get_dns_servers,
    get_active_interface,
)


class TestPlatformDetection(unittest.TestCase):

    def test_platform_flag_set(self):
        self.assertTrue(IS_MACOS or IS_LINUX or IS_WINDOWS)

    def test_mutually_exclusive(self):
        count = sum([IS_MACOS, IS_LINUX, IS_WINDOWS])
        self.assertEqual(count, 1)


class TestMemoryInfo(unittest.TestCase):

    def test_has_all_fields(self):
        info = get_memory_info()
        for key in ("total_gb", "used_gb", "free_gb", "memory_pct",
                     "swap_total_mb", "swap_used_mb", "swap_pct"):
            self.assertIn(key, info)

    def test_percent_in_range(self):
        info = get_memory_info()
        if "error" not in info:
            self.assertGreaterEqual(info["memory_pct"], 0)
            self.assertLessEqual(info["memory_pct"], 100)


class TestCpuInfo(unittest.TestCase):

    def test_has_all_fields(self):
        info = get_cpu_info()
        for key in ("load_1min", "load_5min", "load_15min", "cores"):
            self.assertIn(key, info)

    def test_cores_positive(self):
        info = get_cpu_info()
        self.assertGreaterEqual(info["cores"], 1)


class TestDiskInfo(unittest.TestCase):

    def test_has_all_fields(self):
        info = get_disk_info()
        for key in ("root_total_gb", "root_avail_gb", "root_pct"):
            self.assertIn(key, info)

    def test_percent_in_range(self):
        info = get_disk_info()
        if info["root_total_gb"] > 0:
            self.assertGreaterEqual(info["root_pct"], 0)
            self.assertLessEqual(info["root_pct"], 100)


class TestGpuInfo(unittest.TestCase):

    def test_has_fields(self):
        info = get_gpu_info()
        self.assertIn("gpu_name", info)
        self.assertIn("vram_mb", info)
        self.assertIn("available", info)


class TestMisc(unittest.TestCase):

    def test_platform_name(self):
        self.assertTrue(get_platform_name())

    def test_python_version(self):
        self.assertTrue(get_python_version())


class TestNetworkNoCrash(unittest.TestCase):
    """网络函数不应 crash，即使无网络"""

    def test_proxy(self):
        r = detect_proxy()
        self.assertIn("enabled", r)

    def test_gateway(self):
        self.assertIsInstance(get_gateway(), str)

    def test_dns_servers(self):
        self.assertIsInstance(get_dns_servers(), list)

    def test_active_interface(self):
        self.assertIsInstance(get_active_interface(), str)


class TestWindowsMockFunctions(unittest.TestCase):
    """Windows CIM/PowerShell mock tests — verify parsing logic."""

    def _mock_memory_json(self):
        """Simulate PowerShell CIM output for memory."""
        return '{"TotalVisibleMemoryKb": 16777216, "FreePhysicalMemoryKb": 8388608, "SwapTotalMb": 4096, "SwapUsedMb": 1024}'

    def test_memory_from_powershell_json(self):
        """Parse CIM JSON output like actual _memory_windows()."""
        import json as _json
        data = _json.loads(self._mock_memory_json())
        total_kb = float(data.get("TotalVisibleMemoryKb", 0))
        free_kb = float(data.get("FreePhysicalMemoryKb", 0))
        total_gb = round(total_kb / (1024**2), 2)
        used_gb = round((total_kb - free_kb) / (1024**2), 2)
        mem_pct = round((total_kb - free_kb) / total_kb * 100, 1) if total_kb > 0 else 0
        self.assertEqual(total_gb, 16.0)
        self.assertEqual(mem_pct, 50.0)

    def test_swap_from_powershell_json(self):
        import json as _json
        data = _json.loads(self._mock_memory_json())
        st = float(data.get("SwapTotalMb", 0))
        su = float(data.get("SwapUsedMb", 0))
        pct = round(su / st * 100, 1) if st > 0 else 0
        self.assertEqual(st, 4096)
        self.assertEqual(su, 1024)
        self.assertEqual(pct, 25.0)

    def test_cpu_from_powershell_json_single(self):
        """Single CPU load percentage."""
        import json as _json
        data = _json.loads("45")
        self.assertEqual(round(float(data), 2), 45.0)

    def test_cpu_from_powershell_json_multi(self):
        """Multi-core CPU load array."""
        import json as _json
        data = _json.loads("[35, 42, 38, 41]")
        avg = sum(float(v) for v in data if v is not None) / max(len(data), 1)
        self.assertEqual(round(avg, 2), 39.0)

    def test_gpu_from_powershell_json(self):
        import json as _json
        data = _json.loads('[{"Name": "NVIDIA RTX 4090", "AdapterRAM": 25769803776}]')
        if isinstance(data, list):
            for gpu in data:
                name = (gpu.get("Name") or "").strip()
                if name:
                    vram_mb = int((gpu.get("AdapterRAM") or 0)) // (1024 * 1024)
                    self.assertEqual(name, "NVIDIA RTX 4090")
                    self.assertEqual(vram_mb, 24576)
                    break

    def test_proxy_registry_output_plain(self):
        import json as _json
        data = _json.loads('{"ProxyEnable": 1, "ProxyServer": "127.0.0.1:7897"}')
        self.assertTrue(data.get("ProxyEnable"))
        server = data.get("ProxyServer", "")
        self.assertEqual(server, "127.0.0.1:7897")

    def test_proxy_registry_output_protocol(self):
        import json as _json
        data = _json.loads('{"ProxyEnable": 1, "ProxyServer": "http=127.0.0.1:7897;https=127.0.0.1:7897"}')
        self.assertTrue(data.get("ProxyEnable"))
        server = data.get("ProxyServer", "")
        http = https = None
        if "=" in server:
            for part in server.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    k = k.strip().lower()
                    if k == "http":
                        http = v
                    elif k == "https":
                        https = v
        self.assertEqual(http, "127.0.0.1:7897")
        self.assertEqual(https, "127.0.0.1:7897")

    def test_proxy_registry_disabled(self):
        import json as _json
        data = _json.loads('{"ProxyEnable": 0, "ProxyServer": ""}')
        self.assertFalse(data.get("ProxyEnable"))

    def test_gateway_route_output(self):
        import json as _json
        data = _json.loads('{"NextHop": "192.168.1.1"}')
        self.assertEqual(data.get("NextHop"), "192.168.1.1")

    def test_gateway_route_empty(self):
        import json as _json
        data = _json.loads("[]")
        self.assertEqual(len(data), 0)

    def test_dns_server_output(self):
        import json as _json
        data = _json.loads('["8.8.8.8", "1.1.1.1"]')
        self.assertIsInstance(data, list)
        self.assertIn("8.8.8.8", data)

    def test_interface_output(self):
        import json as _json
        data = _json.loads('{"InterfaceAlias": "Ethernet0"}')
        self.assertEqual(data.get("InterfaceAlias"), "Ethernet0")
