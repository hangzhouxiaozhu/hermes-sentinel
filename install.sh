#!/bin/bash
# Hermes Sentinel — 一键安装与 cron 配置
# 在终端运行: bash ~/Desktop/hermes-sentinel/install.sh

set -e

SKILL_NAME="hermes-sentinel"
SKILL_DIR="$HOME/.hermes/skills/system/$SKILL_NAME"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON=$(command -v python3)

echo "=============================="
echo " Hermes Sentinel · 安装脚本"
echo "=============================="

# ── 检查 Python ──
if [ -z "$PYTHON" ]; then
    echo "❌ 未找到 python3"
    exit 1
fi
echo "✅ Python: $($PYTHON --version)"
echo "✅ 源目录: $SOURCE_DIR"
echo "✅ 目标目录: $SKILL_DIR"

# ── 复制文件 ──
echo ""
echo "📦 复制文件 ..."
mkdir -p "$SKILL_DIR/scripts"
cp "$SOURCE_DIR"/scripts/*.py "$SKILL_DIR/scripts/"
cp -r "$SOURCE_DIR/cron" "$SKILL_DIR/"
cp "$SOURCE_DIR/SKILL.md" "$SKILL_DIR/"
[ -d "$SOURCE_DIR/templates" ] && cp -r "$SOURCE_DIR/templates" "$SKILL_DIR/"
[ -d "$SOURCE_DIR/references" ] && cp -r "$SOURCE_DIR/references" "$SKILL_DIR/"
chmod +x "$SKILL_DIR/cron/"*.sh
echo "✅ 技能文件复制完成"

# ── 安装 Hermes 插件（自动记录 token） ──
if [ -d "$SOURCE_DIR/plugin" ]; then
    PLUGIN_DIR="$HOME/.hermes/plugins/hermes-sentinel"
    mkdir -p "$PLUGIN_DIR"
    cp "$SOURCE_DIR/plugin/"* "$PLUGIN_DIR/" 2>/dev/null
    echo "✅ Hermes plugin 已安装到 ~/.hermes/plugins/hermes-sentinel/（自动记录每次 API 调用的 token 消耗）"
fi

# ── 创建日志和缓存目录 ──
mkdir -p "$HOME/.hermes/logs"
mkdir -p "$HOME/.hermes/cache/guardian"

# ── 设置 cron ──
echo ""
echo "⏰ 配置 cron 定时任务 ..."

TICK_SCRIPT="$SKILL_DIR/cron/hardware-check.sh"
DAILY_SCRIPT="$SKILL_DIR/cron/daily-backup.sh"
CRON_NEW=$(crontab -l 2>/dev/null || true)
ADDED=0

if echo "$CRON_NEW" | grep -q "$SKILL_NAME/cron/hardware-check"; then
    echo "  ⏭️  硬件巡检 cron 已存在，跳过"
else
    M_OFFSET=$(( RANDOM % 10 ))
    CRON_NEW="$CRON_NEW
$M_OFFSET-59/10 * * * * $TICK_SCRIPT 2>&1 | logger -t sentinel-tick"
    echo "  ✅ 已添加：每 10 分钟硬件+网络巡检"
    ADDED=1
fi

if echo "$CRON_NEW" | grep -q "$SKILL_NAME/cron/daily-backup"; then
    echo "  ⏭️  每日报告 cron 已存在，跳过"
else
    RND_MIN=$(( RANDOM % 30 ))
    CRON_NEW="$CRON_NEW
$RND_MIN 9 * * * $DAILY_SCRIPT 2>&1 | logger -t sentinel-daily"
    echo "  ✅ 已添加：每天 9:${RND_MIN} 日报"
    ADDED=1
fi

if [ "$ADDED" = "1" ]; then
    echo "$CRON_NEW" | crontab -
    echo "✨ cron 已更新"
fi

echo ""
echo "📋 当前 cron 任务（Sentinel 相关）："
crontab -l 2>/dev/null | grep -E "sentinel" || echo "  （无）"

# ── 首次运行 ──
echo ""
echo "🚀 执行首次运行验证 ..."

$PYTHON -c "
import sys
sys.path.insert(0, '$SKILL_DIR/scripts')
from os_detect import get_platform_name, get_python_version
from guardian_core import guardian_tick

print(f'  Platform: {get_platform_name()}')
print(f'  Python:   {get_python_version()}')

result = guardian_tick()
if result.get('notify'):
    print(f'  🌟 通知: {result.get(\"message\", \"\")[:80]}')
else:
    print('  ✅ 首次巡检完成，一切正常')
print('  📝 日志: ~/.hermes/logs/')
"

echo ""
echo "=============================="
echo " ✅ Hermes Sentinel 安装完成"
echo "=============================="
echo ""
echo "查看日志: tail -f ~/.hermes/logs/hardware_monitor.log"
echo "查看 cron: crontab -l | grep sentinel"
echo "手动巡检: bash $SKILL_DIR/cron/hardware-check.sh"
