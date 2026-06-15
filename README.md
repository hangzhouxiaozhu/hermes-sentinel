# Hermes Sentinel · 无感守护者

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-lightgrey)]()
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux-yellow)]()
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-blue)]()

**Hermes 的后台守护 skill** — 硬件监控、网络质量检测、成本记账、故障自愈、安全审查。全部自动运行，用户无感。

## 核心亮点：自适应指令理解（行业坐标系）

这是 Sentinel 最核心的能力。当用户输入 ≤5 个字或指向模糊时，不走"对齐 skill 标准"的机械路线，而是三步专业重构：

```
"太暗"
   │
   ▼
① 行业定位 → 判断任务所属领域（公众号封面 → 新媒体视觉设计）
   │
   ▼
② 标准调取 → 三源交叉验证
   ├─ web_search("微信公众号封面设计最佳实践 2026")
   ├─ skill 已沉淀的用户专业标准
   └─ 模型训练数据中的行业共识
   │
   ▼
③ 专业重构 → 输出含设计原理的完整方案，而非"亮度+20"
```

**示例：**

| 用户说 | 对齐 skill 的机械做法 | Sentinel 的行业坐标系做法 |
|--------|---------------------|------------------------|
| "太暗" | 查到 #fdfcf9 → 换上 | 先搜行业标准 → 确认 #fdfcf9 是对的 → 加移动端 0.3s 视觉锚点原理 → 输出含金边竖线的完整方案 |
| "乱码" | 查到 `ensure_ascii=False` → 补上 | 搜微信 API 最佳实践 → 还发现 `charset=utf-8 header` → 一起修 |
| 未知场景 | 无 skill → 退回通用回答 | 现场搜索行业标准 → 构建临时坐标系 → 输出专业方案 |

**关键区别：**

| 对齐 skill 标准 | 行业坐标系（Sentinel） |
|----------------|---------------------|
| skill 写死"你试出来的正确答案" | skill 写死答案 + web_search 补行业当前最优解题思路 |
| 只做"查表替换" | 先确认 skill 的标准符合行业共识 |
| 未知场景投降 | 现场搜索建坐标，不投降 |
| 输出"亮度+20" | 输出含设计原理的完整方案 |

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
| `scripts/guardian_core.py` | 中央协调器，暴露 3 个 hook/tick 入口 |
| `scripts/narrator.py` | 机器数据 → 人话 + 通知节流 |
| `scripts/os_detect.py` | 跨平台适配层（macOS / Linux / Windows） |
| `scripts/hardware_monitor.py` | 硬件数据采集 + 自动修复 |
| `scripts/network_monitor.py` | 网络质量检测（代理/VPN/DNS/网关/公网） |
| `scripts/cost_tracker.py` | Token 费用记账 |
| `scripts/self_heal.py` | API 连通性检测 + 自动重试 |
| `scripts/skill_auditor.py` | Skill 安全审查（静默） |
| `scripts/config_manager.py` | 配置冲突检测（静默合并） |
| `scripts/daily_report.py` | 日报生成器（日志用） |
| `cron/hardware-check.sh` | Cron 定时巡检入口 |
| `cron/daily-backup.sh` | Cron 每日日报入口 |
| `references/` | 内部参考文档 |
| `templates/monitor-config.yaml` | 硬件阈值配置模板 |

---

## Hook 接口（供 Hermes 主循环调用）

```python
from guardian_core import (
    guardian_tick,                # 每 10 分钟
    guardian_on_api_call,         # API 调用后（需传入 token 数）
    guardian_on_api_response,     # API 返回后（自动解析响应体提取 token）
    guardian_on_skill_install,    # 安装 skill 前
    get_notification,             # 检查是否有通知待推送
    guardian_daily_report,        # 生成一句话日报
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
│   ├── os_detect.py          # 跨平台适配（macOS/Linux/Windows）
│   ├── hardware_monitor.py
│   ├── network_monitor.py
│   ├── cost_tracker.py
│   ├── self_heal.py
│   ├── skill_auditor.py
│   ├── config_manager.py
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
