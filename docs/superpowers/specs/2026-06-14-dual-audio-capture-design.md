# 双路音频采集（麦克风 + 系统音频）设计文档

> **日期：** 2026-06-14
> **状态：** 已批准
> **范围：** 前端 only，后端零改动

## 目标

实时会议助手当前仅采集麦克风。需要同时采集**系统音频输出**（浏览器标签页的会议声音），实现"麦克风 + 系统音频"双路混音，覆盖浏览器内在线会议场景（腾讯会议/飞书/Zoom Web）。

## 架构

```
麦克风     → getUserMedia     → MediaStreamSource → GainNode(0.5) ─┐
系统音频   → getDisplayMedia  → MediaStreamSource → GainNode(0.5) ─┤
                                                                     ▼
                                                        ScriptProcessor(4096)
                                                              │
                                                      逐样本相加 + clamp
                                                              │
                                                           PCM16
                                                              │
                                                       WebSocket
                                                              │
                                                     /ws/live/{id} (不变)
```

- 两路音频各自进入独立的 `MediaStreamSource`
- 各接一个 `GainNode(gain=0.5)` 防止叠加后溢出
- 汇入同一个 `ScriptProcessor` ← Web Audio API **自动混音**（多源 connect 到同一节点时内置求和）
- `onaudioprocess` 收到的 `inputBuffer` 已是混音后的信号，直接转 PCM 发送即可
- 后端 `/ws/live/{meeting_id}` 收到的仍是单路 PCM 二进制帧，**零改动**

## 改动范围

### 修改文件

| 文件 | 说明 | 行数 |
|------|------|------|
| `python/frontend/src/composables/useLiveSession.ts` | 拆分 `startMic()`，新增 `startSystemAudio()` + 混音逻辑 + 状态 | ~80 |
| `python/frontend/src/views/LiveMeetingView.vue` | 状态栏显示音源信息 | ~10 |

### 不改动

- 后端所有文件
- WebSocket 协议
- `audio_buffer.py` / `chunk_transcriber.py` / `session_manager.py` 等

## 关键接口

### useLiveSession 变更

```typescript
// 新增状态
const audioSources = ref<'mic_only' | 'mic_and_system'>('mic_only')

// 新增函数
async function startSystemAudio(): Promise<MediaStream | null> {
  try {
    return await navigator.mediaDevices.getDisplayMedia({
      audio: true,
      video: { width: 1, height: 1 }, // 最小化视频采集，仅取1x1像素视频轨（API要求）
    })
  } catch (e) {
    return null // 用户取消或浏览器不支持 → 降级
  }
}

// 注：不需要手动 mixBuffers。Web Audio API 中多个 source 连接到同一个
// ScriptProcessor 时，AudioContext 会自动对信号求和（auto-mix）。
// ScriptProcessor.onaudioprocess 拿到的 inputBuffer 已经是混音后的结果。
```

### start() 流程变更

```
1. ws = connect()
2. await startMic()           // 必须成功，否则抛错
3. sysStream = await startSystemAudio()  // 可选，失败 → audioSources = 'mic_only'
4. 创建 AudioContext(16000)
5. 创建 micSource = audioContext.createMediaStreamSource(micStream)
6. 创建 micGain = audioContext.createGain(); micGain.gain.value = attr.source === 'both' ? 0.5 : 1.0
7. 如果有 sysStream:
   - sysSource = audioContext.createMediaStreamSource(sysStream)
   - sysGain = audioContext.createGain(); sysGain.gain.value = 0.5
   - 两路连接到各自的 GainNode → ScriptProcessor
   - audioSources = 'mic_and_system'
8. ScriptProcessor.onaudioprocess:
   - 拿到的 inputBuffer 已是 AudioContext 自动混音结果（单路或双路）
   - 直接 float32ToPCM16(inputBuffer) → ws.send(pcm)
9. isRecording = true; startTimer()
```

**注意：** `getDisplayMedia` 的视频轨（1x1像素）需要在 ScriptProcessor 连接后立即 `stop()` 释放带宽。

## 错误处理 / 降级策略

| 情况 | 触发条件 | 行为 |
|------|---------|------|
| 用户拒绝麦克风 | `getUserMedia` 抛 `NotAllowedError` | 显示错误，不启动会话 |
| 用户取消标签页共享 | `getDisplayMedia` 抛 `AbortError` | 降级为仅麦克风，`audioSources = 'mic_only'` |
| 浏览器不支持系统音频采集 | `getDisplayMedia` 不支持 `audio: true` | 同上 |
| 音频帧长度不一致 | 两个 source 的 `onaudioprocess` 帧长不同 | AudioContext 以固定 bufferSize(4096) 统一采样，不会出现不一致 |
| 标签页共享中途被用户停止 | `MediaStreamTrack.onended` 触发 | 自动切回仅麦克风，不移除已连接的 source 节点 |

## 测试

| 测试点 | 方式 |
|--------|------|
| 仅麦克风（降级路径） | 现有测试覆盖 |
| 双路混音 AudioContext 自动混合 | 手动：开音乐 + 说话，检查 PCM 数据不溢出 [-1, 1] |
| 系统音频采集取消 | 点击"取消"共享对话框，验证降级 |
| Chrome/Edge 兼容性 | `getDisplayMedia({ audio: true })` 在 Chrome 74+/Edge 79+ 支持 |
| 视频轨释放 | 验证共享结束后 1x1 视频 track 已 stop |

## 浏览器兼容性

| 浏览器 | 支持 `getDisplayMedia({ audio: true })` | 行为 |
|--------|---------------------------------------|------|
| Chrome 74+ | ✅ | 全功能 |
| Edge 79+ | ✅ | 全功能 |
| Firefox | ❌ | 降级为仅麦克风 |
| Safari | ❌ | 降级为仅麦克风 |
