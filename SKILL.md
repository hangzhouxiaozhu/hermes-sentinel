---
name: hermes-guardian
description: 后台守护 — 硬件监控、网络质量检测、成本记账、故障自愈、隐私保护，全程自动无感运行
version: 2.0.0
author: Hermes Agent
type: system_daemon
platforms: [macos]
triggers:
  - type: tick
    interval: 600
    handler: guardian_tick
  - type: hook
    event: before_outbound
    handler: guardian_before_outbound
  - type: hook
    event: after_api_call
    handler: guardian_on_api_call
  - type: hook
    event: on_skill_install
    handler: guardian_on_skill_install
tags: [monitoring, network, cost-tracking, self-healing, security, privacy]
---

# Hermes Guardian · 无感守护者

Hermes Guardian 是一个**后台守护 skill**。它对用户完全透明——用户不需要知道它的存在，不需要调用任何命令。

## 核心理念：先解决，后求助

这是 Guardian 的**根本原则**，所有模块的行为都由它驱动：

```
问题发生
    ↓
① 能自动解决吗？  ──是──→ 静默修复，用户无感
    ↓ 否
② 等一等能恢复吗？ ──是──→ 自动重试，用户无感
    ↓ 否
③ 需要用户配合吗？ ──否──→ 内部记录，不打扰
    ↓ 是
④ 通知用户：
   "我刚才试了 XXX 没成功，
   你方便的时候能 YYY 吗？"
```

### 什么时候出声

所有面向用户的消息都是**请求型**而非**告知型**：

| 不要这样 | 要这样 |
|---------|-------|
| "内存 82%，请压缩上下文" | "内存快满了，我帮你压缩了上下文" |
| "网络不可用，状态码 503" | "我连不上网络，你能看看网线吗？" |
| "发现高危风险，已阻止" | "这个插件不太安全，我帮你拦下了" |
| "今日费用 $0.52" | （预算内，沉默） |

### 什么时候沉默

- 一切正常 → 绝对沉默
- 能自动修复 → 自动处理，沉默
- 同类型问题今天提醒过几次 → 节流，沉默
- 用户无法解决的问题 → 内部记录，不转移焦虑

---

## 触发条件与行为

### 1. 定时巡检（每 10 分钟）

Hermes 每 10 分钟自动调用 `guardian_tick()`，执行：

- **硬件检测** — 内存、CPU、磁盘、GPU
  - 正常 → 写日志，沉默
  - 预警 → 自动修复（如清理过期日志），沉默
  - 危险 → 自动保存 + 通知用户

- **网络质量检测** — 本地网络拓扑、公网连通性、DNS 质量、代理健康
  - 自动识别网络类型：直连 / 代理 / VPN / 企业内网
  - 不依赖特定 API 提供商或地区——自动发现用户实际使用哪些服务
  - 正常 → 沉默
  - 异常 → 诊断根因 + 给出可操作建议（而非报一堆技术指标）
  - 恢复后自动告知用户

- **故障检测** — API 连通性
  - 正常 → 沉默
  - 断连 → 自动重试 3 次，成功后沉默；失败后通知用户

### 2. 联网传输前（hook）

每次联网前自动调用 `guardian_before_outbound()`：

- 自动过滤手机号、身份证号、银行卡号、邮箱
- 用户无感，不影响正常使用
- 不删除数据中的字段，只脱敏值

### 3. API 调用后（hook）

每次 API 调用完成后自动调用 `guardian_on_api_call()`：

- 自动记录模型、Token、费用
- 仅当今日费用超预算时通知用户

### 4. 安装 Skill 前（hook）

安装新 Skill 前自动调用 `guardian_on_skill_install()`：

- 静态扫描：硬编码密钥、高危命令、恶意模式
- 致命/严重风险 → 自动阻止安装
- 低风险 → 静默放行
- 用户只看到"这个插件不太安全"或完全无感

---

## 模块

| # | 模块 | 自动触发 | 只在必要时出声 |
|---|------|---------|--------------|
| 1 | 硬件监控 | 每 10 分钟 | ✅ |
| 2 | 网络质量检测 | 每 10 分钟（轻量）+ 异常时深度检测 | ✅ 诊断+建议 |
| 3 | 成本记账 | 每次 API 调用后 | ✅ 仅超预算 |
| 4 | 故障自愈 | 每 10 分钟 | ✅ |
| 5 | Skill 安全审查 | 安装 Skill 前 | ✅ 仅被阻止时 |
| 6 | 配置冲突检测 | 安装 Skill 前 | ✅ 从不 |
| 7 | 隐私隔离 | 每次联网前 | ✅ 从不 |

---

## 用户能感知到的消息（示例）

```
"电脑内存快满了，还剩 2GB 空闲。"
"帮你清理了些旧日志，多了 1.5GB 空间。"
"网络不太稳，我换了一条路试试。"
"连不上网了，可能是代理没开，检查一下代理客户端。"
"网恢复了，可以继续用了。"
"本地网络正常，但外网连不上，可能宽带需要重新认证。"
"DNS 解析不了，试试把 DNS 改成 8.8.8.8。"
"到 api.openai.com 延迟偏高，如果你在国内试试走代理。"
"这个插件不太安全，我没让它装上。"
"今天 API 花了 $0.52 了，快到预算了。"
"一切正常。"
```

消息特点：
- 最多两句话
- 具体可操作
- 同类型每天最多 3 次

---

## 不做什么

以下 Hermes 原生功能，Guardian 不做：
- 依赖检查 → 用 `hermes doctor`
- 配置备份 → 用 curator
- 模型选择 → 用 `hermes model`
- 对话续接 → 用 `hermes --resume`

Guardian 不做 CLI 工具。所有功能被动触发。

---

## 日志文件

所有日志在 `~/.hermes/logs/` 下（JSONL 格式，供管理员排查），**不包含对话内容**：

| 文件 | 内容 |
|------|------|
| `hardware_monitor.log` | 硬件巡检 |
| `model_cost.log` | Token 费用 |
| `self_heal.log` | 故障恢复记录 |
| `network_monitor.log` | 网络诊断记录 |
| `skill_audit.log` | Skill 审查记录 |
| `privacy_guard.log` | 隐私操作记录 |

---

## 安装

```bash
cp -r hermes-guardian ~/.hermes/skills/system/
```

安装后自动通过 Hermes 的 hook 和 tick 机制激活，无需额外配置。
