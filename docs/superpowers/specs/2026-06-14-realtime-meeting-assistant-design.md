# 实时会议助手（WebSocket 流式）— 技术规格

**日期**: 2026-06-14
**目标**: 在现有 Batch 模式基础上，新增实时会议模式：音频流式转写 + 增量 LLM 分析 + 前端直播仪表盘

---

## 1. 目标与范围

### 1.1 实时层级：Level 2 — 转写流式推送 + 增量洞察

| 层级 | 描述 |
|------|------|
| Level 1 | 仅转写流式推送，停会后跑完整分析（不做） |
| **Level 2（本次）** | 转写流式推送 + 后台定期增量分析 Summary/Actions/Insights |
| Level 3 | 加 VAD 实时打断检测、人工纠错、说话人切换事件（不做） |

### 1.2 核心体验变化

```
Batch 模式：录音 → 点停止 → 等待 → 一次性出报告
Stream 模式：录音 → 边录边看转写 + 洞察实时刷新 → 停会即出最终报告
```

---

## 2. 关键技术决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 转写引擎 | 分块 WhisperX + WebRTC VAD | 复用现有代码，无外部付费依赖 |
| 触发策略 | 混合触发（每 10 句 OR 每 60 秒） | 平衡实时性与 LLM 调用成本 |
| LLM 分析 | 滑动窗口（最近 20 句 + 上次摘要） | Token 消耗稳定，不随会议时长增长 |
| 前端布局 | 左右分栏（左转写流 + 右洞察面板） | 信息密度高，桌面端最佳 |
| 说话人识别 | 首次 chunk 跑 diarization，后续继承 speaker embedding | 避免每 chunk 重新识别 |

---

## 3. 系统架构

### 3.1 整体数据流

```
浏览器麦克风
    │
    │ MediaRecorder API (PCM 16kHz 单声道)
    │ WebSocket 二进制帧
    ▼
┌─────────────────────────────────────────┐
│           LiveSessionManager             │
│                                          │
│  ┌──────────────┐   ┌───────────────┐   │
│  │ AudioBuffer  │──▶│ChunkTranscriber│   │
│  │ (VAD 分块)   │   │ (WhisperX)    │   │
│  └──────────────┘   └───────┬───────┘   │
│                              │           │
│              transcript_delta│           │
│                              ▼           │
│  ┌──────────────────────────────────┐   │
│  │   IncrementalAnalyzer           │   │
│  │   混合触发: 10句 OR 60秒        │   │
│  │   滑动窗口: 最近20句 + 上次摘要   │   │
│  │   → Summary / Actions / Insights │   │
│  └──────────────────────────────────┘   │
│                                          │
│   所有结果通过 WebSocket 推送到前端       │
└─────────────────────────────────────────┘
```

### 3.2 与现有系统的关系

```
现有（Batch）:        新增（Stream）:
─────────────        ──────────────
                      AudioBuffer (NEW)
TranscriptionAgent →  ChunkTranscriber (MODIFIED — 加 chunk 模式)
SummaryAgent      →  IncrementalAnalyzer (NEW — 增量调用 SummaryAgent)
ActionAgent       ↗   IncrementalAnalyzer 内部复用
InsightAgent      ↗   IncrementalAnalyzer 内部复用
FollowUpAgent     →  停会后复用，生成最终报告
server.py          →  新增 /ws/live/{id} 端点
UploadView.vue     →  新增 LiveMeetingView.vue
```

---

## 4. 核心组件规格

### 4.1 AudioBuffer（VAD 分块器）

**职责**: 接收音频字节流，用 VAD 检测语音边界，切分为可转写的音频块。

**输入**: WebSocket 二进制帧（PCM 16-bit, 16kHz, 单声道）
**输出**: `(chunk_bytes, chunk_id, start_offset_ms)`

**关键参数**:
- VAD 模式: WebRTC VAD (aggressiveness=2, 中等激进)
- 静音阈值: 800ms 连续静音 → 切分边界
- 最大 chunk 长度: 10 秒（强制切分，防无停顿场景）
- 最小 chunk 长度: 1.5 秒（丢弃过短的噪声块）

