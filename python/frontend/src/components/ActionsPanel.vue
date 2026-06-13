<template>
  <div>
    <n-empty v-if="!actions?.action_items?.length" description="本会议无提取到的待办事项" />

    <n-space v-else vertical size="medium">
      <!-- 审核提示 -->
      <n-alert v-if="!reviewed" type="warning" title="待审核" :bordered="false">
        请逐条审核待办事项，确认后点击底部按钮发送到 Jira 和飞书
      </n-alert>

      <!-- 每条待办 -->
      <n-card v-for="(item, idx) in actions.action_items" :key="idx" :bordered="true"
        :style="{ opacity: item.review_status === 'deleted' ? 0.4 : 1 }">
        <template #header>
          <n-space align="center" justify="space-between">
            <n-tag v-if="item.review_status === 'pending'" type="default">待审核</n-tag>
            <n-tag v-else-if="item.review_status === 'confirmed'" type="success">已确认</n-tag>
            <n-tag v-else-if="item.review_status === 'deleted'" type="error">已删除</n-tag>
            <n-tag v-else-if="item.review_status === 'modified'" type="info">已修改</n-tag>
            <n-text depth="3">#{{ idx + 1 }}</n-text>
          </n-space>
        </template>

        <!-- 编辑模式 -->
        <n-form v-if="editing === idx" label-placement="left" label-width="80px" size="small">
          <n-form-item label="任务"><n-input v-model:value="editForm.task" /></n-form-item>
          <n-form-item label="负责人"><n-input v-model:value="editForm.assignee" /></n-form-item>
          <n-form-item label="截止日期">
            <n-input v-model:value="editForm.deadline" placeholder="YYYY-MM-DD" />
          </n-form-item>
          <n-form-item label="优先级">
            <n-select v-model:value="editForm.priority" :options="priorityOptions" />
          </n-form-item>
          <n-space><n-button size="small" type="primary" @click="saveEdit(idx)">保存修改</n-button>
            <n-button size="small" @click="editing = -1">取消</n-button></n-space>
        </n-form>

        <!-- 展示模式 -->
        <n-descriptions v-else :column="2" size="small" bordered>
          <n-descriptions-item label="任务">{{ item.task }}</n-descriptions-item>
          <n-descriptions-item label="负责人">{{ item.assignee }}</n-descriptions-item>
          <n-descriptions-item label="截止">{{ item.deadline || '未指定' }}</n-descriptions-item>
          <n-descriptions-item label="优先级">
            <n-tag :type="priorityColor(item.priority)">{{ item.priority }}</n-tag>
          </n-descriptions-item>
        </n-descriptions>

        <template #action v-if="!reviewed">
          <n-space>
            <n-button size="small" type="primary" @click="startEdit(idx)">✏️ 编辑</n-button>
            <n-button size="small" type="success" @click="confirmItem(idx)">✅ 确认</n-button>
            <n-button size="small" type="error" @click="deleteItem(idx)">⛔ 删除</n-button>
          </n-space>
        </template>
      </n-card>

      <!-- 底部操作栏 -->
      <n-space v-if="!reviewed" justify="end" align="center">
        <n-popconfirm @positive-click="submitReview" v-if="allDeleted">
          <template #trigger><n-button type="primary" size="large">📤 全部确认并发送</n-button></template>
          所有待办已被删除，将不同步到外部系统。确定继续？
        </n-popconfirm>
        <n-button v-else type="primary" size="large" :loading="submitting" @click="submitReview">
          📤 全部确认并发送
        </n-button>
      </n-space>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import type { ActionResult } from '../shared/types'
import { api } from '../shared/api'

const props = defineProps<{
  actions?: ActionResult
  threadId?: string
  meetingId: string
  reviewed: boolean
}>()
const emit = defineEmits(['updated'])

const editing = ref(-1)
const submitting = ref(false)
const allDeleted = computed(() =>
  props.actions?.action_items?.every(i => i.review_status === 'deleted')
)

const editForm = reactive({ task: '', assignee: '', deadline: '', priority: 'medium' })
const priorityOptions = [
  { label: '低', value: 'low' }, { label: '中', value: 'medium' },
  { label: '高', value: 'high' }, { label: '紧急', value: 'urgent' },
]

function priorityColor(p: string) {
  return { low: 'default', medium: 'warning', high: 'error', urgent: 'error' }[p] || 'default'
}

function startEdit(idx: number) {
  const item = props.actions?.action_items?.[idx]
  if (!item) return
  editing.value = idx
  editForm.task = item.task
  editForm.assignee = item.assignee
  editForm.deadline = item.deadline
  editForm.priority = item.priority
}
function saveEdit(idx: number) {
  const item = props.actions?.action_items?.[idx]
  if (!item) return
  item.task = editForm.task
  item.assignee = editForm.assignee
  item.deadline = editForm.deadline
  item.priority = editForm.priority as any
  item.review_status = 'modified'
  editing.value = -1
}
function confirmItem(idx: number) {
  const item = props.actions?.action_items?.[idx]
  if (item) item.review_status = 'confirmed'
}
function deleteItem(idx: number) {
  const item = props.actions?.action_items?.[idx]
  if (item) item.review_status = 'deleted'
}

async function submitReview() {
  if (!props.actions?.action_items || !props.threadId) return
  submitting.value = true
  try {
    const items = props.actions.action_items.map((item, idx) => ({
      index: idx,
      review_status: item.review_status,
      assignee: item.assignee,
      task: item.task,
      deadline: item.deadline,
      priority: item.priority,
    }))
    await api.reviewActions(props.meetingId, props.threadId, items)
    await api.resumePipeline(props.meetingId, props.threadId)
    // Wait briefly then emit
    setTimeout(() => emit('updated'), 1500)
  } catch (e: any) {
    alert('提交失败: ' + e.message)
  } finally {
    submitting.value = false
  }
}
</script>
