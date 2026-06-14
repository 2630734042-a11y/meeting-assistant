# 双路音频采集（麦克风 + 系统音频）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实时会议助手的音频输入从单一的麦克风扩展为「麦克风 + 系统音频」双路采集，覆盖浏览器内在线会议场景。

**Architecture:** 将当前 `startMic()` 的单体逻辑拆分为三个独立函数：`captureMic()` 负责麦克风权限与流获取，`startSystemAudio()` 负责 `getDisplayMedia` 采集系统音频（用户取消时返回 null 降级），`setupAudioPipeline()` 负责 AudioContext 节点连接。Web Audio API 自动混音多源输入，ScriptProcessor 拿到的 buffer 已是混合后的单路信号，后端零改动。

**Tech Stack:** TypeScript, Vue 3 (Composition API), Web Audio API, MediaDevices API, Naive UI

---

### Task 1: 重构 `startMic()` → `captureMic()` + 新增 `audioSources` 状态 + `startSystemAudio()`

**Files:**
- Modify: `python/frontend/src/composables/useLiveSession.ts`

- [ ] **Step 1: 添加 `audioSources` 响应式状态**

在现有 ref 声明区域（`line 31` 附近）新增：

```typescript
const audioSources = ref<'mic_only' | 'mic_and_system'>('mic_only')
```

- [ ] **Step 2: 重命名 stream 变量 + 新增系统音频变量**

将现有 `let stream: MediaStream | null = null` 替换为：

```typescript
let micStream: MediaStream | null = null
let sysStream: MediaStream | null = null
```

在 `let timer` 行后新增 AudioContext 节点变量：

```typescript
let micSource: MediaStreamAudioSourceNode | null = null
let sysSource: MediaStreamAudioSourceNode | null = null
let micGain: GainNode | null = null
let sysGain: GainNode | null = null
```

- [ ] **Step 3: 将 `startMic()` 拆分为纯媒体流获取函数 `captureMic()`**

将当前 `startMic()` 函数（lines 111-143）替换为仅获取 MediaStream 的版本：

```typescript
// ---- 麦克风采流（不含 AudioContext 设置）----
async function captureMic(): Promise<MediaStream> {
  try {
    return await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        sampleRate: 16000,
        echoCancellation: true,
        noiseSuppression: true,
      },
    })
  } catch (err: any) {
    if (err.name === 'NotAllowedError') {
      error.value = '麦克风权限被拒绝，请在浏览器设置中允许麦克风访问'
    } else {
      error.value = `麦克风初始化失败: ${err.message}`
    }
    throw err
  }
}
```

- [ ] **Step 4: 新增 `startSystemAudio()` 函数**

在 `captureMic()` 之后添加：

```typescript
// ---- 系统音频采集（getDisplayMedia）----
async function startSystemAudio(): Promise<MediaStream | null> {
  try {
    const displayStream = await navigator.mediaDevices.getDisplayMedia({
      audio: true,
      video: { width: 1, height: 1 },
    })
    // 立即 stop 视频轨释放带宽
    const videoTracks = displayStream.getVideoTracks()
    for (const t of videoTracks) {
      t.stop()
      displayStream.removeTrack(t)
    }
    // 监听用户中途停止共享
    const audioTrack = displayStream.getAudioTracks()[0]
    if (audioTrack) {
      audioTrack.onended = () => {
        // 系统音频停止 → 降级为仅麦克风
        if (sysGain) sysGain.gain.value = 0
        if (micGain) micGain.gain.value = 1.0
        audioSources.value = 'mic_only'
      }
    }
    return displayStream
  } catch (e) {
    return null // 用户取消或浏览器不支持 → 降级
  }
}
```

- [ ] **Step 5: 新增 `setupAudioPipeline()` 函数**

在 `startSystemAudio()` 之后添加 AudioContext 节点连接函数：

