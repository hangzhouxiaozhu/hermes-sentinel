#!/bin/bash
# Hermes Guardian — 定时巡检（每 10 分钟）
# 调用 guardian_core 协调所有子模块
# 配合 Hermes cronjob 使用

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/.."

/usr/bin/python3 -c "
import sys
sys.path.insert(0, '$PROJECT_DIR/scripts')
from guardian_core import guardian_tick
result = guardian_tick()
if result.get('notify'):
    print(result.get('message', ''))
"
