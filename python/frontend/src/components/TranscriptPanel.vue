<template>
  <div>
    <n-empty v-if="!transcript?.segments?.length" description="暂无转写结果" />
    <n-timeline v-else>
      <n-timeline-item v-for="(seg, i) in transcript.segments" :key="i"
        :title="seg.speaker"
        :time="formatTime(seg.start) + ' - ' + formatTime(seg.end)">
        <n-tag :type="speakerColor(seg.speaker)" size="small">{{ seg.speaker }}</n-tag>
        <p style="margin-top: 4px">{{ seg.text }}</p>
      </n-timeline-item>
    </n-timeline>
  </div>
</template>

<script setup lang="ts">
import type { TranscriptResult } from '../shared/types'
defineProps<{ transcript?: TranscriptResult }>()

const speakerColors = ['primary', 'success', 'warning', 'info', 'error'] as const
function speakerColor(speaker: string) {
  return speakerColors[speaker.charCodeAt(0) % speakerColors.length]
}
function formatTime(s: number) {
  return new Date(s * 1000).toISOString().slice(14, 19)
}
</script>
