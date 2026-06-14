<template>
  <n-space vertical size="large">
    <n-card title="上传会议文件">
      <n-upload
        :accept="'.mp4,.mkv,.webm,.avi,.mov,.flv,.wmv,.wav,.mp3,.m4a,.flac'"
        :multiple="false"
        :custom-request="handleUpload"
        :disabled="uploading"
      >
        <n-upload-dragger>
          <n-icon size="48" :component="CloudUploadOutline" />
          <p style="margin-top: 12px">拖拽或点击上传音频/视频文件</p>
          <n-text depth="3" style="font-size: 12px">
            支持 MP4/MKV/WebM/AVI/MOV/FLV/WMV/WAV/MP3/M4A/FLAC
          </n-text>
        </n-upload-dragger>
      </n-upload>
      <n-space justify="center" style="margin-top: 12px">
        <n-button @click="router.push('/live/' + generateLiveId())" type="primary">
          🎙 实时会议
        </n-button>
        <n-button @click="runDemoMode" :loading="uploading" type="tertiary">
          或运行演示模式（无需文件）
        </n-button>
      </n-space>
    </n-card>

    <!-- 处理状态 -->
    <n-card v-if="processing" title="处理中">
      <n-steps :current="stage" status="process">
        <n-step title="上传完成" />
        <n-step title="提取音频" />
        <n-step title="智能分析" />
      </n-steps>
    </n-card>

    <!-- 最近会议 -->
    <n-card v-if="!processing && recentMeetings.length" title="最近会议">
      <n-space vertical>
        <n-card v-for="m in recentMeetings" :key="m.id" size="small" hoverable
          @click="router.push(`/report/${m.id}`)">
          <n-space justify="space-between">
            <span>{{ m.id }}</span>
            <n-tag :type="m.status === 'completed' ? 'success' : 'warning'">{{ m.status }}</n-tag>
          </n-space>
        </n-card>
      </n-space>
    </n-card>
  </n-space>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { CloudUploadOutline } from '@vicons/ionicons5'
import { api } from '../shared/api'
import type { UploadCustomRequestOptions } from 'naive-ui'

const router = useRouter()
const uploading = ref(false)
const processing = ref(false)
const stage = ref(0)
const recentMeetings = ref<{ id: string; status: string }[]>(
  JSON.parse(localStorage.getItem('recentMeetings') || '[]')
)

function saveToRecent(id: string, status: string) {
  const list: { id: string; status: string }[] = JSON.parse(
    localStorage.getItem('recentMeetings') || '[]'
  )
  list.unshift({ id, status })
  if (list.length > 5) list.pop()
  localStorage.setItem('recentMeetings', JSON.stringify(list))
  recentMeetings.value = list
}

async function handleUpload({ file }: UploadCustomRequestOptions) {
  uploading.value = true
  processing.value = true
  stage.value = 0

  const meetingResp = await api.createMeeting()
  const meetingId = meetingResp.meeting_id
  stage.value = 1

  const fileName = (file as File).name || 'unknown'
  const isVideo = /\.(mp4|mkv|webm|avi|mov|flv|wmv)$/i.test(fileName)
  const resp = isVideo
    ? await api.uploadVideo(meetingId, file as File)
    : await api.uploadAudio(meetingId, file as File)

  if (resp.status === 'failed') {
    alert('处理失败: ' + (resp.errors?.join(', ') || '未知错误'))
    uploading.value = false
    processing.value = false
    return
  }

  stage.value = 2
  saveToRecent(meetingId, resp.status || 'processing')
  uploading.value = false
  processing.value = false
  router.push(`/report/${meetingId}`)
}

function generateLiveId(): string {
  return `live-${Date.now()}`
}

async function runDemoMode() {
  uploading.value = true
  processing.value = true
  const meetingResp = await api.createMeeting()
  const resp: any = await api.runDemo(meetingResp.meeting_id)
  saveToRecent(meetingResp.meeting_id, resp.status || 'completed')
  uploading.value = false
  processing.value = false
  router.push(`/report/${meetingResp.meeting_id}`)
}
</script>
