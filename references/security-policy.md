# Skill 安全审查规则

## 审查流程

```
安装请求 → 来源判定 → 静态扫描 → 生成风险报告 → 用户决定放行/拒绝
```

注意: 最终审批由 Hermes 内置 approval 系统完成，本模块仅负责扫描和报告。

## 来源分级

| 来源 | 策略 | 说明 |
|------|------|------|
| `trusted` (agentskills.io, NousResearch) | 自动放行 | 记录审计日志 |
| `third_party` (GitHub 公共仓库) | 自动生成风险报告 | 有 HIGH+ 风险需人工确认 |
| `unknown` (本地文件/其他来源) | 强制弹窗报告 | 默认禁用，需手动确认 |

## 高危模式清单

### 致命 (FATAL) — 立即阻止
- `rm -rf /` 或 `rm -rf ~`
- fork bomb (`:(){ :|:& };:`)
- 系统文件破坏

### 严重 (CRITICAL) — 立即阻止
- 硬编码 AppSecret / API Key / Token
- 尝试读取或上传 `.env` 文件
- Telegram bot token 外泄

### 高风险 (HIGH) — 需审核
- `curl | bash` 远程执行
- OpenAI/Google/Slack API key 硬编码
- 配置外泄 (curl POST 上传敏感文件)

### 中风险 (MEDIUM) — 警告
- `eval()` / `exec()` 动态代码执行
- `os.system()` 系统调用
- 无限循环 / 无边界迭代
- 引用 `.env` 路径

### 低风险 (LOW) — 信息
- `subprocess` 调用（常见工具用法）
- `__import__` 动态导入

## 动态行为监控

安装后持续监测以下异常行为：
1. 读取 `~/.hermes/.env` 文件
2. 批量上传本地文件到外部
3. 修改 `config.yaml` 中安全相关配置
4. 创建新的 cron 任务（可能是持久化后门）

一旦检测到 → 立即强制停用 skill 并告警。
