<template>
  <div>
    <n-empty v-if="!summary" description="暂无会议纪要" />
    <n-space v-else vertical>
      <n-h2>{{ summary.title }}</n-h2>
      <n-descriptions v-if="summary.participants.length" :column="1" bordered size="small">
        <n-descriptions-item label="参会人">{{ summary.participants.join(', ') }}</n-descriptions-item>
      </n-descriptions>
      <n-card v-for="(topic, i) in summary.topics" :key="i" :title="`议题${i+1}: ${topic.title}`" size="small">
        <n-ul><n-li v-for="p in topic.discussion_points" :key="p">{{ p }}</n-li></n-ul>
        <n-tag v-if="topic.conclusion" type="success">结论: {{ topic.conclusion }}</n-tag>
      </n-card>
      <n-card v-if="summary.decisions.length" title="会议决策" size="small">
        <n-ul><n-li v-for="d in summary.decisions" :key="d">{{ d }}</n-li></n-ul>
      </n-card>
      <n-card v-if="summary.next_steps.length" title="下一步计划" size="small">
        <n-ul><n-li v-for="s in summary.next_steps" :key="s">{{ s }}</n-li></n-ul>
      </n-card>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import type { MeetingSummary } from '../shared/types'
defineProps<{ summary?: MeetingSummary }>()
</script>
