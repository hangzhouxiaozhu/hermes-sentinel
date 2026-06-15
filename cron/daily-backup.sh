#!/bin/bash
# Hermes Guardian — 每日巡检 + 日报（建议每日 9:00）
# 调用 guardian_core 生成报告并记录日志

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/.."

/usr/bin/python3 -c "
import sys
sys.path.insert(0, '$PROJECT_DIR/scripts')

# 1. 执行定时巡检
from guardian_core import guardian_tick
guardian_tick()

# 2. 生成日报，写到日志
from daily_report import generate
report = generate()
log_path = '$PROJECT_DIR/../reports'
import os
os.makedirs(log_path, exist_ok=True)
with open(f'{log_path}/daily_$(date +%Y%m%d).md', 'w') as f:
    f.write(report)
"
