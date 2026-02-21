# OpenClaw 升级维护项目

> 本项目用于 OpenClaw 的持续升级、维护和二次开发。

---

## 项目信息

| 项目 | 值 |
|------|-----|
| 主机 | Mac mini (macOS) |
| OpenClaw 版本 | 2026.2.20 |
| 配置文件 | `~/.openclaw/openclaw.json` |
| Workspace | `~/.openclaw/workspace/` |
| Gateway 端口 | 18789 |
| Dashboard | `http://127.0.0.1:18789/` |

---

## OpenClaw 核心配置

### 目录结构

```
~/.openclaw/
├── openclaw.json           # 主配置文件
├── workspace/              # 工作空间
│   ├── AGENTS.md          # Agent 行为指令
│   ├── SOUL.md            # Agent 人格定义
│   ├── TOOLS.md           # 工具配置记录
│   ├── IDENTITY.md        # 身份信息
│   ├── USER.md            # 用户信息
│   ├── HEARTBEAT.md       # 心跳任务
│   ├── skills/            # Workspace 级技能
│   ├── hooks/             # Workspace 级 hooks
│   ├── scripts/           # 自定义脚本
│   └── memory/            # Agent 记忆
└── agents/main/sessions/  # 会话记录 (.jsonl)
```

### 扩展点层级（可靠性从低到高）

| 层级 | 机制 | 适用场景 |
|------|------|----------|
| 1 | Workspace 文件 (SOUL.md/AGENTS.md/TOOLS.md) | Agent 人格/行为指令 |
| 2 | Skills (SKILL.md) | 教 Agent 使用特定工具 |
| 3 | Hooks (HOOK.md + handler.ts) | 事件驱动自动化 |
| 4 | Plugins (Node.js) | 注册工具/CLI/Hook |
| 5 | 外部 Daemon (LaunchAgent) | 独立监控/自动化 |

### Hook 支持的事件（2026.1.29）

| 事件 | 说明 | 状态 |
|------|------|------|
| `command:new` | `/new` 命令 | 可用 |
| `command:reset` | `/reset` 命令 | 可用 |
| `command:stop` | `/stop` 命令 | 可用 |
| `agent:bootstrap` | 系统提示注入前 | 可用 |
| `gateway:startup` | Gateway 启动后 | 可用 |
| `message:sent` | 消息发送后 | **未实现** |
| `message:received` | 消息接收后 | **未实现** |
| `session:start/end` | 会话开始/结束 | **未实现** |

---

## TTS 配置（当前方案）

### 架构

```
用户消息 → Gateway → Agent 回复 → 写入 .jsonl transcript
                                          ↓
                              tts-watcher.py (监控文件变化)
                                          ↓
                              tts-play.sh (调用 MiniMax API)
                                          ↓
                              afplay (后台播放音频)
```

### 关键文件

| 文件 | 说明 |
|------|------|
| `~/.openclaw/workspace/scripts/tts-play.sh` | MiniMax TTS v2 脚本 |
| `~/.openclaw/workspace/scripts/tts-watcher.py` | Session transcript 监控守护进程 |
| `~/Library/LaunchAgents/com.openclaw.tts-watcher.plist` | macOS LaunchAgent |
| `~/.openclaw/workspace/skills/minimax-tts/SKILL.md` | TTS skill 定义 |

### TTS 参数

| 参数 | 值 |
|------|-----|
| TTS Provider | MiniMax (speech-2.6-hd) |
| Voice | Chinese (Mandarin)_ExplorativeGirl |
| Emotion | happy |
| Max TTS chars | 脚本层 1500，watcher 层 200 |
| 轮询间隔 | 1 秒 |

### TTS 配置（openclaw.json）

```json
"messages": {
  "tts": {
    "auto": "off"
  }
}
```

> **注意**：有效值是 `"off"` / `"always"` / `"inbound"` / `"tagged"`，不是 `"never"`。

---

## 环境变量

| 变量 | 说明 | 必需 |
|------|------|------|
| `MINIMAX_API_KEY` | MiniMax API Key | 是 |
| `MINIMAX_GROUP_ID` | MiniMax Group ID | 是 |