**接口**:
```python
class AudioBuffer:
    async def feed(self, pcm_bytes: bytes) -> None: ...
    async def get_chunk(self) -> AudioChunk | None: ...  # VAD 边界触发
    def flush(self) -> AudioChunk: ...  # 停会时强制输出剩余
```

### 4.2 ChunkTranscriber（分块转写器）

**职责**: 对每个音频 chunk 跑 WhisperX 转写，逐句推送到前端。

**输入**: `AudioChunk (bytes, offset_ms)`
**输出**: 通过 WebSocket 推送 `transcript_delta` 消息

**关键设计**:
- 复用 `TranscriptionAgent._transcribe()` 核心逻辑，抽取为接收 `bytes` 参数的独立方法
- 时间戳转换: chunk 内偏移 + chunk 的全局 offset_ms → 绝对时间戳
- 说话人标签: 每个 chunk 独立跑 diarization（SPEAKER_01 等标签仅在 chunk 内有效）。跨 chunk 说话人匹配作为后续优化项（需要 speaker embedding 持久化）
- 降级: 首次 WhisperX 加载失败 → 切到 demo 模式（模拟句子流）

**限制（已知，不作本次范围）**:
- 跨 chunk 的说话人标签不一致（chunk A 的 SPEAKER_01 和 chunk B 的 SPEAKER_01 可能是不同人）
- 每个 chunk 独立跑 diarization，小 chunk（&lt;5s）可能导致说话人识别不准

**接口**:
```python
class ChunkTranscriber:
    async def transcribe_chunk(self, chunk: AudioChunk) -> list[TranscriptSegment]: ...
    def get_accumulated_text(self) -> str: ...  # 供增量分析使用
```

### 4.3 IncrementalAnalyzer（增量分析器）

**职责**: 监听新句子，按触发策略定期调用 LLM，更新 Summary/Actions/Insights。

**输入**: 新句子列表 + 累积全文
**输出**: 通过 WebSocket 推送 `summary_update` / `actions_update` / `insights_update`

**触发逻辑**:
```python
class IncrementalAnalyzer:
    TRIGGER_SENTENCE_COUNT = 10   # 累计 10 句新句子触发
    TRIGGER_TIME_SECONDS = 60     # 至少 60 秒触发一次
    
    SLIDING_WINDOW_SIZE = 20      # 滑动窗口大小（句数）
    
    async def on_new_sentences(self, sentences: list[str]) -> None:
        self._pending_count += len(sentences)
        if self._pending_count >= TRIGGER_SENTENCE_COUNT:
            await self._run_analysis()
            self._pending_count = 0
            self._last_analysis_time = time.time()
    
    # 后台定时器: 每 TRIGGER_TIME_SECONDS 检查一次
```

**Prompt 设计**: 滑动窗口 + 上一次输出
```
## 已有分析结果
上次摘要: {previous_summary}
上次待办: {previous_actions}
上次洞察: {previous_insights}

## 新增转写内容（最近 {window_size} 句）
{recent_transcript}

请基于以上信息，输出更新后的完整分析结果（JSON格式），合并新旧信息，
去重冲突项，保留仍有效的待办事项。
```

**并行策略**: Summary / Actions / Insights 三个分析并发执行（asyncio.gather），彼此独立。

### 4.4 LiveSessionManager（会话管理器）

**职责**: 管理单次实时会议的生命周期，协调 AudioBuffer / ChunkTranscriber / IncrementalAnalyzer。

**生命周期**:
```
[WebSocket 连接] → [start 消息] → [音频流持续] → [stop 消息] → [最终分析] → [断开]
```

