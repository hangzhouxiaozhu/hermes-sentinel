# Hermes Sentinel · Invisible Guardian

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-lightgrey)]()
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux-yellow)]()
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-blue)]()
[![Tests: 139](https://img.shields.io/badge/Tests-139%20passed-brightgreen)]()

<br>

> **Hermes 后台守护助手** — 专为 AI 新手设计的全自动守护系统。  
> **Hermes Agent background daemon** — Auto-monitor memory, network, token usage, and security.  
> *Zero config. Zero maintenance. Zero privacy risk.*

---

## 项目简介 / About (中文)

**Hermes Sentinel** 是 [Hermes Agent](https://github.com/hangzhouxiaozhu/hermes-sentinel) 的官方后台守护 skill。  
它专门帮助 **AI 工具新手** 和 **非技术用户**，让 Hermes 用得更省心：

| 你的困扰 | Sentinel 帮你做 |
|----------|---------------|
| ❓ 说"太暗""乱码"表达不清 | ✅ **自动翻译**成清晰指令 |
| 💻 电脑内存/磁盘快满了 | ✅ **自动检测+清理**旧日志 |
| 🌐 连不上 API、代理没开 | ✅ **自动诊断**并告诉你怎么修 |
| 💰 AI 花了多少 token 不知道 | ✅ **自动记账**，每日汇总 |
| 🔒 装插件怕不安全 | ✅ **自动扫描**高危代码和密钥 |

**一句话：** 它不像一个"插件"，更像一个"不打搅你的管家"。后台静默运行，出问题才出声。

<br>

---

## Core Feature: Beginner-Friendly Intent Translator

When a novice user types short fuzzy commands ("too dark", "garbled", "too slow"),
Sentinel translates them into clear, actionable instructions that Hermes can execute directly.

```
"too dark"
   ↓
intent_translator.translate("太暗")
   ↓
{ "should_translate": true,
  "translated": "User thinks the current result is too dark. First determine
                 what they're working on. If image/cover: increase brightness
                 and title contrast, check thumbnail readability...",
  "category": "visual_adjustment" }
```

### Supported fuzzy terms

| Category | User says | Translated to |
|----------|-----------|--------------|
| Visual | 太暗、太亮、不好看、太乱、看不清 | Specific visual adjustment instructions |
| Code/API | 乱码、报错、跑不起来、没反应 | Encoding fix, debug, runtime repair |
| Hermes usage | 太慢、太贵、连不上、没输出 | Performance, cost, network check |
| Document | 太啰嗦、太短、看不懂 | Simplify, expand, rewrite |

> **Integration:** Requires the Hermes main loop to call `guardian_before_user_message()` before processing user input.

---

## Design Principles

> **Fix it first. If it can't be fixed, ask for help.**

All Sentinel modules follow the same flow:

1. Problem occurs → try auto-remediation
2. Still broken → wait a few seconds, retry (could be transient)
3. Still failing → evaluate if user action is needed
4. User action required → "I tried X and it didn't work. When you have a moment, could you Y?"

**Goal: 95% of the time, the user doesn't know Sentinel exists.**

> Clear boundary with Hermes: this skill only does what Hermes cannot natively.

---

## Architecture

```
┌────────────────────────────────────────────────────┐
│             Auto-running (no config needed)        │
├────────────────────────────────────────────────────┤
│                                                    │
│  cron (every 10 min) → guardian_core.guardian_tick │
│    ├─ hardware_monitor.check()    → auto-fix/notify│
│    ├─ network_monitor.check()     → diagnose/suggest│
│    └─ self_heal.quick_check()     → self-heal/notify│
│                                                    │
│  Plugin: post_api_request hook (Hermes native)     │
│    └─ cost_tracker.record() → auto token logging   │
│                                                    │
└────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────┐
│          Requires Hermes main loop integration      │
├────────────────────────────────────────────────────┤
│                                                    │
│  guardian_on_skill_install(skill_path)             │
│    └─ pre-install security audit + config conflicts │
│                                                    │
└────────────────────────────────────────────────────┘
```

**All modules communicate via flag files and the narrator layer — no direct terminal output.**

---

## Quick Start

```bash
# Clone or copy to Hermes skills directory
cp -r hermes-sentinel ~/.hermes/skills/system/

# Or in Hermes:
# /install hermes-sentinel
```

**That's it.** On first load, Sentinel automatically:
1. Creates log directories
2. Installs the Hermes plugin for token tracking
3. Configures cron for 10-minute patrols and daily reports
4. Starts monitoring immediately

Run `install.sh` for automated cron setup and plugin installation.

---

## Features

| Feature | Description | Auto-run | Speaks only when needed |
|---------|-------------|----------|------------------------|
| 🖥️ **Hardware Monitoring** | Memory, CPU, disk, GPU — auto-clean old logs at 90% disk | ✅ Every 10 min | ✅ |
| 🌐 **Network Quality** | Internet reachability, DNS, proxy health, API latency | ✅ Every 10 min | ✅ diagnosis + advice |
| 💰 **Token Tracking** | Auto-record prompt/completion tokens from every API call | ✅ Plugin: post_api_request | ✅ only over budget |
| 🛡️ **Self-Healing** | Skill integrity checks + log health | ✅ Every 10 min | ✅ |
| 🔒 **Security Audit** | Scan for API keys, malicious commands, secrets | Before skill install | ✅ only when blocked |
| 💬 **Intent Translator** | "太暗" → clear instruction for Hermes | Requires Hermes integration | passthrough by default |

---

## File Reference

| File | Purpose |
|------|---------|
| `scripts/guardian_core.py` | Central coordinator — tick/API/install entry points |
| `scripts/intent_translator.py` | Fuzzy input → clear instruction translator |
| `scripts/narrator.py` | Machine data → natural language + throttle |
| `scripts/os_detect.py` | Cross-platform abstraction (macOS/Linux/Windows) |
| `scripts/hardware_monitor.py` | Hardware data collection + auto-remediation |
| `scripts/network_monitor.py` | Network quality (proxy/VPN/DNS/gateway/internet) |
| `scripts/cost_tracker.py` | Token usage logging + cost estimation |
| `scripts/self_heal.py` | Skill integrity + log health checks |
| `scripts/skill_auditor.py` | Pre-scan for secrets, dangerous commands, malware |
| `scripts/daily_report.py` | Daily report generator |
| `cron/hardware-check.sh` | Cron tick entry point |
| `cron/daily-backup.sh` | Cron daily report entry point |
| `plugin/` | Hermes plugin for auto token tracking |
| `references/` | Internal reference docs |
| `templates/monitor-config.yaml` | Hardware threshold config template |

---

## Hook API (for Hermes main loop)

```python
from guardian_core import (
    guardian_tick,                # cron: hardware/network patrol every 10 min
    guardian_before_user_message, # fuzzy input → clear instruction translation
    guardian_on_api_call,         # record API token usage (auto via plugin)
    guardian_on_api_response,     # record token usage (from API response JSON)
    guardian_on_skill_install,    # [needs integration] pre-install security audit
    get_notification,             # check for pending notifications
    guardian_daily_report,        # generate one-line daily report
)
```

---

## Development

```bash
# File tree
hermes-sentinel/
├── SKILL.md              # Skill behavior definition
├── README.md             # This file
├── install.sh            # macOS/Linux installer
├── install.ps1           # Windows installer
├── plugin/
│   ├── __init__.py       # Hermes plugin: auto token tracking
│   └── plugin.yaml
├── cron/
│   ├── hardware-check.sh
│   └── daily-backup.sh
├── scripts/
│   ├── guardian_core.py
│   ├── intent_translator.py      # Fuzzy input → clear instruction
│   ├── narrator.py
│   ├── os_detect.py               # Cross-platform (macOS/Linux/Windows)
│   ├── hardware_monitor.py
│   ├── network_monitor.py
│   ├── cost_tracker.py
│   ├── self_heal.py
│   ├── skill_auditor.py
│   └── daily_report.py
├── references/
│   ├── memory-thresholds.md
│   ├── model-cost-reference.md
│   └── security-policy.md
├── templates/
│   └── monitor-config.yaml
└── tests/
    ├── test_os_detect.py
    ├── test_skill_auditor.py
    ├── test_narrator.py
    ├── test_cost_tracker.py
    ├── test_guardian_core.py
    ├── test_hardware_monitor.py
    ├── test_intent_translator.py
    ├── test_network_noise.py
    ├── test_self_heal.py
    └── test_plugin.py
```

**All scripts are pure functions — no CLI, no argparse, no main() — designed to be called by guardian_core.**

---

## Technical Highlights

- **Zero-touch install** — `import guardian_core` auto-configures cron, plugin, and directories
- **Cross-platform** — macOS (sysctl), Linux (/proc), Windows (PowerShell CIM)
- **Token accuracy** — Extracts real token counts from API response `usage` object
- **Noise reduction** — Network alerts require 3 consecutive failures before notification
- **Safety** — All data stays local, no telemetry, no external uploads
- **139 passing tests** — Full CI coverage

---

## Privacy Notice

Hermes Sentinel runs **fully locally**. It does not collect, transmit, or share any personal data.

### What does this skill do over the network?

To monitor network quality, it sends the following probes every 10 minutes (equivalent to what every browser does when checking connectivity):

| Target | Method | Data sent |
|--------|--------|-----------|
| `1.1.1.1:443` (Cloudflare) | TCP handshake, immediately close | None |
| `8.8.8.8:443` (Google DNS) | TCP handshake, immediately close | None |
| `github.com`, `baidu.com` | HTTP HEAD request | None |
| User's API providers | TCP handshake or DNS lookup | None |

These probes **carry no user data, no authentication, and cannot be attributed to a specific user**.

### Log storage

- All logs stored in `~/.hermes/logs/`
- Logs older than 30 days are automatically cleaned
- Log content is structured machine data (hardware metrics, network latency, API call counts) — **no conversation content**

---

## Why "Sentinel"?

**因为它在后台守护，不出声，不出错。**
*Because it watches. Silently. Reliably.*

Unlike monitoring dashboards or CLI tools that demand attention,
Hermes Sentinel is designed to be **forgotten about** — until something needs attention.

---

## License

MIT
