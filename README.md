# Hermes Sentinel · Invisible Guardian

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-lightgrey)]()
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux-yellow)]()
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-blue)]()

**Hermes Agent background daemon skill** — Adaptive instruction understanding (industry coordinate system), hardware monitoring, network quality detection, token stats, self-healing, security audit. All automatic, invisible to the user.

## Core Feature: Adaptive Instruction Understanding (Industry Coordinate System)

When user input is ≤8 characters or ambiguous ("too dark", "garbled", "fix it"), Sentinel does NOT blindly apply skill defaults. Instead, it uses a 4-layer engine to produce a professional rewrite:

```
"too dark"
   ↓
① Ambiguity detection → is_ambiguous_instruction() → needs rewrite
   ↓
② Context resolution → context_resolver: infer from current file, recent messages, active tool
   ↓  "wechat_article/cover/rendering" → industry matched
③ Industry matching → industry_profiles → new_media_visual_design (confidence 0.86)
   ↓  plus standards_registry → local standards loaded
④ Rewrite plan → build_rewrite_plan() → full instruction with rationale
```

**Key difference:**

| Traditional approach | Sentinel |
|---------|---------|
| Skill hardcodes answer, apply directly | Skill standards + industry rules + context signals cross-validated |
| Simple lookup-and-replace | Confirm industry first, output principle-driven solution |
| Unknown scenario → fallback to generic reply | No industry match → passthrough, no forced intervention |
| Output "brightness +20" | Output full rewrite plan for Hermes to execute |

### Decision table

| Input | Behavior |
|------|------|
| "too dark" + cover context | ✅ Rewrite to visual optimization instruction |
| "garbled" + Python/API context | ✅ Rewrite to encoding fix instruction |
| "continue" + no context | ⏭️ Passthrough, no intervention |
| "increase the brightness of this image by 20%" | ⏭️ Clear command, passthrough |

### Supported industries (v1)

| Industry | Signal words | Fuzzy terms |
|---------|-------------|-------------|
| New media visual design | cover, poster, rendering, wechat | too dark, looks bad, too messy |
| Social media content | xiaohongshu, post, copywriting, seo | no views, bad data, no traffic |
| Software engineering | code, error, garbled, API, Python | garbled, crash, won't run |
| AI operations | token, API, model, provider | too expensive, too slow |
| Document writing | doc, article, report, PPT | too verbose, too short |
| Data analysis | table, data, chart, visualization | unclear, wrong |

> **Integration:** Requires the Hermes main loop to call `guardian_before_user_message()` before processing user input.

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

## File Reference

| File | Purpose |
|------|---------|
| `scripts/guardian_core.py` | Central coordinator — tick/API/install entry points |
| `scripts/adaptive_understanding.py` | Fuzzy input detection + rewrite plan engine |
| `scripts/industry_profiles.py` | 6 industry classification tables |
| `scripts/context_resolver.py` | Session/file/skill context inference |
| `scripts/standards_registry.py` | Local standards register (13 built-in) |
| `scripts/narrator.py` | Machine data → natural language + throttle |
| `scripts/os_detect.py` | Cross-platform abstraction (macOS/Linux/Windows) |
| `scripts/hardware_monitor.py` | Hardware data collection + auto-remediation |
| `scripts/network_monitor.py` | Network quality (proxy/VPN/DNS/gateway/internet) |
| `scripts/cost_tracker.py` | Token usage logging + cost estimation |
| `scripts/self_heal.py` | Skill integrity + log health checks |
| `scripts/skill_auditor.py` | Pre-scan for secrets, dangerous commands, malware |
| `scripts/config_manager.py` | Config conflict detection + recommendation |
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
    guardian_on_api_call,         # record API token usage (auto via plugin)
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
├── plugin/
│   ├── __init__.py       # Hermes plugin: auto token tracking
│   └── plugin.yaml
├── cron/
│   ├── hardware-check.sh
│   └── daily-backup.sh
├── scripts/
│   ├── guardian_core.py
│   ├── adaptive_understanding.py  # Instruction understanding engine
│   ├── industry_profiles.py       # Industry classification
│   ├── context_resolver.py        # Session context inference
│   ├── standards_registry.py      # Standards register
│   ├── narrator.py
│   ├── os_detect.py               # Cross-platform (macOS/Linux/Windows)
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
├── templates/
│   └── monitor-config.yaml
└── tests/
    ├── test_adaptive_understanding.py  # 24 tests
    ├── test_os_detect.py
    ├── test_skill_auditor.py
    ├── test_narrator.py
    ├── test_cost_tracker.py
    ├── test_config_manager.py
    └── test_plugin.py
```

**All scripts are pure functions — no CLI, no argparse, no main() — designed to be called by guardian_core.**

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

## License

MIT
