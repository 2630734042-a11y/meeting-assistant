<template>
  <div class="live-container">
    <!-- 顶部状态栏 -->
    <n-card size="small" :bordered="false" style="margin-bottom: 12px">
      <n-space align="center" justify="space-between">
        <n-space align="center">
          <n-tag :type="isRecording ? 'error' : 'default'" round>
            {{ isRecording ? '🔴 会议进行中' : '⏸ 已停止' }}
          </n-tag>
          <n-text depth="2">
            {{ formatTime(elapsedSeconds) }}
          </n-text>
          <n-text v-if="transcript.length" depth="3">
            · {{ transcript.length }} 句 · {{ speakerCount }} 人发言
          </n-text>
        </n-space>
        <n-space v-if="!isRecording && transcript.length">
          <n-button type="primary" size="small" @click="$router.push('/history')">
            查看历史记录
          </n-button>
        </n-space>
      </n-space>
    </n-card>

    <!-- 错误提示 -->
    <n-alert v-if="error" type="error" :title="error" closable @close="error = null"
      style="margin-bottom: 12px" />

    <!-- 主内容：左右分栏 -->
    <n-split direction="horizontal" :default-size="0.55" :min="0.3" :max="0.7"
      style="height: calc(100vh - 240px)">
      <template #1>
        <n-card title="📝 实时转写" size="small" :bordered="false" style="height: 100%">
          <div class="transcript-stream" ref="transcriptEl">
            <div v-if="!transcript.length && isRecording" class="transcript-waiting">
              <n-text depth="3">等待识别结果...</n-text>
            </div>
            <div v-for="(seg, idx) in transcript" :key="idx" class="transcript-line"
              :class="{ 'transcript-new': idx === transcript.length - 1 && isRecording }">
              <n-tag :bordered="false" size="tiny"
                :style="{ background: speakerColor(seg.speaker) }">
                {{ seg.speaker }}
              </n-tag>
              <span class="transcript-time">{{ formatTimestamp(seg.start) }}</span>
              <span class="transcript-text">{{ seg.text }}</span>
            </div>
            <div v-if="isRecording" class="transcript-cursor">▊</div>
          </div>
        </n-card>
      </template>
      <template #2>
        <n-scrollbar style="height: 100%">
          <n-space vertical size="medium">
            <n-card title="📋 实时摘要" size="small">
              <SummaryPanel :summary="summary || undefined" />
            </n-card>

            <n-card title="📌 待办事项" size="small">
              <ActionsPanel
                v-if="actions"
                :actions="actions"
                :meeting-id="meetingId"
                :reviewed="true"
              />
              <n-empty v-else description="暂无待办" size="small" />
            </n-card>

            <n-card title="💡 会议洞察" size="small">
              <InsightsPanel :insights="insights || undefined" />
            </n-card>

            <n-text depth="3" style="text-align: center; display: block; font-size: 12px">
              {{ insights ? `✅ 分析进行中` : '⏳ 等待首次分析...' }}
            </n-text>
          </n-space>
        </n-scrollbar>
      </template>
    </n-split>

    <!-- 底部控制栏 -->
    <n-card size="small" :bordered="false" style="margin-top: 12px">
      <n-space justify="center" align="center">
        <n-button
          v-if="!isRecording"
          type="primary"
          size="large"
          @click="startMeeting"
          :loading="connecting"
        >
          🎙 开始会议
        </n-button>
        <n-button
          v-else
          type="error"
          size="large"
          @click="stopMeeting"
        >
          ⏹ 结束会议
        </n-button>
      </n-space>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useLiveSession } from '../composables/useLiveSession'
import SummaryPanel from '../components/SummaryPanel.vue'
import ActionsPanel from '../components/ActionsPanel.vue'
import InsightsPanel from '../components/InsightsPanel.vue'

const route = useRoute()
const meetingId = (route.params.meetingId as string) || `live-${Date.now()}`

const {
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
} = useLiveSession(meetingId)

const connecting = ref(false)
const transcriptEl = ref<HTMLElement | null>(null)

const speakerCount = computed(() => {
  const names = new Set<string>()
  transcript.value.forEach((s) => names.add(s.speaker))
  return names.size
})

const speakerColors = [
  'rgba(32, 128, 240, 0.15)', 'rgba(24, 160, 88, 0.15)',
  'rgba(240, 160, 32, 0.15)', 'rgba(208, 48, 80, 0.15)',
  'rgba(124, 58, 237, 0.15)',
]
function speakerColor(name: string): string {
  return speakerColors[name.charCodeAt(0) % speakerColors.length]
}

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}

function formatTimestamp(s: number): string {
  const min = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${min.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`
}

watch(
  () => transcript.value.length,
  async () => {
    await nextTick()
    if (transcriptEl.value) {
      transcriptEl.value.scrollTop = transcriptEl.value.scrollHeight
    }
  }
)

async function startMeeting() {
  connecting.value = true
  try {
    await start('实时会议')
  } catch (e: any) {
    error.value = e.message || '启动失败'
  } finally {
    connecting.value = false
  }
}

function stopMeeting() {
  stop()
}
</script>

<style scoped>
.live-container {
  padding: 12px;
  max-width: 1400px;
  margin: 0 auto;
}

.transcript-stream {
  height: 100%;
  overflow-y: auto;
  padding: 8px;
}

.transcript-line {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 4px 8px;
  margin-bottom: 2px;
  border-radius: 4px;
  font-size: 14px;
  line-height: 1.6;
}

.transcript-new {
  animation: fadeIn 0.3s ease-in;
}

@keyframes fadeIn {
  from { background: rgba(32, 128, 240, 0.08); }
  to   { background: transparent; }
}

.transcript-time {
  color: #999;
  font-size: 11px;
  font-family: monospace;
  min-width: 45px;
}

.transcript-text {
  flex: 1;
}

.transcript-cursor {
  color: #999;
  font-size: 12px;
  animation: blink 1s step-end infinite;
}

@keyframes blink {
  50% { opacity: 0; }
}

.transcript-waiting {
  text-align: center;
  padding: 40px;
}
</style>
