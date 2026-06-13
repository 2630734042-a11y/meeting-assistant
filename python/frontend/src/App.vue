<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN">
    <n-layout style="min-height: 100vh">
      <n-layout-header bordered>
        <n-menu mode="horizontal" :value="activeMenu" :options="menuOptions"
          @update:value="(v: string) => router.push(v)" />
      </n-layout-header>
      <n-layout-content style="padding: 24px; max-width: 1200px; margin: 0 auto">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { zhCN, dateZhCN } from 'naive-ui'

const router = useRouter()
const route = useRoute()

const menuOptions = [
  { label: '上传', key: '/upload' },
  { label: '历史', key: '/history' },
]

const activeMenu = computed(() => {
  if (route.path.startsWith('/report')) return '/upload' // 报告页不高亮历史
  return route.path
})
</script>
