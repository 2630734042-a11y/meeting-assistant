<template>
  <div>
    <n-page-header @back="router.back()">
      <template #title>会议报告 - {{ meetingId }}</template>
    </n-page-header>

    <n-spin :show="loading" description="加载中...">
      <n-tabs v-if="report" type="line" animated>
        <n-tab-pane name="transcript" tab="📝 转写">
          <TranscriptPanel :transcript="report.transcript" />
        </n-tab-pane>
        <n-tab-pane name="summary" tab="📋 纪要">
          <SummaryPanel :summary="report.summary" />
        </n-tab-pane>
        <n-tab-pane name="actions" tab="✅ 待办">
          <ActionsPanel :actions="report.actions" :thread-id="report.thread_id"
            :meeting-id="meetingId" :reviewed="report.status === 'completed'"
            @updated="refreshReport" />
        </n-tab-pane>
        <n-tab-pane name="insights" tab="🔍 洞察">
          <InsightsPanel :insights="report.insights" />
        </n-tab-pane>
      </n-tabs>
    </n-spin>

    <n-empty v-if="!report && !loading" description="未找到该会议报告" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../shared/api'
import type { MeetingReport } from '../shared/types'
import TranscriptPanel from '../components/TranscriptPanel.vue'
import SummaryPanel from '../components/SummaryPanel.vue'
import ActionsPanel from '../components/ActionsPanel.vue'
import InsightsPanel from '../components/InsightsPanel.vue'

const route = useRoute()
const meetingId = route.params.id as string
const report = ref<MeetingReport | null>(null)
const loading = ref(true)

async function refreshReport() {
  try {
    report.value = await api.getReport(meetingId)
  } catch (e) { console.error(e) }
}

onMounted(async () => {
  await refreshReport()
  loading.value = false
  // 如果不是 completed 且不是 failed，每秒轮询
  if (report.value?.status !== 'completed' && report.value?.status !== 'failed') {
    const timer = setInterval(async () => {
      await refreshReport()
      if (report.value?.status === 'completed' || report.value?.status === 'failed') {
        clearInterval(timer)
      }
    }, 2000)
    // cleanup on unmount
    ;(window as any).__reportTimer = timer
  }
})
</script>
