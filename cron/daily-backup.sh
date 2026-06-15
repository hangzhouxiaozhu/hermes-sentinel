#!/bin/bash
# Hermes Sentinel — 每日巡检 + 日报（建议每天 9 点）
# 由 install.sh 安装时自动配置 cron

export PATH="/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"

PYTHON=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo "/usr/bin/python3")
SKILL_DIR="$HOME/.hermes/skills/system/hermes-sentinel"

if [ ! -d "$SKILL_DIR" ]; then
    logger -t sentinel "ERROR: skill directory not found at $SKILL_DIR"
    exit 1
fi

cd "$SKILL_DIR" || exit 1

"$PYTHON" -c "
import sys
sys.path.insert(0, 'scripts')
from guardian_core import guardian_tick, guardian_daily_report

# 执行巡检
guardian_tick()

# 生成日报
report = guardian_daily_report()
print(report)
" 2>&1 | logger -t sentinel-daily
