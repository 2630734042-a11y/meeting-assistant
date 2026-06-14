import { ref, onUnmounted, type Ref } from 'vue'
import type {
  TranscriptSegment,
  MeetingSummary,
  ActionResult,
  MeetingInsight,
} from '../shared/types'

export interface LiveSessionState {
  connected: Ref<boolean>
  transcript: Ref<TranscriptSegment[]>
  summary: Ref<MeetingSummary | null>
  actions: Ref<ActionResult | null>
  insights: Ref<MeetingInsight | null>
  elapsedSeconds: Ref<number>
  error: Ref<string | null>
  isRecording: Ref<boolean>
  audioSources: Ref<'mic_only' | 'mic_and_system'>
}

export function useLiveSession(meetingId: string): LiveSessionState & {
  start: (title: string) => Promise<void>
  stop: () => void
} {
  const connected = ref(false)
  const transcript = ref<TranscriptSegment[]>([])
  const summary = ref<MeetingSummary | null>(null)
  const actions = ref<ActionResult | null>(null)
  const insights = ref<MeetingInsight | null>(null)
  const elapsedSeconds = ref(0)
  const error = ref<string | null>(null)
  const isRecording = ref(false)
  const audioSources = ref<'mic_only' | 'mic_and_system'>('mic_only')

  let ws: WebSocket | null = null
  let audioContext: AudioContext | null = null
  let processor: ScriptProcessorNode | null = null
  let micStream: MediaStream | null = null
  let sysStream: MediaStream | null = null
  let micSource: MediaStreamAudioSourceNode | null = null
  let sysSource: MediaStreamAudioSourceNode | null = null
  let micGain: GainNode | null = null
  let sysGain: GainNode | null = null
  let timer: ReturnType<typeof setInterval> | null = null

  // ---- PCM 转换 ----
  function float32ToPCM16(buffer: Float32Array): ArrayBuffer {
    const len = buffer.length
    const pcm = new Int16Array(len)
    for (let i = 0; i < len; i++) {
      const s = Math.max(-1, Math.min(1, buffer[i]))
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
    }
    return pcm.buffer
  }

  // ---- WebSocket ----
  function connect(): WebSocket {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${location.host}/ws/live/${meetingId}`
    const socket = new WebSocket(url)
    socket.binaryType = 'arraybuffer'

    socket.onopen = () => {
      connected.value = true
    }

    socket.onmessage = (event: MessageEvent) => {
      if (event.data instanceof ArrayBuffer) return

      try {
        const msg = JSON.parse(event.data)
        switch (msg.type) {
          case 'connected':
            connected.value = true
            break
          case 'transcript_delta':
            transcript.value = [...transcript.value, msg.data as TranscriptSegment]
            break
          case 'summary_update':
            summary.value = msg.data as MeetingSummary
            break
          case 'actions_update':
            actions.value = msg.data as ActionResult
            break
          case 'insights_update':
            insights.value = msg.data as MeetingInsight
            break
          case 'completed':
            isRecording.value = false
            stopTimer()
            break
          case 'error':
            error.value = msg.message
            break
          case 'pong':
            break
        }
      } catch {
        // ignore parse errors
      }
    }

    socket.onclose = () => {
      connected.value = false
      isRecording.value = false
      stopTimer()
    }

    socket.onerror = () => {
      error.value = 'WebSocket 连接失败'
    }

    return socket
  }

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

  // ---- 计时器 ----
  function startTimer(): void {
    const startTime = Date.now()
    timer = setInterval(() => {
      elapsedSeconds.value = Math.floor((Date.now() - startTime) / 1000)
    }, 1000)
  }

  function stopTimer(): void {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

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

  onUnmounted(() => {
    stop()
    if (ws) {
      ws.close()
      ws = null
    }
  })

  return {
    connected,
    transcript,
    summary,
    actions,
    insights,
    elapsedSeconds,
    error,
    isRecording,
    audioSources,
    start,
    stop,
  }
}
