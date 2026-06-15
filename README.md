# Hermes Sentinel · 无感守护者

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-lightgrey)]()

**Hermes 的后台守护 skill** — 硬件监控、网络质量检测、成本记账、故障自愈、安全审查、隐私隔离。全部自动运行，用户无感。

## 设计原则

> **先自动解决，解决不了再请用户帮忙。**

Sentinel 所有模块遵循同样的流程：
1. 问题发生时，先尝试自动修复
2. 修复不了，等几秒重试（可能是短暂抖动）
3. 还不行，评估是否需要用户操作
4. 确实需要用户配合 → 说清楚"我试了什么、你方便做什么"

目标：用户 95% 的情况下不知道 Sentinel 的存在。

> 与 Hermes 边界清晰：本 skill 只做 Hermes 本身不具备的能力。

---

## 架构

```
Hermes 主循环
    │
    ├── 定时 (每 10 分钟) → guardian_core.guardian_tick()
    │   ├── hardware_monitor.check()      → 自动修复 / 通知
    │   ├── network_monitor.quick_check() → 轻量快速检测
    │   │   └── (异常时) full check       → 诊断根因 + 建议
    │   └── self_heal.quick_check()       → 自动重试 / 通知
    │
    ├── 联网前 hook → guardian_core.guardian_before_outbound()
    │   └── privacy_guard.filter_outgoing_data()
    │
    ├── API 调用后 hook → guardian_core.guardian_on_api_call()
    │   └── cost_tracker.record()
    │
    └── 安装 skill 前 hook → guardian_core.guardian_on_skill_install()
        ├── skill_auditor.scan()
        └── config_manager.auto_merge()
```

**所有模块不直接输出到终端**，通过 flag 文件与 narrator 层和 Hermes 主循环通讯。

---

## 文件说明

| 文件 | 用途 |
|------|------|
| `scripts/guardian_core.py` | 中央协调器，暴露 4 个 hook/tick 入口 |
| `scripts/narrator.py` | 机器数据 → 人话 + 通知节流 |
| `scripts/hardware_monitor.py` | 硬件数据采集 + 自动修复 |
| `scripts/network_monitor.py` | 网络质量检测（代理/VPN/DNS/网关/公网） |
| `scripts/cost_tracker.py` | Token 费用记账 |
| `scripts/self_heal.py` | API 连通性检测 + 自动重试 |
| `scripts/skill_auditor.py` | Skill 安全审查（静默） |
| `scripts/config_manager.py` | 配置冲突检测（静默合并） |
| `scripts/privacy_guard.py` | 隐私字段脱敏 |
| `scripts/daily_report.py` | 日报生成器（日志用） |
| `cron/hardware-check.sh` | Cron 定时巡检入口 |
| `cron/daily-backup.sh` | Cron 每日日报入口 |
| `references/` | 内部参考文档 |
| `templates/monitor-config.yaml` | 硬件阈值配置模板 |

---

## Hook 接口（供 Hermes 主循环调用）

```python
from guardian_core import (
    guardian_tick,              # 每 10 分钟
    guardian_before_outbound,   # 联网前
    guardian_on_api_call,       # API 调用后
    guardian_on_skill_install,  # 安装 skill 前
    get_notification,           # 检查是否有通知待推送
    guardian_daily_report,      # 生成一句话日报
)
```

---

## 开发

```bash
# 文件结构
hermes-guardian/
├── SKILL.md          # Skill 行为定义
├── README.md         # 本文件
├── cron/
│   ├── hardware-check.sh
│   └── daily-backup.sh
├── scripts/
│   ├── guardian_core.py
│   ├── narrator.py
│   ├── hardware_monitor.py
│   ├── network_monitor.py
│   ├── cost_tracker.py
│   ├── self_heal.py
│   ├── skill_auditor.py
│   ├── config_manager.py
│   ├── privacy_guard.py
│   └── daily_report.py
├── references/
│   ├── memory-thresholds.md
│   ├── model-cost-reference.md
│   └── security-policy.md
└── templates/
    └── monitor-config.yaml
```

所有脚本**无 CLI、无 argparse、无 main()**，纯函数设计供 guardian_core 调用。

---

## Privacy Notice

Hermes Sentinel 在用户本地运行，**不收集、不上传、不分享任何个人数据**。

### 本 skill 在本地检测什么

- **手机号、身份证号、银行卡号、邮箱地址**
  → 仅在待发送的数据中进行检测，传输前自动脱敏（例如 `138****1234`）
  → 原始数据**不被记录、不被上传**

### 本 skill 联网做什么

为检测网络质量，每 10 分钟对外发起以下探测（与浏览器检查连通性相同）：

| 目标 | 方式 | 是否传输数据 |
|------|------|-------------|
| `1.1.1.1:443` (Cloudflare) | TCP 握手后立即断开 | 无 |
| `8.8.8.8:443` (Google DNS) | TCP 握手后立即断开 | 无 |
| `github.com`, `baidu.com` | HTTP HEAD 请求 | 无 |
| 用户使用的 API 提供商 | TCP 握手或 DNS 查询 | 无 |

这些探测**不携带任何用户数据、不包含认证信息、不可被识别为特定用户**。

### 日志存储

- 所有日志存储在 `~/.hermes/logs/` 目录下
- 30 天前的日志自动清理
- 日志内容为结构化机器数据（硬件指标、网络延迟、API 调用次数），**不包含对话内容**

---

## License

MIT
