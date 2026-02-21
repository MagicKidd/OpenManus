# 双模型语音响应系统设计方案

> **版本**: v1.1 (评审修订版)
> **更新日期**: 2026-02-21
> **状态**: 设计中

---

## 一、现状问题

| # | 问题 | 描述 | 影响 |
|---|------|------|------|
| 1 | 延迟高 | 等深度思考模型生成完整回答后才能语音 | 用户等 5-10s 无反馈 |
| 2 | 语音不自然 | 语音和文字内容一样，像念稿子 | 缺乏对话感 |
| 3 | 打断丢内容 | 快速连续消息时语音互相覆盖 | 信息丢失 |
| 4 | 反馈不及时 | 用户问完问题后长时间空白 | 体验差，不确定系统是否在工作 |

---

## 二、核心设计理念

**分离语音和文字的职责**：语音负责"即时反馈 + 对话感"，文字负责"完整信息传达"。

```
┌─────────────────────────────────────────────────────────────┐
│                     用户发送消息                              │
└─────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
┌──────────────────────────┐  ┌──────────────────────────────┐
│   路径 A: 即时反馈        │  │   路径 B: 深度思考            │
│   规则模板（无 API 调用） │  │   MiniMax-M2.5（深度思考）    │
│                          │  │                              │
│   过渡语模板选择          │  │   生成完整回答（文字）         │
│   → TTS → 语音播放       │  │   → 显示在界面上              │
│   耗时: < 100ms          │  │   耗时: 3-10s                │
└──────────────────────────┘  └──────────────────────────────┘
                    │                   │
                    └─────────┬─────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              状态机协调：TTL 检查 + 打断处理                   │
└─────────────────────────────────────────────────────────────┘
```

### 与原方案的关键差异

| 维度 | 原方案 | 修订方案 |
|------|--------|----------|
| 过渡语生成 | 快速 LLM 模型 | **规则模板**（90%场景）+ LLM 备选（10%复杂场景） |
| 结束语 | 必有（Step 3） | **砍掉**，不增加额外延迟 |
| 打断处理 | 三种策略选择 | **显式状态机** + TTL 机制 |
| API 调用次数 | 每条消息 2-3 次 LLM | 每条消息 **1 次 LLM**（仅深度思考） |

---

## 三、语音 vs 文字分工

| | 语音（规则模板 / 快速模型） | 文字（慢速模型） |
|---|---|---|
| **触发时机** | 用户发送后 **立即**（< 100ms） | 思考完成后 |
| **内容风格** | 过渡语、确认语、承接语 | 详细、完整、报告式 |
| **长度** | 短（10-50 字） | 长（可上千字） |
| **生成方式** | 规则模板选择，无 API 调用 | LLM 深度思考 |
| **示例** | "好的，让我想想..." | 完整的技术方案、代码、列表 |

---

## 四、过渡语模板系统

### 4.1 两层架构

```
层 1（规则层）—— 覆盖 90% 场景，0 延迟
  ├── 根据意图分类选择模板
  ├── 根据对话轮次选择风格
  └── 随机化避免重复

层 2（LLM 层）—— 覆盖 10% 复杂场景
  ├── 用户问了需要确认理解的复杂问题
  ├── 多轮对话中需要承接上文内容
  └── 注入最近 3 轮压缩摘要作为上下文
```

### 4.2 规则模板库（按意图分类）

```yaml
# 通用确认
general:
  - "好的，让我想想。"
  - "收到，稍等一下。"
  - "明白了，我来处理。"
  - "没问题，马上来。"

# 分析类问题
analysis:
  - "好问题，让我分析一下。"
  - "这个值得好好想想。"
  - "让我梳理一下思路。"

# 创作/生成类
creative:
  - "有意思，让我构思一下。"
  - "好的，我来想想怎么写。"

# 查询/搜索类
search:
  - "我来查查看。"
  - "让我找一下相关信息。"

# 修改/调整类
modify:
  - "好的，我来调整一下。"
  - "没问题，马上修改。"

# 多轮承接
followup:
  - "好的，接着刚才的继续。"
  - "明白，我来展开说说。"

# 打招呼/闲聊
greeting:
  - "你好！有什么可以帮你的？"
  - "嗨，我在呢。"
```

