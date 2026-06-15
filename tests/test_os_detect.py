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