**关键逻辑**:
```python
class LiveSessionManager:
    def __init__(self, meeting_id: str, websocket: WebSocket):
        self.buffer = AudioBuffer()
        self.transcriber = ChunkTranscriber(config)
        self.analyzer = IncrementalAnalyzer(llm_client)
        self._running = False
    
    async def run(self):
        """主循环：读取 WS 消息 → feed buffer → 转写 → 推送"""
        # 三个 asyncio.Task:
        # 1. audio_task: WebSocket 接收 → AudioBuffer.feed()
        # 2. transcribe_task: AudioBuffer.get_chunk() → ChunkTranscriber → push transcript_delta
        # 3. analyze_task: 定时器 + 句子计数 → IncrementalAnalyzer → push *_update
    
    async def stop(self):
        """停止：flush buffer → 转写剩余 → 触发最终完整分析 → push completed"""
```

---

## 5. WebSocket 消息协议

### 5.1 客户端 → 服务端

| 消息类型 | 格式 | 说明 |
|----------|------|------|
| `audio_frame` | 二进制 PCM 16kHz 16bit mono | 音频数据帧 |
| `start` | `{"type":"start", "meeting_id":"...", "title":"..."}` | 开始会议 |
| `stop` | `{"type":"stop"}` | 停止录制 |
| `ping` | `{"type":"ping"}` | 心跳（每 15 秒） |

### 5.2 服务端 → 客户端

| 消息类型 | 数据结构 | 说明 |
|----------|----------|------|
| `connected` | `{meeting_id, session_id}` | 连接确认 |
| `transcript_delta` | `TranscriptSegment` (JSON) | 每识别完一句立即推送 |
| `summary_update` | `MeetingSummary` (JSON) | 增量更新纪要 |
| `actions_update` | `ActionResult` (JSON) | 增量更新待办 |
| `insights_update` | `MeetingInsight` (JSON) | 增量更新洞察 |
| `completed` | `{meeting_id, report_url, status}` | 停会后最终完成 |
| `error` | `{message, traceback?}` | 错误通知 |
| `pong` | `{}` | 心跳回应 |

---

## 6. 前端规格

### 6.1 新页面: LiveMeetingView.vue

**路由**: `/live/:meetingId`

**布局**: 左右分栏

```
┌────────────────────────────────────────────┐
│ 🔴 会议进行中 | 00:12:34 | 3人发言           │  ← 顶部状态栏
├──────────────────────┬─────────────────────┤
│ 📝 实时转写          │ 📊 动态洞察           │
│                      │                     │
│ [张总] 00:00        │ ┌─────────────────┐ │
│ 好的，我们开始...     │ │ 📋 实时摘要      │ │
│                      │ │ Q3预算评审...    │ │
│ [李明] 00:08        │ └─────────────────┘ │
│ Q2预算执行率87%...   │                     │
│                      │ ┌─────────────────┐ │
│ [李明] 00:16  ⬤     │ │ 📌 待办事项      │ │
│ Q3计划上调15%...     │ │ 1. 整理Q3预算    │ │
│                      │ │ 2. 拟定招聘JD    │ │
│ ▊▊▊ 继续识别中...    │ └─────────────────┘ │
│                      │                     │
│                      │ ┌─────────────────┐ │
│                      │ │ 💡 发言统计      │ │
│                      │ │ 张总 38% ████   │ │
│                      │ │ 李明 35% ███▌   │ │
│                      │ │ 王芳 27% ██▋    │ │
│                      │ └─────────────────┘ │
│                      │                     │
│                      │ ⏱ 上次更新: 30秒前   │
├──────────────────────┴─────────────────────┤
│              [⏹ 结束会议] [⏸ 暂停]          │  ← 底部控制栏
└────────────────────────────────────────────┘
```

### 6.2 组件复用

| 现有组件 | 用途 |
|----------|------|
| `SummaryPanel.vue` | 右侧摘要卡片（实时刷新） |
| `ActionsPanel.vue` | 右侧待办卡片（只读模式，HITL 审核在会后） |
| `InsightsPanel.vue` | 右侧洞察卡片（实时刷新） |

### 6.3 WebSocket 连接管理