### 4.3 模板选择逻辑

```python
def select_transitional_phrase(
    intent: str,
    turn_count: int,
    recent_phrases: list[str],
) -> str:
    """选择过渡语模板，避免连续重复"""
    pool = PHRASE_TEMPLATES.get(intent, PHRASE_TEMPLATES["general"])

    if turn_count > 5:
        pool = pool + PHRASE_TEMPLATES["followup"]

    available = [p for p in pool if p not in recent_phrases[-3:]]
    if not available:
        available = pool

    return random.choice(available)
```

### 4.4 LLM 层（仅复杂场景触发）

触发条件：

| 条件 | 说明 |
|------|------|
| 用户消息含指代词且上文复杂 | "刚才说的第二点能展开吗？" |
| 用户明确要求确认 | "你确定理解我的意思了吗？" |
| 连续 3+ 轮同主题深入对话 | 需要体现"我在跟进"的智能感 |

```python
fast_model_context = {
    "system": (
        "你是语音助手。根据用户消息和对话摘要，生成一句简短过渡语（≤50字）。"
        "语气自然、口语化，像朋友在回应。不要重复用户的问题。"
    ),
    "recent_summary": compressed_last_3_turns,  # 压缩摘要，非原文
    "user_message": current_message,
}

# 模型参数
model = "MiniMax-M2.5-highspeed"  # 无深度思考
temperature = 0.7
max_tokens = 60
timeout_ms = 1500  # 超时则降级到规则层
```

---

## 五、状态机设计

### 5.1 状态定义

```python
from enum import Enum

class ResponseState(Enum):
    IDLE = "idle"                         # 空闲，等待新消息
    TRANSITION_SPEAKING = "transition_speaking"  # 过渡语 TTS 播放中
    SLOW_THINKING = "slow_thinking"       # 深度模型思考中
    SLOW_DONE = "slow_done"               # 深度模型完成，文字已显示
    CANCELLED = "cancelled"               # 被新消息打断，清理中
```

### 5.2 状态转换图

```
                ┌──────────────────────────────────────┐
                │            新消息到达                  │
                └───────────────┬──────────────────────┘
                                │
                                ▼
                ┌──────────────────────────────────────┐
                │              IDLE                     │
                │  · 选择过渡语模板                      │
                │  · 调用 TTS                           │
                │  · 同时启动慢模型思考                   │
                └───────────┬──────────────────────────┘
                            │
                ┌───────────┴───────────┐
                ▼                       ▼
┌───────────────────────┐  ┌───────────────────────────┐
│  TRANSITION_SPEAKING  │  │     SLOW_THINKING         │
│  · 播放过渡语音频      │  │  · 深度模型生成中          │
│  · 界面显示"思考中..." │  │  · 可被新消息取消          │
└───────────┬───────────┘  └───────────┬───────────────┘
            │                          │
            │    ┌─────────────────────┘
            │    │
            ▼    ▼
┌──────────────────────────────────────┐
│            SLOW_DONE                  │
│  · 文字内容显示在界面                  │
│  · 过渡语音频已播完（或被 TTL 丢弃）   │
│  · 回到 IDLE                         │
└──────────────────────────────────────┘

[任意状态] ──新消息到达──▶ CANCELLED ──清理完成──▶ IDLE（重新开始）
```

### 5.3 打断处理矩阵

| 当前状态 | 新消息到达时的处理 | 资源清理 |
|----------|-------------------|----------|
| `IDLE` | 正常处理，无打断 | 无 |
| `TRANSITION_SPEAKING` | 停止 TTS 播放，取消慢模型，重新开始 | 停止 afplay/音频播放进程 |
| `SLOW_THINKING` | 取消慢模型请求，停止可能的 TTS，重新开始 | AbortController.abort() |
| `SLOW_DONE` | 保留已显示的文字，处理新消息 | 无需清理 |

### 5.4 TTL 机制

过渡语的 TTS 有时效性——如果慢模型已经完成，过期的过渡语不应该播放。

