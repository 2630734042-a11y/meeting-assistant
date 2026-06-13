import type { MeetingReport } from './types'

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  createMeeting: () =>
    request<{ meeting_id: string }>('/api/v1/meeting/start', { method: 'POST' }),

  uploadAudio: (meetingId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch(`/api/v1/meeting/${meetingId}/upload`, { method: 'POST', body: form }).then(r => r.json())
  },

  uploadVideo: (meetingId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch(`/api/v1/meeting/${meetingId}/upload-video`, { method: 'POST', body: form }).then(r => r.json())
  },

  runDemo: (meetingId: string) =>
    request(`/api/v1/meeting/${meetingId}/demo`, { method: 'POST' }),

  getReport: (meetingId: string) =>
    request<MeetingReport>(`/api/v1/meeting/${meetingId}/report`),

  reviewActions: (meetingId: string, threadId: string, items: any[]) =>
    request(`/api/v1/meeting/${meetingId}/actions/review`, {
      method: 'PUT',
      body: JSON.stringify({ thread_id: threadId, items }),
    }),

  resumePipeline: (meetingId: string, threadId: string) =>
    request(`/api/v1/meeting/${meetingId}/resume`, {
      method: 'POST',
      body: JSON.stringify({ thread_id: threadId }),
    }),
}
