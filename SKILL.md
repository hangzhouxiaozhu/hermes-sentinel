---
name: hermes-sentinel
description: Beginner-friendly intent translator + hardware monitoring, network quality detection, token stats, self-healing, security audit. Fully automatic, invisible to the user.
version: 2.0.0
author: Hermes Agent
type: system_daemon
platforms: [macos, linux, windows]
triggers:
  - type: tick
    interval: 600
    handler: guardian_tick
  - type: hook
    event: after_api_call
    handler: guardian_on_api_call
  - type: hook
    event: before_user_message
    handler: guardian_before_user_message
tags: [adaptive-understanding, monitoring, network, cost-tracking, self-healing, security]
---

# Hermes Sentinel · Invisible Guardian

Hermes Sentinel is a **background daemon skill**. It is completely transparent to the user — they don't need to know it exists or invoke any commands.

## Core Principle: Fix first, ask later

This is the **fundamental rule** that drives every module:

```
Problem detected
    ↓
① Can it auto-fix?        ──yes──→ Silent repair, user unaware
    ↓ no
② Can it recover if we wait?──yes──→ Auto-retry, user unaware
    ↓ no
③ Does user action help?  ──no───→ Log internally, don't bother
    ↓ yes
④ Notify the user:
   "I tried X but it didn't work.
    When you have a moment, could you Y?"
```

---

## Core Feature: Beginner-Friendly Intent Translator

When a novice user types short fuzzy commands like "too dark", "garbled", or "too slow",
Sentinel translates them into clear, actionable instructions that Hermes can execute directly.

### How it works

```
"too dark"
   ↓
intent_translator.translate("太暗")
   ↓
{
  "should_translate": true,
  "translated": "User thinks the current result is too dark. First determine
                 what they're working on (image, web page, or document).
                 If image/cover: increase brightness and title contrast,
                 check thumbnail and mobile readability. Avoid overexposure.",
  "category": "visual_adjustment"
}
```

### Supported fuzzy terms

| Category | User says | Hermes gets |
|----------|-----------|-------------|
| Visual | 太暗、太亮、不好看、太乱、看不清 | Specific visual adjustment instructions |
| Code/API | 乱码、报错、跑不起来、没反应 | Encoding fix, debug, runtime repair steps |
| Hermes usage | 太慢、太贵、连不上、没输出 | Performance, cost, network check |
| Document | 太啰嗦、太短、看不懂 | Simplify, expand, rewrite instructions |

> **Integration:** Requires the Hermes main loop to call `guardian_before_user_message()` before processing user input.

### When to speak

All user-facing messages are **requests**, not **notifications**:

| Don't say | Say |
|-----------|-----|
| "Memory at 82%, compress context" | "Memory is nearly full, I compressed the context for you" |
| "Network unavailable, status 503" | "I can't reach the network. Could you check the cable?" |
| "High-risk detected, blocked" | "This plugin didn't look safe, so I blocked it" |
| "Today's cost: $0.52" | (within budget, silent) |

### When to stay silent

- Everything normal → absolute silence
- Can be auto-fixed → fix silently
- Same issue already notified today → throttle, silent
- User can't fix it anyway → log internally, don't transfer anxiety

---

## Triggers & Behavior

### 1. Scheduled patrol (every 10 min)

Hermes calls `guardian_tick()` every 10 minutes:

- **Hardware check** — Memory, CPU, disk, GPU
  - Normal → log, silent
  - Warning → auto-repair (e.g. clean old logs), silent
  - Danger → auto-save + notify user

- **Network quality** — Topology, internet reachability, DNS quality, proxy health
  - Auto-detect network type: direct / proxy / VPN / corporate
  - Doesn't depend on specific API providers or region
  - Normal → silent
  - Anomaly → diagnose root cause + actionable advice
  - Recovery → auto-notify

- **Health check** — Skill integrity + log writability
  - Normal → silent
  - Broken → notify

### 2. Post-API-call (hook)

Every API call triggers `guardian_on_api_call()`:

- Records model name, input/output token count (from actual API response)
- Cost estimation only when a price table is configured

### 3. Pre-skill-install (requires Hermes integration)

Requires Hermes to call `guardian_on_skill_install(skill_path)` before installing a skill:

```python
from hermes_sentinel.guardian_core import guardian_on_skill_install
result = guardian_on_skill_install(skill_directory)
if not result["approved"]:
    # block installation, show result["reason"]
```

Features:
- Static scan: hardcoded secrets, dangerous commands, malicious patterns
- FATAL/CRITICAL → auto-block
- Low risk → auto-approve silently
- User sees only "this plugin didn't look safe" or nothing at all

> **Current status:** Requires Hermes main loop integration. Not auto-registered via plugin (Hermes's `VALID_HOOKS` doesn't include skill-install events). PRs welcome.

---

## Modules

| # | Module | Trigger | Speaks only when needed |
|---|--------|---------|------------------------|
| 1 | Hardware monitoring | Every 10 min | ✅ |
| 2 | Network quality | Every 10 min (lightweight) + deep on anomaly | ✅ diagnosis + advice |
| 3 | Token logging | Every API call | ✅ only over budget |
| 4 | Self-healing | Every 10 min | ✅ |
| 5 | Skill security audit | Before skill install | ✅ only when blocked |
| 6 | Config conflict detection | Before skill install | ✅ never |

---

## Messages the user might see (examples)

```
"Your computer is running low on memory — only 2GB free."
"I cleaned up some old logs, freeing 1.5GB."
"Network is a bit unstable. I'll try a different route."
"Can't reach the network — maybe the proxy isn't running?"
"Network is back."
"Local network is up but the internet is down — maybe the broadband needs re-authentication."
"DNS isn't resolving. Try changing to 8.8.8.8 or 114.114.114.114."
"High latency to api.openai.com. Try a proxy if you're in China."
"This plugin didn't look safe, so I blocked it."
"API costs today reached $0.52 — approaching the daily budget."
"All clear."
```

Characteristics:
- At most two sentences
- Specific and actionable
- Same type throttled to max 3 times per day

---

## What this skill does NOT do

Hermes native features that Sentinel does NOT duplicate:
- Dependency checks → use `hermes doctor`
- Config backups → use curator
- Model selection → use `hermes model`
- Session resumption → use `hermes --resume`

Sentinel has no CLI. All features are passive and trigger-driven.

---

## Log files

All logs in `~/.hermes/logs/` (JSONL format, for admin troubleshooting), **no conversation content**:

| File | Content |
|------|---------|
| `hardware_monitor.log` | Hardware patrol |
| `model_cost.log` | Token usage and cost |
| `self_heal.log` | Recovery records |
| `network_monitor.log` | Network diagnostics |
| `skill_audit.log` | Skill audit records |

---

## Installation

```bash
cp -r hermes-sentinel ~/.hermes/skills/system/
```

After installation, Sentinel activates automatically via Hermes's hook and tick mechanisms. No additional configuration needed.
