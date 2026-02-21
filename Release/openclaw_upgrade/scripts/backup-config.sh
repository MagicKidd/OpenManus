#!/bin/bash
# OpenClaw 配置备份脚本

BACKUP_DIR="$HOME/openclaw_backups"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

echo "=== OpenClaw 配置备份 ==="
echo "时间: $(date)"
echo "备份目录: $BACKUP_DIR"

# 备份 openclaw.json
cp "$HOME/.openclaw/openclaw.json" "$BACKUP_DIR/openclaw.json.$DATE"
echo "✓ 备份 openclaw.json"

# 备份 workspace 文件
if [ -d "$HOME/.openclaw/workspace" ]; then
    BACKUP_WS="$BACKUP_DIR/workspace.$DATE"
    mkdir -p "$BACKUP_WS"
    cp -r "$HOME/.openclaw/workspace/"* "$BACKUP_WS/"
    echo "✓ 备份 workspace/"
fi

# 备份 LaunchAgent
if [ -f "$HOME/Library/LaunchAgents/com.openclaw.tts-watcher.plist" ]; then
    cp "$HOME/Library/LaunchAgents/com.openclaw.tts-watcher.plist" "$BACKUP_DIR/com.openclaw.tts-watcher.plist.$DATE"
    echo "✓ 备份 LaunchAgent"
fi

echo ""
echo "备份完成! 共 $(ls -1 $BACKUP_DIR | wc -l | tr -d ' ') 个备份文件"
echo "最新备份: $DATE"
