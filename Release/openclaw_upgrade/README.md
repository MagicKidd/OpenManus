# OpenClaw 升级维护项目

> 用于 OpenClaw 的持续升级、维护和二次开发。

## 快速开始

1. **查看配置**：阅读 `CLAUDE.md` 了解完整配置
2. **查看升级日志**：`docs/upgrade-log.md`
3. **备份配置**：`./scripts/backup-config.sh`

## 项目结构

```
openclaw_upgrade/
├── CLAUDE.md                 # Cursor 入口规则（必读）
├── docs/
│   ├── upgrade-log.md       # 升级日志
│   └── config-changes.md    # 配置变更记录
├── scripts/
│   ├── backup-config.sh     # 备份配置
│   └── restore-config.sh    # 恢复配置
├── src/
│   └── openclaw/            # 源码 (https://github.com/openclaw/openclaw)
└── README.md
```

## 常用命令

```bash
# 备份配置
./scripts/backup-config.sh

# 查看 Gateway 状态
openclaw gateway status

# 查看 TTS 日志
tail -f /tmp/tts-watcher.log
```

## 文档

- [CLAUDE.md](CLAUDE.md) - 完整配置指南
- [升级日志](docs/upgrade-log.md)
- [配置变更记录](docs/config-changes.md)
