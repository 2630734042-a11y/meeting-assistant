"""
多Agent智能会议助手 - 核心数据模型

包含:
- 枚举类型（MeetingStatus, Priority, SentimentType）
- 转写相关模型（TranscriptSegment, TranscriptResult）
- 摘要相关模型（TopicSummary, MeetingSummary）
- 待办相关模型（ActionItem, ActionResult）
- 洞察相关模型（SpeakerStats, MeetingInsight）
- 跟进相关模型（FollowUpResult）
- 状态工厂函数（create_initial_state）

所有模型继承 pydantic BaseModel，支持序列化（.model_dump()）。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ============================================================
# 枚举类型
# ============================================================


class MeetingStatus(str, Enum):
    """会议处理状态枚举

    在 LangGraph Pipeline 中流转:
    CREATED → TRANSCRIBING → [SUMMARYING/EXTRACTING/ANALYZING] → FOLLOWING_UP → COMPLETED
    """

    CREATED = "created"
    TRANSCRIBING = "transcribing"
    SUMMARYING = "summarying"
    EXTRACTING = "extracting"
    ANALYZING = "analyzing"
    FOLLOWING_UP = "following_up"
    COMPLETED = "completed"
    FAILED = "failed"


class Priority(str, Enum):
    """待办优先级枚举"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class SentimentType(str, Enum):
    """会议情绪类型枚举"""

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


# ============================================================
# 转写 (Transcription) 模型
# ============================================================


class TranscriptSegment(BaseModel):
    """单条转写片段

    由 TranscriptionAgent 输出，包含说话人、文本、时间戳和置信度。
    """

    speaker: str = Field(default="Unknown", description="说话人标识")
    text: str = Field(default="", description="转写文本内容")
    start: float = Field(default=0.0, description="开始时间（秒）")
    end: float = Field(default=0.0, description="结束时间（秒）")
    confidence: float = Field(default=0.0, description="置信度 0-1")


class TranscriptResult(BaseModel):
    """完整转写结果

    TranscriptionAgent 的主要输出，供 Summary / Action / Insight Agent 使用。
    """

    meeting_id: str = Field(default="", description="会议ID")
    segments: list[TranscriptSegment] = Field(
        default_factory=list, description="转写片段列表"
    )
    language: str = Field(default="zh", description="识别语言")
    duration_seconds: float = Field(default=0.0, description="音频总时长（秒）")
    full_text: str = Field(default="", description="纯文本全文（无时间戳）")


# ============================================================
# 摘要 (Summary) 模型
# ============================================================


class TopicSummary(BaseModel):
    """单个议题摘要"""

    title: str = Field(default="", description="议题名称")
    discussion_points: list[str] = Field(default_factory=list, description="讨论要点")
    participants: list[str] = Field(default_factory=list, description="参与人")
    conclusion: str = Field(default="", description="该议题结论")


class MeetingSummary(BaseModel):
    """会议纪要

    SummaryAgent 的主要输出，结构化会议纪要。
    """

    title: str = Field(default="会议纪要", description="会议主题")
    date: str = Field(default="", description="会议日期")
    participants: list[str] = Field(default_factory=list, description="参会人列表")
    topics: list[TopicSummary] = Field(default_factory=list, description="议题列表")
    decisions: list[str] = Field(default_factory=list, description="会议决策")
    next_steps: list[str] = Field(default_factory=list, description="下一步计划")


# ============================================================
# 待办 (Action) 模型
# ============================================================


class ActionItem(BaseModel):
    """单条待办/行动项

    ActionAgent 提取并同步到 Jira 和飞书后填充 jira_issue_key / feishu_task_id。
    """

    assignee: str = Field(default="未指定", description="负责人")
    task: str = Field(default="", description="任务描述")
    deadline: str = Field(default="", description="截止日期 YYYY-MM-DD")
    priority: Priority = Field(default=Priority.MEDIUM, description="优先级")
    context: str = Field(default="", description="任务背景/上下文")

    # 同步状态 — 由 _sync_to_external 填充
    jira_issue_key: str = Field(default="", description="关联的 Jira Issue Key")
    feishu_task_id: str = Field(default="", description="关联的飞书任务 ID")


class ActionResult(BaseModel):
    """待办提取结果

    ActionAgent 的主要输出，包含提取的行动项和同步状态。
    """

    meeting_id: str = Field(default="", description="会议ID")
    action_items: list[ActionItem] = Field(default_factory=list, description="行动项列表")
    sync_status: dict[str, str] = Field(
        default_factory=lambda: {"jira": "disabled", "feishu": "disabled"},
        description="同步状态",
    )


# ============================================================
# 洞察 (Insight) 模型
# ============================================================


class SpeakerStats(BaseModel):
    """单个说话人的发言统计

    由 InsightAgent 的规则引擎计算（纯确定性逻辑，不依赖 LLM）。
    """

    speaker: str = Field(default="", description="说话人")
    speaking_duration: float = Field(default=0.0, description="发言总时长（秒）")
    speaking_ratio: float = Field(default=0.0, description="发言占比 0-1")
    word_count: int = Field(default=0, description="总字数")
    segment_count: int = Field(default=0, description="发言次数")


class MeetingInsight(BaseModel):
    """会议洞察

    InsightAgent 的主要输出，综合规则引擎和 LLM 分析结果。
    """

    meeting_id: str = Field(default="", description="会议ID")
    overall_sentiment: SentimentType = Field(
        default=SentimentType.NEUTRAL, description="整体情绪"
    )
    sentiment_score: float = Field(default=0.5, description="情绪得分 0-1")
    speaker_stats: list[SpeakerStats] = Field(
        default_factory=list, description="发言统计"
    )
    efficiency_score: float = Field(default=0.0, description="效率评分 0-10")
    keywords: list[str] = Field(default_factory=list, description="关键词")
    highlights: list[str] = Field(default_factory=list, description="会议亮点")
    suggestions: list[str] = Field(default_factory=list, description="改进建议")


# ============================================================
# 跟进 (Follow-up) 模型
# ============================================================


class FollowUpResult(BaseModel):
    """跟进结果

    FollowUpAgent 的主要输出，汇总所有会后操作的状态。
    """

    meeting_id: str = Field(default="", description="会议ID")
    summary_sent: bool = Field(default=False, description="纪要是否已发送")
    recipients: list[str] = Field(default_factory=list, description="接收人列表")
    jira_issues_created: list[str] = Field(
        default_factory=list, description="已创建的 Jira Issue Key 列表"
    )
    feishu_tasks_created: list[str] = Field(
        default_factory=list, description="已创建的飞书任务 ID 列表"
    )
    reminders_scheduled: int = Field(default=0, description="已设置的提醒数量")
    report_url: str = Field(default="", description="完整报告路径/URL")


# ============================================================
# 状态工厂函数
# ============================================================


def create_initial_state(
    meeting_id: str,
    audio_data: bytes = b"",
) -> dict[str, Any]:
    """创建 LangGraph 初始状态字典

    在 run_meeting_pipeline() 中调用，生成 Graph 执行的起始状态。
    所有 Agent 按需读取和更新这个字典。

    Args:
        meeting_id: 会议唯一标识
        audio_data: 原始音频数据（为空时使用 demo 数据）

    Returns:
        初始 MeetingState 字典
    """
    return {
        "meeting_id": meeting_id,
        "status": MeetingStatus.CREATED,
        "audio_data": audio_data,
        "transcript": None,
        "transcript_text": "",
        "summary": None,
        "actions": None,
        "insights": None,
        "followup": None,
        "errors": [],
    }