```typescript
// ---- AudioContext 管线搭建 ----
function setupAudioPipeline(mic: MediaStream, sys: MediaStream | null): void {
  audioContext = new AudioContext({ sampleRate: 16000 })
  processor = audioContext.createScriptProcessor(4096, 1, 1)

  // 麦克风链路: micStream → micGain → processor
  micSource = audioContext.createMediaStreamSource(mic)
  micGain = audioContext.createGain()
  micGain.gain.value = sys ? 0.5 : 1.0  // 双路时减半防止溢出
  micSource.connect(micGain)
  micGain.connect(processor)

  // 系统音频链路（可选）: sysStream → sysGain → processor
  if (sys) {
    sysSource = audioContext.createMediaStreamSource(sys)
    sysGain = audioContext.createGain()
    sysGain.gain.value = 0.5
    sysSource.connect(sysGain)
    sysGain.connect(processor)
    audioSources.value = 'mic_and_system'
  } else {
    audioSources.value = 'mic_only'
  }

  // PCM 发送 — AudioContext 自动混音，inputBuffer 已是混合结果
  processor.onaudioprocess = (e: AudioProcessingEvent) => {
    if (!ws || ws.readyState !== WebSocket.OPEN || !isRecording.value) return
    const inputData = e.inputBuffer.getChannelData(0)
    ws.send(float32ToPCM16(inputData))
  }

  processor.connect(audioContext.destination)
}
```

- [ ] **Step 6: 验证前端构建通过**