```python
TRANSITION_TTL_MS = 3000  # 过渡语有效期 3 秒

class TransitionTTL:
    def __init__(self):
        self.created_at: float = 0
        self.slow_model_done: bool = False

    def start(self):
        self.created_at = time.time()
        self.slow_model_done = False

    def mark_slow_done(self):
        self.slow_model_done = True

    def should_play(self) -> bool:
        """TTS 音频就绪时，判断是否应该播放"""
        if self.slow_model_done:
            return False  # 慢模型已完成，过渡语无意义
        elapsed = (time.time() - self.created_at) * 1000
        if elapsed > TRANSITION_TTL_MS:
            return False  # 超时，丢弃
        return True
```

---

## 六、TTS 管线控制

### 6.1 与现有 OpenClaw TTS 的集成

当前 OpenClaw 支持三种 TTS 提供商（ElevenLabs / OpenAI / Edge TTS），本方案在其上层增加管线控制，不改动底层 TTS 引擎。

```
                    ┌─────────────┐
                    │  管线控制层  │  ← 本方案新增
                    │ (TTL/状态机) │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │ OpenClaw TTS │  ← 现有基础设施
                    │ (tts-core)  │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ElevenLabs│ │  OpenAI  │ │ Edge TTS │
        └──────────┘ └──────────┘ └──────────┘
```

### 6.2 并发控制

```python
import asyncio

class TTSPipeline:
    def __init__(self):
        self._current_task: asyncio.Task | None = None
        self._play_process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def cancel_current(self):
        """取消当前正在进行的 TTS 任务和播放"""
        if self._play_process and self._play_process.returncode is None:
            self._play_process.terminate()
            self._play_process = None

        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            self._current_task = None

    async def speak(self, text: str, ttl: TransitionTTL | None = None):
        """生成并播放 TTS，支持 TTL 检查"""
        async with self._lock:
            await self.cancel_current()

            async def _do_speak():
                audio_path = await self._generate_tts(text)

                if ttl and not ttl.should_play():
                    return  # TTL 过期，丢弃

                self._play_process = await asyncio.create_subprocess_exec(
                    "afplay", audio_path
                )
                await self._play_process.wait()

            self._current_task = asyncio.create_task(_do_speak())
            await self._current_task

    async def _generate_tts(self, text: str) -> str:
        """调用 TTS API 生成音频文件"""
        # 复用 OpenClaw 现有 TTS 管线
        # 配置优先级: MiniMax > ElevenLabs > OpenAI > Edge
        ...
```

---

## 七、完整时序流程

### 7.1 正常流程

```
T+0ms     用户发送消息
          │
T+1ms     ├── 意图分类（规则层，本地）
          │
T+5ms     ├── 选择过渡语模板: "好问题，让我分析一下。"
          ├── 创建 TransitionTTL
          │
T+10ms    ├── [并行启动]
          │   ├── 路径 A: 过渡语 → TTS API → 音频
          │   └── 路径 B: 慢模型深度思考
          │
T+50ms    状态: TRANSITION_SPEAKING + SLOW_THINKING
          界面: "🧠 正在思考中..."
          │
T+300ms   TTS 音频就绪
          ├── TTL 检查: should_play() → True
          └── 开始播放: "好问题，让我分析一下。"
          │
T+2000ms  过渡语播放完毕
          │
T+5000ms  慢模型完成
          ├── TTL.mark_slow_done()
          ├── 状态 → SLOW_DONE
          └── 界面显示完整回答
          │
T+5100ms  状态 → IDLE
```

### 7.2 慢模型快速完成（TTL 生效）

```
T+0ms     用户发送简单消息: "几点了？"
          │
T+5ms     选择过渡语 → TTS API 调用
          │
T+800ms   慢模型完成（简单问题，思考很快）
          ├── TTL.mark_slow_done()
          ├── 显示文字回答
          │
T+1200ms  TTS 音频才就绪
          ├── TTL 检查: should_play() → False（慢模型已完成）
          └── 丢弃音频，不播放
```

### 7.3 打断流程

