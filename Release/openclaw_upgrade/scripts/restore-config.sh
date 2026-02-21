#!/bin/bash
# OpenClaw 配置恢复脚本

BACKUP_DIR="$HOME/openclaw_backups"

echo "=== OpenClaw 配置恢复 ==="
echo ""

# 列出可用备份
echo "可用备份:"
ls -1t "$BACKUP_DIR" | head -10
echo ""

read -p "输入要恢复的备份日期时间 (YYYYMMDD_HHMMSS): " DATE

if [ -z "$DATE" ]; then
    echo "错误: 请输入备份日期"
    exit 1
fi

# 检查备份文件是否存在
if [ ! -f "$BACKUP_DIR/openclaw.json.$DATE" ]; then
    echo "错误: 备份文件不存在: openclaw.json.$DATE"
    exit 1
fi

echo ""
echo "确认恢复以下备份: $DATE"
read -p "继续? (y/n): " CONFIRM

if [ "$CONFIRM" != "y" ]; then
    echo "取消恢复"
    exit 0
fi

# 执行恢复
echo ""
echo "开始恢复..."

cp "$BACKUP_DIR/openclaw.json.$DATE" "$HOME/.openclaw/openclaw.json"
echo "✓ 恢复 openclaw.json"

if [ -d "$BACKUP_DIR/workspace.$DATE" ]; then
    cp -r "$BACKUP_DIR/workspace.$DATE/"* "$HOME/.openclaw/workspace/"
    echo "✓ 恢复 workspace/"
fi

if [ -f "$BACKUP_DIR/com.openclaw.tts-watcher.plist.$DATE" ]; then
    cp "$BACKUP_DIR/com.openclaw.tts-watcher.plist.$DATE" "$HOME/Library/LaunchAgents/com.openclaw.tts-watcher.plist"
    echo "✓ 恢复 LaunchAgent"
fi

echo ""
echo "恢复完成! 请重启 Gateway: openclaw gateway stop && openclaw gateway install"
