#!/bin/bash
# Hermes Sentinel — 定时巡检（每 10 分钟）
# 由 install.sh 安装时自动配置 cron
# cron 环境 PATH 很短，显式设置以保证找到系统命令

export PATH="/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"

PYTHON=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo "/usr/bin/python3")
SKILL_DIR="$HOME/.hermes/skills/system/hermes-sentinel"

if [ ! -d "$SKILL_DIR" ]; then
    logger -t sentinel "ERROR: skill directory not found at $SKILL_DIR"
    exit 1
fi

cd "$SKILL_DIR" || exit 1

RESULT=$("$PYTHON" -c "
import sys
sys.path.insert(0, 'scripts')
from guardian_core import guardian_tick
r = guardian_tick()
msg = r.get('message', '') if r.get('notify') else ''
print(msg, end='')
" 2>&1)

if [ -n "$RESULT" ]; then
    logger -t sentinel "$RESULT"
fi
