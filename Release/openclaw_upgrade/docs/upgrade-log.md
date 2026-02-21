# OpenClaw 升级日志

## 2026-02-21

| 项目 | 值 |
|------|-----|
| OpenClaw 版本 | 2026.1.29 |
| 项目创建日期 | 2026-02-21 |

### 初始状态

- TTS 方案：外部 watcher daemon + MiniMax API
- Hook 事件：仅支持 command/*, agent:bootstrap, gateway:startup
- Gateway 端口：18789

---

## 2026-02-21 (更新)

### 版本同步

- OpenClaw 运行时版本已升级到 **2026.2.20**（CLAUDE.md 之前记录 2026.1.29）
- 源码仓库 `src/openclaw/` 与 main 分支同步，版本 2026.2.20

### 新增：Crabwalk 实时监控面板

| 项目 | 值 |
|------|-----|
| Crabwalk 版本 | v1.0.11 |
| 安装方式 | CLI release (`~/.crabwalk/` + `~/.local/bin/crabwalk`) |
| 监控地址 | `http://localhost:3000/monitor` |
| 依赖 | qrencode (brew install) |

**功能**：实时节点图可视化 Agent 会话、工具调用、思考链路，支持多平台监控。

**启动**：`crabwalk start --daemon`

---

## 2026-02-21 (Skills 批量安装)

### 安装概览

从 23/63 ready 提升至 **31/71 ready**，新增 10 个社区 Skills。

### 第一梯队：地基能力

| Skill | 版本 | Slug | 状态 | 说明 |
|-------|------|------|------|------|
| ClawHub | v0.7.0 | `clawhub` | ready (已有) | 技能市场管理器 |
| Agent Browser | v0.2.0 | `agent-browser` | ready | Rust 无头浏览器自动化 |
| Brave Search | v1.0.1 | `brave-search` | ready | Brave 搜索 API（需 API Key） |
| Claw Shell | v1.0.0 | `claw-shell` | ready | tmux shell 执行（已装 tmux 3.6a） |
| Cron Mastery | v1.0.3 | `cron-mastery` | ready | 定时任务精通 |

### 社区推荐三件套

| Skill | 版本 | Slug | 状态 | 说明 |
|-------|------|------|------|------|
| Tavily Search | v1.0.0 | `tavily-search` | ready | Tavily AI 搜索（需 API Key） |
| Find Skills | v0.1.0 | `find-skills` | ready | 自动发现并安装 skills |
| Proactive Solvr | v1.6.7 | `proactive-solvr` | missing | 主动代理（需 `SOLVR_API_KEY`） |

### 第三梯队：生产力工具

| Skill | 版本 | Slug | 状态 | 说明 |
|-------|------|------|------|------|
| Gmail | v1.0.6 | `gmail` | ready | Gmail API + OAuth |
| Google Calendar | v0.1.0 | `google-calendar` | ready | Google Calendar API |
| Notion | v1.0.0 | `notion` | ready | Notion API 集成 |

### 新增依赖

```bash
brew install tmux      # claw-shell 依赖
brew install qrencode  # crabwalk 依赖（之前已装）
```

### 待配置的 API Key

| Skill | 环境变量 | 说明 |
|-------|---------|------|
| Brave Search | `BRAVE_API_KEY` | 从 brave.com/search/api 获取 |
| Tavily Search | `TAVILY_API_KEY` | 从 tavily.com 获取 |
| Proactive Solvr | `SOLVR_API_KEY` | 从 solvr.ai 获取 |
| Gmail | OAuth | 首次使用时引导 OAuth 授权 |
| Google Calendar | OAuth | 需 Google Cloud Console 配置 |
| Notion | `NOTION_API_KEY` | 从 notion.so/integrations 获取 |

### 安全状态

- Approvals 已启用，仅 TTS 脚本自动放行
- 其他工具执行需手动确认

---

## 2026-02-21 (第四梯队：进阶玩法)

### Nodes（设备节点能力）

- 已安装并启动 Node Host 服务（LaunchAgent）：`openclaw node install`
- 当前已配对并连接 1 个节点：本机 `JING的Mac mini`

常用命令：

```bash
openclaw node status     # Node Host 服务状态
openclaw nodes status    # 已配对节点列表
openclaw nodes pending   # 待审批配对请求
openclaw nodes approve <id>
openclaw nodes location <id>
openclaw nodes camera <id>
```

> 说明：图中“控制手机/定位/摄像头”需要手机端节点发起配对并授权相机/定位权限；本次已把 Mac 侧 Node Host 与网关能力打通。

### 进阶技能（锦上添花）

| 能力 | 对应 Skill | Slug | 状态 | 需要配置 |
|------|-----------|------|------|---------|
| Skill Creator | Skill Creator | `skill-creator` | ready (已有) | 无 |
| Spotify | Spotify | `spotify` | ready | 需本机已安装并登录 Spotify |
| Home Assistant | Home Assistant Agent (Secure) | `home-assistant-agent-secure` | missing | `HOME_ASSISTANT_URL` + `HOME_ASSISTANT_TOKEN` |
| Twitter/X | Twitter Command Center (AIsa) | `openclaw-twitter` | missing | `AISA_API_KEY` |

---

*持续更新...*