Run:
```bash
cd python/frontend && npx vite build
```
Expected: Build succeeds (Task 1 adds new functions but doesn't change call sites yet; existing `start()` still references old `startMic()` internals).

- [ ] **Step 7: Commit**

```bash
git add python/frontend/src/composables/useLiveSession.ts
git commit -m "refactor: extract captureMic + startSystemAudio + setupAudioPipeline from startMic"
```

---

### Task 2: 重构 `start()` + `stop()` 接入双路管线

**Files:**
- Modify: `python/frontend/src/composables/useLiveSession.ts`

- [ ] **Step 1: 重写 `start()` 函数**

将当前 `start()` 函数（lines 161-186）替换为：

```typescript
// ---- Public API ----
async function start(title: string): Promise<void> {
  error.value = null
  transcript.value = []
  summary.value = null
  actions.value = null
  insights.value = null
  audioSources.value = 'mic_only'

  ws = connect()

  await new Promise<void>((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Connection timeout')), 10000)
    ws!.onopen = () => {
      clearTimeout(timeout)
      ws!.send(JSON.stringify({ type: 'start', meeting_id: meetingId, title }))
      resolve()
    }
    ws!.onerror = () => {
      clearTimeout(timeout)
      reject(new Error('Connection failed'))
    }
  })

  micStream = await captureMic()             // 必须成功，否则抛错
  sysStream = await startSystemAudio()       // 可选，失败返回 null → 降级
  setupAudioPipeline(micStream, sysStream)
  isRecording.value = true
  startTimer()
}
```

- [ ] **Step 2: 重写 `stop()` 函数以清理双路资源**

将当前 `stop()` 函数（lines 188-208）替换为：

```typescript
function stop(): void {
  isRecording.value = false
  stopTimer()

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'stop' }))
  }

  // 断开音频节点
  if (processor) {
    processor.disconnect()
    processor = null
  }
  if (micGain) { micGain.disconnect(); micGain = null }
  if (sysGain) { sysGain.disconnect(); sysGain = null }
  if (micSource) { micSource.disconnect(); micSource = null }
  if (sysSource) { sysSource.disconnect(); sysSource = null }
  if (audioContext) {
    audioContext.close()
    audioContext = null
  }

  // 停止麦克风媒体流
  if (micStream) {
    micStream.getTracks().forEach((t) => t.stop())
    micStream = null
  }
  // 停止系统音频媒体流
  if (sysStream) {
    sysStream.getTracks().forEach((t) => t.stop())
    sysStream = null
  }
}
```

- [ ] **Step 3: 更新 `onUnmounted` 清理逻辑中对 `stream` 的引用**

将 `onUnmounted` 中对 `stream` 的引用改为 `micStream` 和 `sysStream`。当前代码（lines 210-216）中 `stop()` 已处理清理，`onUnmounted` 只需确保 ws close，无需额外改动。

- [ ] **Step 4: 更新返回值接口，导出 `audioSources`**

在 `return { ... }` 块中添加：

```typescript
return {
  connected,
  transcript,
  summary,
  actions,
  insights,
  elapsedSeconds,
  error,
  isRecording,
  audioSources,   // 新增
  start,
  stop,
}
```

同步更新 `LiveSessionState` 接口（line 18）添加：

```typescript
export interface LiveSessionState {
  connected: Ref<boolean>
  transcript: Ref<TranscriptSegment[]>
  summary: Ref<MeetingSummary | null>
  actions: Ref<ActionResult | null>
  insights: Ref<MeetingInsight | null>
  elapsedSeconds: Ref<number>
  error: Ref<string | null>
  isRecording: Ref<boolean>
  audioSources: Ref<'mic_only' | 'mic_and_system'>  // 新增
}
```

返回类型签名无需改动——`audioSources` 已在 `LiveSessionState` 接口中，自动包含在 `LiveSessionState & { start, stop }` 交叉类型中。

- [ ] **Step 5: 验证前端构建通过**

Run:
```bash
cd python/frontend && npx vite build
```
Expected: Build succeeds with zero errors.

- [ ] **Step 6: Commit**

```bash
git add python/frontend/src/composables/useLiveSession.ts
git commit -m "feat: wire dual audio capture (mic + system) into start/stop pipeline"
```

---

### Task 3: 更新 `LiveMeetingView.vue` 显示音源状态

**Files:**
- Modify: `python/frontend/src/views/LiveMeetingView.vue`

- [ ] **Step 1: 从 composable 解构 `audioSources`**

在 `<script setup>` 的 `useLiveSession` 解构行（line 116-127）中添加：

```typescript
const {
  connected,
  transcript,
  summary,
  actions,
  insights,
  elapsedSeconds,
  error,
  isRecording,
  audioSources,   // 新增
  start,
  stop,
} = useLiveSession(meetingId)
```

- [ ] **Step 2: 在顶部状态栏添加音源指示标签**

在现有 `n-tag`（录音状态）之后（line 10 附近），添加音源标签：

```vue
<n-tag v-if="isRecording && audioSources === 'mic_and_system'" type="info" size="small" round>
  🎙+🔊 双路
</n-tag>
<n-tag v-else-if="isRecording" size="small" round>
  🎙 仅麦克风
</n-tag>
```

- [ ] **Step 3: 验证前端构建通过**

Run:
```bash
cd python/frontend && npx vite build
```
Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add python/frontend/src/views/LiveMeetingView.vue
git commit -m "feat: show dual audio source indicator in LiveMeetingView status bar"
```

---

### Task 4: 端到端手动验证

- [ ] **Step 1: 启动服务**

```bash
# 终端 1
cd python && python -m src.main
# 终端 2
cd python/frontend && npm run dev
```

- [ ] **Step 2: 仅麦克风路径（降级验证）**

1. 打开 `http://localhost:5173`，点击「🎙 实时会议」
2. 点击「开始会议」，在弹出共享对话框时**点击取消**
3. 验证：状态栏显示「🎙 仅麦克风」标签
4. 说几句话，验证转写正常
5. 点击「结束会议」

- [ ] **Step 3: 双路音频路径**

1. 新开会话，点击「开始会议」
2. 先授权麦克风，再在共享对话框中选择**一个正在播放音频的标签页**（如 B 站视频），勾选「共享系统音频」
3. 验证：状态栏显示「🎙+🔊 双路」标签
4. 验证：转写能捕获标签页的声音
5. 点击「结束会议」

- [ ] **Step 4: 中途停止共享（降级验证）**

1. 新开会话，选双路模式
2. 在 Chrome 底部共享提示栏点击「停止共享」
3. 验证：状态栏自动切换为「🎙 仅麦克风」，转写继续工作

- [ ] **Step 5: Firefox 降级验证**

```bash
# 用 Firefox 打开 http://localhost:5173
```
1. 启动会话
2. 验证：不会弹出共享对话框（Firefox 不支持 `getDisplayMedia({ audio: true })`）
3. 验证：状态栏直接显示「🎙 仅麦克风」

- [ ] **Step 6: Commit 验证结果记录**

```bash
git add -A
git commit -m "verify: dual audio capture manual tests passed"
```

---

### Spec Coverage Checklist

| Spec Requirement | Covered by |
|-----------------|-----------|
| `audioSources` 状态 | Task 1 Step 1 |
| `startSystemAudio()` 函数 | Task 1 Step 4 |
| `captureMic()` 拆分 | Task 1 Step 3 |
| `setupAudioPipeline()` 双路连接 | Task 1 Step 5 |
| GainNode 0.5/1.0 动态调整 | Task 1 Step 5 (micGain.gain.value = sys ? 0.5 : 1.0) |
| 视频轨 1x1 + stop 释放 | Task 1 Step 4 |
| `start()` 流程: WS→mic→sys→pipeline | Task 2 Step 1 |
| `stop()` 双流清理 | Task 2 Step 2 |
| 用户取消共享 → 降级 | Task 1 Step 4 (catch returns null) |
| 中途停止共享 → onended | Task 1 Step 4 (audioTrack.onended) |
| Firefox 降级 | Task 1 Step 4 (catch returns null) |
| LiveMeetingView 状态显示 | Task 3 |
