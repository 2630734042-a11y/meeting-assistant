<template>
  <n-card title="📋 历史会议">
    <n-data-table
      :columns="columns"
      :data="meetings"
      :loading="loading"
      :pagination="pagination"
      @update:page="onPageChange"
      :row-props="(row: any) => ({ style: 'cursor: pointer', onClick: () => goToReport(row.id) })"
    >
      <template #empty>
        <n-empty description="暂无历史会议记录" />
      </template>
    </n-data-table>
  </n-card>
</template>

<script setup lang="ts">
import { ref, h, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NPopconfirm, NSpace, NTag, NEmpty } from 'naive-ui'
import { api } from '../shared/api'

const router = useRouter()

const loading = ref(false)
const meetings = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20

const pagination = ref({
  page: 1,
  pageSize: 20,
  showSizePicker: false,
  itemCount: 0,
  prefix: () => `共 ${total.value} 条`,
})

async function fetchMeetings() {
  loading.value = true
  try {
    const res = await api.listMeetings(page.value, pageSize)
    meetings.value = res.items
    total.value = res.total
    pagination.value.itemCount = res.total
    pagination.value.page = page.value
  } catch (e) {
    console.error('Failed to fetch meetings:', e)
  } finally {
    loading.value = false
  }
}

function onPageChange(p: number) {
  page.value = p
  fetchMeetings()
}

function goToReport(id: string) {
  router.push(`/report/${id}`)
}

async function handleDelete(id: string) {
  try {
    await api.deleteMeeting(id)
    fetchMeetings()
  } catch (e) {
    console.error('Failed to delete meeting:', e)
  }
}

const statusMap: Record<string, { type: 'default' | 'success' | 'warning' | 'error'; label: string }> = {
  completed: { type: 'success', label: '已完成' },
  created: { type: 'default', label: '待处理' },
  transcribing: { type: 'warning', label: '处理中' },
  failed: { type: 'error', label: '失败' },
}

const columns = [
  {
    title: '会议',
    key: 'title',
    render: (row: any) => row.title || row.id,
  },
  {
    title: '来源',
    key: 'source',
    width: 80,
    render: (row: any) =>
      row.source === 'live'
        ? h(NTag, { size: 'small', bordered: false }, { default: () => '🎙 实时' })
        : h(NTag, { size: 'small', bordered: false }, { default: () => '📁 上传' }),
  },
  {
    title: '状态',
    key: 'status',
    width: 100,
    render: (row: any) => {
      const s = statusMap[row.status] || { type: 'default' as const, label: row.status }
      return h(NTag, { type: s.type, size: 'small' }, { default: () => s.label })
    },
  },
  {
    title: '时长',
    key: 'duration_seconds',
    width: 80,
    render: (row: any) => {
      const m = Math.floor((row.duration_seconds || 0) / 60)
      const s = Math.floor((row.duration_seconds || 0) % 60)
      return `${m}:${s.toString().padStart(2, '0')}`
    },
  },
  {
    title: '句数',
    key: 'segment_count',
    width: 60,
  },
  {
    title: '创建时间',
    key: 'created_at',
    width: 140,
    render: (row: any) => {
      if (!row.created_at) return '-'
      const d = new Date(row.created_at)
      return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
    },
  },
  {
    title: '操作',
    key: 'action',
    width: 140,
    render: (row: any) => {
      return h(NSpace, { size: 'small' }, () => [
        h(
          NButton,
          { size: 'small', onClick: (e: Event) => { e.stopPropagation(); goToReport(row.id) } },
          { default: () => '查看' }
        ),
        h(
          NPopconfirm,
          { onPositiveClick: (e: Event) => { e.stopPropagation(); handleDelete(row.id) } },
          {
            trigger: () =>
              h(
                NButton,
                { size: 'small', type: 'error', onClick: (e: Event) => e.stopPropagation() },
                { default: () => '删除' }
              ),
            default: () => '确定删除此会议？',
          }
        ),
      ])
    },
  },
]

onMounted(fetchMeetings)
</script>
