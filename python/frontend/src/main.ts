import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import naive from 'naive-ui'
import App from './App.vue'
import './style.css'

const routes = [
  { path: '/', redirect: '/upload' },
  { path: '/upload', component: () => import('./views/UploadView.vue') },
  { path: '/report/:id', component: () => import('./views/ReportView.vue') },
  { path: '/history', component: () => import('./views/HistoryView.vue') },
]

const router = createRouter({ history: createWebHashHistory(), routes })

const app = createApp(App)
app.use(naive)
app.use(router)
app.mount('#app')