---

## 常用命令

### Gateway 管理

```bash
openclaw gateway status           # 查看状态
openclaw gateway install          # 安装并启动
openclaw gateway stop             # 停止（会 uninstall LaunchAgent）
openclaw dashboard --no-open      # 获取带 token 的 Dashboard URL
```

### Skills

```bash
openclaw skills list              # 列出所有技能
openclaw skills list | grep ready # 只看已就绪的
```

### Hooks

```bash
openclaw hooks list               # 列出 hooks
openclaw hooks enable <name>      # 启用
openclaw hooks info <name>       # 详情
```

### Plugins

```bash
openclaw plugins list             # 列出插件
openclaw plugins install <path>  # 安装
```

### Sessions

```bash
openclaw agent -m "消息" --json           # CLI 发消息（单轮）
openclaw agent --session-id test -m "消息" --json  # 指定 session
```

### Approvals

```bash
openclaw approvals allowlist add --agent "*" "pattern"
# 示例
openclaw approvals allowlist add --agent "*" "~/.openclaw/workspace/scripts/tts-play.sh *"
```

### TTS Watcher 日志

```bash
tail -f /tmp/tts-watcher.log      # watcher 监控日志
tail -f /tmp/tts-openclaw.log     # TTS API 调用日志
```

### LaunchAgent

```bash
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.openclaw.tts-watcher.plist
launchctl bootout gui/501/com.openclaw.tts-watcher
launchctl kickstart gui/501/com.openclaw.tts-watcher
```

### Config

```bash
openclaw config get messages.tts   # 查看配置
# 注意：openclaw config set 不一定写入磁盘文件，建议直接编辑 ~/.openclaw/openclaw.json
```

---

## Crabwalk 监控面板

### 概述

