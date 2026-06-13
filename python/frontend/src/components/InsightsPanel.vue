<template>
  <div>
    <n-empty v-if="!insights" description="暂无洞察数据" />
    <n-space v-else vertical>
      <n-card title="整体评估" size="small">
        <n-descriptions :column="3" size="small">
          <n-descriptions-item label="整体氛围">{{ insights.overall_sentiment }}</n-descriptions-item>
          <n-descriptions-item label="情绪得分">{{ (insights.sentiment_score*100).toFixed(0) }}%</n-descriptions-item>
          <n-descriptions-item label="效率评分">{{ insights.efficiency_score }}/10</n-descriptions-item>
        </n-descriptions>
      </n-card>

      <n-card v-if="insights.speaker_stats?.length" title="发言统计" size="small">
        <div v-for="s in insights.speaker_stats" :key="s.speaker" style="margin-bottom: 8px">
          <n-space justify="space-between">
            <n-text>{{ s.speaker }}</n-text>
            <n-text depth="3">{{ (s.speaking_ratio * 100).toFixed(0) }}% ({{ s.speaking_duration }}s, {{ s.segment_count }}次)</n-text>
          </n-space>
          <n-progress type="line" :percentage="Math.round(s.speaking_ratio * 100)"
            :height="12" :color="progressColor(s.speaker)" />
        </div>
      </n-card>

      <n-card v-if="insights.keywords?.length" title="关键词" size="small">
        <n-space><n-tag v-for="k in insights.keywords" :key="k">{{ k }}</n-tag></n-space>
      </n-card>

      <n-card v-if="insights.highlights?.length" title="会议亮点" size="small">
        <n-ul><n-li v-for="h in insights.highlights" :key="h">{{ h }}</n-li></n-ul>
      </n-card>

      <n-card v-if="insights.suggestions?.length" title="改进建议" size="small">
        <n-ul><n-li v-for="s in insights.suggestions" :key="s">{{ s }}</n-li></n-ul>
      </n-card>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import type { MeetingInsight } from '../shared/types'
defineProps<{ insights?: MeetingInsight }>()
const progressColors = ['#2080f0', '#18a058', '#f0a020', '#d03050', '#7c3aed']
function progressColor(speaker: string) {
  return progressColors[speaker.charCodeAt(0) % progressColors.length]
}
</script>
