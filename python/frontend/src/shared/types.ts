export type MeetingStatus = 'created' | 'transcribing' | 'summarying' |
  'extracting' | 'analyzing' | 'following_up' | 'completed' | 'failed'

export type Priority = 'low' | 'medium' | 'high' | 'urgent'
export type ReviewStatus = 'pending' | 'confirmed' | 'deleted' | 'modified'
export type SentimentType = 'positive' | 'neutral' | 'negative'

export interface TranscriptSegment {
  speaker: string
  text: string
  start: number
  end: number
  confidence: number
}

export interface TranscriptResult {
  meeting_id: string
  segments: TranscriptSegment[]
  language: string
  duration_seconds: number
  full_text: string
}

export interface TopicSummary {
  title: string
  discussion_points: string[]
  participants: string[]
  conclusion: string
}

export interface MeetingSummary {
  title: string
  date: string
  participants: string[]
  topics: TopicSummary[]
  decisions: string[]
  next_steps: string[]
}

export interface ActionItem {
  assignee: string
  task: string
  deadline: string
  priority: Priority
  context: string
  review_status: ReviewStatus
  jira_issue_key: string
  feishu_task_id: string
}

export interface ActionResult {
  meeting_id: string
  action_items: ActionItem[]
  sync_status: { jira: string; feishu: string }
}

export interface SpeakerStats {
  speaker: string
  speaking_duration: number
  speaking_ratio: number
  word_count: number
  segment_count: number
}

export interface MeetingInsight {
  meeting_id: string
  overall_sentiment: SentimentType
  sentiment_score: number
  speaker_stats: SpeakerStats[]
  efficiency_score: number
  keywords: string[]
  highlights: string[]
  suggestions: string[]
}

export interface FollowUpResult {
  meeting_id: string
  summary_sent: boolean
  recipients: string[]
  jira_issues_created: string[]
  feishu_tasks_created: string[]
  reminders_scheduled: number
  report_url: string
}

export interface MeetingReport {
  meeting_id: string
  thread_id?: string
  status: MeetingStatus
  transcript?: TranscriptResult
  summary?: MeetingSummary
  actions?: ActionResult
  insights?: MeetingInsight
  followup?: FollowUpResult
  errors: string[]
}