[Crabwalk](https://github.com/luccast/crabwalk) 是 OpenClaw 的实时伴侣监控器，可可视化 Agent 的会话、工具调用、思考链路。

### 安装信息

| 项目 | 值 |
|------|-----|
| 版本 | v1.0.11 |
| 安装方式 | CLI release |
| 安装路径 | `~/.crabwalk/` + `~/.local/bin/crabwalk` |
| 监控地址 | `http://localhost:3000/monitor` |
| Gateway 连接 | `ws://127.0.0.1:18789`（自动检测 token） |
| 日志 | `~/.crabwalk/crabwalk.log` |

### 常用命令

```bash
crabwalk status             # 查看状态
crabwalk start --daemon     # 后台启动
crabwalk stop               # 停止
crabwalk update             # 更新到最新版本
crabwalk -p 8080            # 自定义端口
```

### 功能

- 实时节点图：ReactFlow 可视化 Agent 会话和动作链
- 多平台监控：同时监控 WhatsApp/Telegram/Discord/Slack
- 动作追踪：展开节点查看工具参数和载荷
- 会话过滤：按平台过滤、按接收者搜索
- QR Code：启动时显示二维码，手机扫码打开监控

---

## 踩坑记录

### 1. `provider: "shell"` 导致 Gateway 崩溃

- **现象**：Gateway 启动后无法访问 `127.0.0.1:18789`，ERR_CONNECTION_REFUSED
- **原因**：`openclaw.json` 中设置了 `"provider": "shell"` 和 `"shell": {...}`，新版已移除
- **修复**：将 TTS 配置改为 `{"auto": "off"}`

### 2. `tts.auto: "never"` 是无效值

- **现象**：修复 provider 后仍然报 Invalid config
- **原因**：有效值是 `"off"` 不是 `"never"`
- **修复**：`"auto": "off"`

### 3. `openclaw gateway stop` 会 uninstall LaunchAgent

- **现象**：stop 后 status 显示 "not loaded"
- **修复**：需要重新 `openclaw gateway install`

### 4. Dashboard 断开连接 "unauthorized: gateway token missing"

- **现象**：直接访问 `http://127.0.0.1:18789/` 显示 disconnected
- **原因**：需要带 token 参数
- **修复**：使用 `openclaw dashboard --no-open` 获取带 token 的 URL

### 5. Agent 不遵循 "每次都调用工具" 的指令

- **现象**：SOUL.md + AGENTS.md 中写了 MANDATORY 指令，Agent 仍然不调用 TTS
- **原因**：MiniMax M2.1 的 instruction-following 不够强
- **替代**：改用外部 Daemon 监控 transcript 文件

---

## 开发流程

### 升级 OpenClaw 版本

1. 检查当前版本：`openclaw --version`
2. 更新 OpenClaw：`openclaw upgrade` 或手动下载新版本
3. 迁移配置：检查 `openclaw.json` 是否有不兼容变更
4. 测试 Gateway：`openclaw gateway install && openclaw gateway status`
5. 验证 TTS：`openclaw agent -m "测试语音"`

### 安装新 Plugin

1. 将插件放到 `~/.openclaw/plugins/` 或指定路径
2. 执行 `openclaw plugins install <path>`
3. 重启 Gateway：`openclaw gateway stop && openclaw gateway install`

### 添加新 Hook

1. 在 `~/.openclaw/workspace/hooks/` 创建 `HOOK.md` + `handler.ts`
2. 启用：`openclaw hooks enable <hook-name>`
3. 查看状态：`openclaw hooks list`

### 调试技巧

1. 查看 Gateway 日志：`tail -f ~/.openclaw/logs/gateway.log`
2. 查看 Agent 会话：`ls ~/.openclaw/agents/main/sessions/`
3. 直接测试配置：`openclaw config get <key>`

---

## 源码位置

| 类型 | 路径 |
|------|------|
| **源码仓库** | `src/openclaw/` (GitHub: https://github.com/openclaw/openclaw) |
| **已安装版本** | `~/.local/.../node_modules/openclaw` → **符号链接到 src/openclaw** |
| **备份** | `~/.local/.../node_modules/openclaw.bak` |
| **运行时** | 2026.2.20 |
| **Crabwalk** | v1.0.11 (`~/.local/bin/crabwalk`) |

### 本地开发配置（已设置）

```
全局 node_modules/openclaw → 符号链接 → src/openclaw/
                                      ↓
                                   dist/ (已复制)
                                   node_modules/ (已复制)
```

**修改源码后生效**：
```bash
# 重启 Gateway
openclaw gateway stop
openclaw gateway install
```

### 源码目录结构

```
src/openclaw/
├── src/                  # 核心源码 (TypeScript)
├── extensions/          # 内置扩展
├── skills/              # 内置 Skills
├── docs/                # 官方文档
├── scripts/             # 脚本
├── AGENTS.md           # Agent 行为定义 (重要!)
├── CLAUDE.md           # → AGENTS.md (入口)
├── package.json         # 项目配置
└── README.md           # 官方文档
```

### 源码开发流程

```bash
# 进入源码目录
cd src/openclaw

# 查看当前安装版本对应的 commit
git log -1 --oneline

# 查看源码版本
cat package.json | grep '"version"'

# 拉取最新源码
git pull origin main

# 重新构建（如需要）
pnpm install
pnpm build
```

---

## 本项目结构

```
openclaw_upgrade/
├── CLAUDE.md                 # 本文件 - Cursor 入口规则
├── docs/                    # 文档
│   ├── upgrade-log.md      # 升级日志
│   └── config-changes.md   # 配置变更记录
├── scripts/                # 维护脚本
│   ├── backup-config.sh    # 备份配置
│   └── restore-config.sh   # 恢复配置
├── src/
│   └── openclaw/           # 源码 (GitHub clone)
└── README.md              # 项目说明
```

---

## 维护规则

1. 每次完成 OpenClaw 升级或配置变更后，记录到 `docs/upgrade-log.md`
2. 遇到新踩坑，追加到本文件的踩坑记录章节
3. 更新 OpenClaw 后，同步更新本文件的版本号
4. 重要配置变更，记录到 `docs/config-changes.md`
