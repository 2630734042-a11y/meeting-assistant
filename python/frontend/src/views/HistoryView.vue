<template>
  <n-card title="历史会议">
    <n-data-table
      :columns="columns"
      :data="meetings"
      :pagination="{ pageSize: 10 }"
      :row-props="(row: any) => ({ style: 'cursor: pointer', onClick: () => router.push(`/report/${row.id}`) })"
      :empty-message="'暂无历史会议记录'"
    />
  </n-card>
</template>

<script setup lang="ts">
import { ref, h } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const meetings = ref<{ id: string; status: string }[]>(
  JSON.parse(localStorage.getItem('recentMeetings') || '[]')
)

const columns = [
  { title: '会议 ID', key: 'id' },
  {
    title: '状态',
    key: 'status',
    render: (row: any) => {
      const statusMap: Record<string, { type: 'default' | 'success' | 'warning' | 'error'; label: string }> = {
        completed: { type: 'success', label: '已完成' },
        transcribing: { type: 'warning', label: '处理中' },
        failed: { type: 'error', label: '失败' },
      }
      const s = statusMap[row.status] || { type: 'default' as const, label: row.status }
      return h('span', {}, s.label)
    },
  },
  {
    title: '操作',
    key: 'action',
    render: (_row: any) => {
      return h('span', {}, '查看详情 →')
    },
  },
]
</script>