```typescript
// composables/useLiveSession.ts
function useLiveSession(meetingId: string) {
  const ws = new WebSocket(`ws://localhost:8000/ws/live/${meetingId}`)
  
  // 麦克风采集
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  const audioContext = new AudioContext({ sampleRate: 16000 })
  const processor = audioContext.createScriptProcessor(4096, 1, 1)
  
  processor.onaudioprocess = (e) => {
    const pcm = convertToPCM16(e.inputBuffer)
    ws.send(pcm)  // 发送二进制帧
  }
  
  ws.onmessage = (e) => {
    if (e.data instanceof Blob) return  // 忽略二进制回显
    const msg = JSON.parse(e.data)
    switch (msg.type) {
      case 'transcript_delta': transcript.value.push(msg.data); break
      case 'summary_update': summary.value = msg.data; break
      case 'actions_update': actions.value = msg.data; break
      case 'insights_update': insights.value = msg.data; break
      case 'completed': router.push(`/report/${msg.meeting_id}`); break
    }
  }
}
```

---

## 7. 文件变更清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `python/src/realtime/__init__.py` | 实时模块导出 |
| `python/src/realtime/audio_buffer.py` | VAD 分块器 |
| `python/src/realtime/chunk_transcriber.py` | 分块转写器 |
| `python/src/realtime/incremental_analyzer.py` | 增量分析器 |
| `python/src/realtime/session_manager.py` | 会话管理器 |
| `python/frontend/src/views/LiveMeetingView.vue` | 实时会议页面 |
| `python/frontend/src/composables/useLiveSession.ts` | WebSocket + 麦克风 Hook |

### 修改文件

| 文件 | 改动 |
|------|------|
| `python/src/agents/transcription_agent.py` | 抽取 `_transcribe_bytes()` 方法，支持不依赖 state 的独立调用 |
| `python/src/websocket/server.py` | 新增 `/ws/live/{id}` 端点 |
| `python/frontend/src/router/index.ts` | 新增 `/live/:meetingId` 路由 |
| `python/frontend/src/views/UploadView.vue` | 添加「实时会议」入口按钮 |

---

## 8. 新增依赖

| 依赖 | 用途 | 安装 |
|------|------|------|
| `webrtcvad` | VAD 语音活动检测 | `pip install webrtcvad` |
| `numpy` | PCM 数据处理（已有） | 已安装 |

前端无新增依赖，浏览器原生 API：`MediaRecorder`、`AudioContext`、`WebSocket`。

**PCM 转换说明**: 浏览器 `AudioContext` 输出 Float32（-1.0~1.0），需在前端转换为 PCM 16-bit signed integer（-32768~32767）后通过 WebSocket 发送。转换代码在 `useLiveSession.ts` 中实现。

---

## 9. 降级与容错

| 场景 | 处理 |
|------|------|
| WhisperX 未安装 | 切到 demo 模式，模拟句子流推送 |
| VAD 未安装 (webrtcvad) | 用固定时长分块（5 秒一刀） |
| LLM 调用失败 | 保留上次结果，推送 `error` 消息，等待下次触发 |
| WebSocket 断开 | 保留已转写文本，支持重连恢复（通过 session_id） |
| 麦克风权限拒绝 | 前端提示，提供「上传音频文件」降级入口 |

---

## 10. 验证方式

### 10.1 单元测试
- `test_audio_buffer.py`: 模拟 PCM 数据，验证 VAD 分块边界
- `test_chunk_transcriber.py`: 用 demo 模式验证转写 + 时间戳转换
- `test_incremental_analyzer.py`: 验证触发计数 + 滑动窗口逻辑

### 10.2 集成测试
- `test_live_session.py`: 模拟 WebSocket 连接 → 发送音频帧 → 停止 → 验证完整消息流

### 10.3 手动验证
1. `python -m src.main` 启动服务
2. `cd python/frontend && npm run dev` 启动前端
3. 访问 `http://localhost:5173` → 点击「实时会议」
4. 授予麦克风权限，开始说话
5. 观察左侧转写流逐句出现、右侧面板定期刷新
6. 点击「结束会议」，自动跳转到最终报告页