```
T+0ms     用户发送消息 A
T+5ms     过渡语 A → TTS → 播放中
T+10ms    慢模型 A 开始思考
          │
T+500ms   用户发送消息 B（打断）
          ├── 状态 → CANCELLED
          ├── 停止过渡语 A 的播放
          ├── 取消慢模型 A
          ├── 清理完成 → IDLE
          │
T+510ms   重新开始处理消息 B
          ├── 过渡语 B → TTS
          └── 慢模型 B 开始思考
```

---

## 八、配置项设计

```json
{
  "dualVoice": {
    "enabled": true,
    "transition": {
      "mode": "template",
      "fallbackToLLM": false,
      "llmModel": "MiniMax-M2.5-highspeed",
      "llmMaxTokens": 60,
      "llmTimeoutMs": 1500,
      "ttlMs": 3000,
      "contextTurns": 3
    },
    "slowModel": "MiniMax-M2.5",
    "interrupt": {
      "cancelOnNewMessage": true,
      "stopAudioOnCancel": true
    }
  }
}
```

### 配置项说明

| 路径 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `dualVoice.enabled` | boolean | `true` | 总开关 |
| `transition.mode` | string | `"template"` | `"template"` 规则模板 / `"llm"` 始终用 LLM |
| `transition.fallbackToLLM` | boolean | `false` | 规则模板模式下，复杂场景是否降级到 LLM |
| `transition.llmModel` | string | - | LLM 层使用的快速模型 |
| `transition.llmMaxTokens` | number | `60` | LLM 层最大输出 token |
| `transition.llmTimeoutMs` | number | `1500` | LLM 层超时（超时降级到模板） |
| `transition.ttlMs` | number | `3000` | 过渡语有效期（ms） |
| `transition.contextTurns` | number | `3` | LLM 层注入的历史对话轮数 |
| `slowModel` | string | - | 深度思考模型 |
| `interrupt.cancelOnNewMessage` | boolean | `true` | 新消息是否打断当前处理 |
| `interrupt.stopAudioOnCancel` | boolean | `true` | 打断时是否立即停止音频 |

---

## 九、失败降级策略

```
┌────────────────────────────────────────────────────────┐
│                    降级链                               │
│                                                        │
│  层 1: 规则模板（本地，不可能失败）                      │
│    ↓ 仅当 mode="llm" 或 fallbackToLLM=true            │
│  层 2: 快速 LLM 模型                                   │
│    ↓ 超时 / 失败                                       │
│  层 3: 降级回规则模板（兜底）                            │
│                                                        │
│  TTS 失败:                                             │
│    MiniMax TTS → OpenAI TTS → Edge TTS → 跳过语音      │
│                                                        │
│  慢模型失败:                                            │
│    · 过渡语已播放 → 显示错误提示文字                     │
│    · 过渡语未播放 → 直接显示错误提示                     │
└────────────────────────────────────────────────────────┘
```

```python
async def handle_message(message: str) -> None:
    """完整消息处理流程"""
    state_machine.transition_to(State.IDLE)

    # 过渡语生成（永远不会失败）
    try:
        if config.transition.mode == "llm":
            phrase = await generate_llm_transition(message, timeout=config.transition.llmTimeoutMs)
        else:
            phrase = select_transitional_phrase(intent, turn_count, recent_phrases)
    except Exception:
        phrase = select_transitional_phrase(intent, turn_count, recent_phrases)

    ttl = TransitionTTL()
    ttl.start()

    # 并行启动
    transition_task = asyncio.create_task(
        tts_pipeline.speak(phrase, ttl=ttl)
    )
    slow_task = asyncio.create_task(
        slow_model_think(message)
    )

    state_machine.transition_to(State.TRANSITION_SPEAKING)

    # 等待慢模型完成
    try:
        result = await slow_task
        ttl.mark_slow_done()
        display_text_result(result)
        state_machine.transition_to(State.SLOW_DONE)
    except asyncio.CancelledError:
        state_machine.transition_to(State.CANCELLED)
        return
    except Exception as e:
        ttl.mark_slow_done()
        display_error(str(e))

    # 等待过渡语任务自然结束（已被 TTL 控制）
    if not transition_task.done():
        transition_task.cancel()

    state_machine.transition_to(State.IDLE)
```

---

## 十、成本分析

### 每条消息的 API 调用对比

