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

  let ws: WebSocket | null = null
  let audioContext: AudioContext | null = null
  let processor: ScriptProcessorNode | null = null
  let stream: MediaStream | null = null
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

  // ---- 麦克风 ----
  async function startMic(): Promise<void> {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
        },
      })

      audioContext = new AudioContext({ sampleRate: 16000 })
      const source = audioContext.createMediaStreamSource(stream)
      processor = audioContext.createScriptProcessor(4096, 1, 1)

      processor.onaudioprocess = (e: AudioProcessingEvent) => {
        if (!ws || ws.readyState !== WebSocket.OPEN || !isRecording.value) return
        const inputData = e.inputBuffer.getChannelData(0)
        const pcm = float32ToPCM16(inputData)
        ws.send(pcm)
      }

      source.connect(processor)
      processor.connect(audioContext.destination)
    } catch (err: any) {
      if (err.name === 'NotAllowedError') {
        error.value = '麦克风权限被拒绝，请在浏览器设置中允许麦克风访问'
      } else {
        error.value = `麦克风初始化失败: ${err.message}`
      }
      throw err
    }
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

    await startMic()
    isRecording.value = true
    startTimer()
  }

  function stop(): void {
    isRecording.value = false
    stopTimer()

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'stop' }))
    }

    if (processor) {
      processor.disconnect()
      processor = null
    }
    if (audioContext) {
      audioContext.close()
      audioContext = null
    }
    if (stream) {
      stream.getTracks().forEach((t) => t.stop())
      stream = null
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
    start,
    stop,
  }
}