| | 改进前 | 修订方案（模板模式） | 原方案（LLM 模式） |
|---|--------|---------------------|-------------------|
| LLM 调用 | 1 次（慢模型） | **1 次**（慢模型） | 2-3 次（快+慢+结束语） |
| TTS 调用 | 1 次 | **1-2 次**（过渡语 + 可选正文摘要） | 2-3 次 |
| 总成本变化 | 基准 | **+0~30%**（仅 TTS 增加） | **+100~200%** |

### TTS 调用成本估算（以 MiniMax TTS 为例）

| 场景 | 文本长度 | 预估成本/次 |
|------|----------|------------|
| 过渡语 | 10-50 字 | ~¥0.001 |
| 完整回答摘要 | 100-500 字 | ~¥0.01 |

---

## 十一、待验证事项（P0）

| # | 事项 | 验证方式 | 阻塞等级 |
|---|------|----------|----------|
| 1 | MiniMax TTS 首帧延迟 | 实测 50 次取 P50/P95 | 方案可行性 |
| 2 | Edge TTS 延迟对比 | 与 MiniMax TTS 对比 | 备选方案 |
| 3 | 深度模型 + TTS 并发时的 QPS 限流 | 并发压测 | 方案稳定性 |
| 4 | afplay 进程终止延迟 | 实测 SIGTERM 响应时间 | 打断体验 |

---

## 十二、实施路线图

### Phase 1: MVP（1-2 天）

- [ ] 实现过渡语模板库（8 场景分类）
- [ ] 实现模板选择逻辑（含去重）
- [ ] 接入现有 TTS 管线（Edge TTS 优先，零成本）
- [ ] 基本状态机（IDLE / SPEAKING / THINKING / DONE）
- [ ] 基本打断逻辑（新消息取消当前）

### Phase 2: 管线优化（2-3 天）

- [ ] TTL 机制
- [ ] TTS 并发控制 + 进程管理
- [ ] 降级策略（TTS 提供商降级链）
- [ ] 配置项接入 `openclaw.json`

### Phase 3: 可选增强（视效果决定）

- [ ] LLM 层过渡语（复杂场景）
- [ ] 意图分类优化（更精准的模板匹配）
- [ ] 过渡语模板 A/B 测试框架

---

## 十三、预期效果

| 指标 | 改进前 | 修订方案 |
|------|--------|----------|
| 首次语音反馈延迟 | 5-10s | **< 500ms**（模板 + Edge TTS） |
| 首次语音反馈延迟 | 5-10s | **< 300ms**（模板 + TTS 预缓存） |
| 语音自然度 | 机械念稿 | **对话感**（口语化过渡语） |
| 用户感知 | 等很久没反馈 | **即时反馈** |
| 信息完整性 | 语音丢失内容 | **文字保完整** |
| API 成本 | 基准 | **+0~30%**（仅增加 TTS 调用） |
| 打断体验 | 语音重叠 | **即时停止 + 无残留** |

---

## 附录 A: 与 OpenClaw 现有 TTS 系统的关系

本方案**不替换**现有 TTS 系统，而是在其上层增加"过渡语管线控制"：

| 层级 | 组件 | 本方案涉及 |
|------|------|-----------|
| 应用层 | 过渡语选择 + 状态机 + TTL | **新增** |
| 管线层 | TTS 并发控制 + 打断 | **新增** |
| 引擎层 | OpenClaw TTS Core (tts-core.ts) | 复用现有 |
| 提供商层 | ElevenLabs / OpenAI / Edge TTS | 复用现有 |

## 附录 B: 文件结构（预期）

```
src/
├── dual_voice/
│   ├── __init__.py
│   ├── state_machine.py      # 状态机
│   ├── transition_phrases.py  # 过渡语模板库 + 选择逻辑
│   ├── tts_pipeline.py        # TTS 管线控制 + TTL
│   ├── handler.py             # 消息处理主流程
│   └── config.py              # 配置解析
├── templates/
│   └── phrases.yaml           # 过渡语模板数据
└── tests/
    └── dual_voice/
        ├── test_state_machine.py
        ├── test_transition_phrases.py
        ├── test_tts_pipeline.py
        └── test_handler.py
```
