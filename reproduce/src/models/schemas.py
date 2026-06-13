"""
Pydantic 数据模型 —— 系统中所有 Agent 之间的"共同语言"

设计原则:
- Pydantic BaseModel: 需序列化的数据对象 (JSON 输出给前端/API)
- Python Enum(str): 类型安全 + 可直接字符串比较
- TypedDict: LangGraph 框架要求的状态类型
- 可选字段用默认值: 表达 "Pipeline 逐步填充" 的语义
"""
from __future__ import annotations

from enum import Enum
from typing import Any, TypedDict

from pydantic import BaseModel, Field


# ============================================================
# 一、枚举类型
# ============================================================

# TODO: 定义 MeetingStatus 枚举 (继承 str, Enum)
#   - 值: created, recording, transcribing, processing, completed, failed
#   - 用途: 追踪会议从创建到完成/失败的生命周期
class MeetingStatus(str, Enum):
    """会议生命周期状态 —— 继承 str 使得可直接与字符串比较"""
    CREATED = "created"            # 已创建，等待录制
    RECORDING = "recording"        # 正在录制音频
    TRANSCRIBING = "transcribing"  # 正在语音转文字
    PROCESSING = "processing"      # 正在执行 Agent Pipeline
    COMPLETED = "completed"        # 处理完成
    FAILED = "failed"              # 处理失败
    
# TODO: 定义 Priority 枚举 (继承 str, Enum)
#   - 值: low, medium, high, urgent
#   - 用途: 任务优先级，继承 str 使得 Priority.HIGH == "high" 为 True
class Priority(str,Enum):
    LOW = "low"
    MEDIUM= "medium"
    HIGH = "high"
    URGENT = "urgent"
# TODO: 定义 SentimentType 枚举 (继承 str, Enum)
#   - 值: positive, neutral, negative
#   - 用途: 会议整体情绪分析结果
class SentimentType(str,Enum):
    POSITIVE="positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
# ============================================================
# 二、转写模型 (TranscriptionAgent 输出)
# ============================================================

# TODO: 定义 TranscriptSegment 类 (继承 BaseModel)
#   单个语音片段 —— 一次发言
#   字段: speaker(str="Unknown"), text(str=""), start(float=0.0), end(float=0.0), confidence(float=0.0)
class TranscriptSegment(BaseModel):
    """单个语音片段 —— 一次发言"""
    speaker: str = "Unknown"     # 说话人
    text: str = ""               # 转写文本
    start: float = 0.0           # 开始时间（秒）
    end: float = 0.0             # 结束时间（秒）
    confidence: float = 0.0      # 转写置信度 0-1
# TODO: 定义 TranscriptResult 类 (继承 BaseModel)
#   完整转写结果 —— TranscriptionAgent 输出
#   字段: meeting_id(str=""), segments(list[TranscriptSegment]=[]), language(str="zh"), duration_seconds(float=0.0), full_text(str="")
class TranscriptResult(BaseModel):
    meeting_id: str=""
    segments: list[TranscriptSegment]=[]
    language: str="zh"
    duration_seconds: float=0.0
    full_text: str=""
# ============================================================
# 三、摘要模型 (SummaryAgent 输出)
# ============================================================

# TODO: 定义 TopicSummary 类 (继承 BaseModel)
#   单个议题摘要
#   字段: title(str=""), discussion_points(list[str]=[]), participants(list[str]=[]), conclusion(str="")
class TopicSummary(BaseModel):
    title: str=""
    discussion_points:list[str]=[]
    participants:list[str]=[]
    conclusion: str=""
# TODO: 定义 MeetingSummary 类 (继承 BaseModel)
#   结构化会议纪要 —— SummaryAgent 输出
#   字段: title(str="会议纪要"), date(str=""), participants(list[str]=[]), topics(list[TopicSummary]=[]), decisions(list[str]=[]), next_steps(list[str]=[])
class MeetingSummary(BaseModel):
    """结构化会议纪要 —— SummaryAgent 输出"""
    title: str = "会议纪要"
    date: str = ""
    participants: list[str] = []
    topics: list[TopicSummary] = []
    decisions: list[str] = []            # 会议做出的决策
    next_steps: list[str] = []           # 下一步行动计划


# ============================================================
# 四、待办模型 (ActionAgent 输出)
# ============================================================

# TODO: 定义 ActionItem 类 (继承 BaseModel)
#   单个待办/行动项
#   字段: assignee(str="未指定"), task(str=""), deadline(str=""), priority(Priority=Priority.MEDIUM), context(str=""), jira_issue_key(str=""), feishu_task_id(str="")
class ActionItem(BaseModel):
    """单个待办/行动项"""
    assignee: str = "未指定"                 # 负责人
    task: str = ""                          # 任务描述
    deadline: str = ""                      # 截止日期 YYYY-MM-DD
    priority: Priority = Priority.MEDIUM    # 优先级
    context: str = ""                       # 任务背景说明
    jira_issue_key: str = ""               # Jira 同步后回填
    feishu_task_id: str = ""               # 飞书同步后回填

# TODO: 定义 ActionResult 类 (继承 BaseModel)
#   待办处理结果 —— ActionAgent 输出
#   字段: meeting_id(str=""), action_items(list[ActionItem]=[]), sync_status(dict[str,str]={})
class ActionResult(BaseModel):
    """待办处理结果 —— ActionAgent 输出"""
    meeting_id: str = ""
    action_items: list[ActionItem] = []
    sync_status: dict[str, str] = {}        # {"jira": "enabled", "feishu": "disabled"}


# ============================================================
# 五、洞察模型 (InsightAgent 输出)
# ============================================================

# TODO: 定义 SpeakerStats 类 (继承 BaseModel)
#   单个说话人统计 —— 规则引擎计算
#   字段: speaker(str=""), speaking_duration(float=0.0), speaking_ratio(float=0.0), word_count(int=0), segment_count(int=0)
class SpeakerStats(BaseModel):
    """单个说话人统计 —— 由规则引擎计算，不依赖 LLM"""
    speaker: str = ""
    speaking_duration: float = 0.0          # 发言总时长（秒）
    speaking_ratio: float = 0.0             # 发言占比 0-1
    word_count: int = 0                     # 总字数
    segment_count: int = 0                  # 发言次数

# TODO: 定义 MeetingInsight 类 (继承 BaseModel)
#   会议洞察 —— InsightAgent 输出
#   字段: meeting_id(str=""), overall_sentiment(SentimentType=SentimentType.NEUTRAL), sentiment_score(float=0.5), speaker_stats(list[SpeakerStats]=[]), efficiency_score(float=5.0), keywords(list[str]=[]), highlights(list[str]=[]), suggestions(list[str]=[])
class MeetingInsight(BaseModel):
    """会议洞察 —— InsightAgent 输出"""
    meeting_id: str = ""
    overall_sentiment: SentimentType = SentimentType.NEUTRAL
    sentiment_score: float = 0.5
    speaker_stats: list[SpeakerStats] = []
    efficiency_score: float = 5.0           # 效率评分 0-10
    keywords: list[str] = []
    highlights: list[str] = []              # 会议亮点
    suggestions: list[str] = []             # 改进建议


# ============================================================
# 六、跟进模型 (FollowUpAgent 输出)
# ============================================================

# TODO: 定义 FollowUpResult 类 (继承 BaseModel)
#   跟进结果 —— FollowUpAgent 输出（Pipeline 最后一个节点）
#   字段: meeting_id(str=""), summary_sent(bool=False), recipients(list[str]=[]), jira_issues_created(list[str]=[]), feishu_tasks_created(list[str]=[]), reminders_scheduled(int=0), report_url(str="")
class FollowUpResult(BaseModel):
    """跟进结果 —— FollowUpAgent 输出（Pipeline 最后一个节点）"""
    meeting_id: str = ""
    summary_sent: bool = False                 # 纪要是否已发送
    recipients: list[str] = []                 # 接收人列表
    jira_issues_created: list[str] = []        # 已创建的 Jira Issue Key
    feishu_tasks_created: list[str] = []       # 已创建的飞书任务 ID
    reminders_scheduled: int = 0               # 已设置的提醒数量
    report_url: str = ""                       # 报告访问链接


# ============================================================
# 七、LangGraph 状态 (TypedDict —— 框架要求)
# ============================================================

class MeetingState(TypedDict, total=False):
    """
    LangGraph 共享状态

    为什么是 TypedDict 而不是 Pydantic Model？
    → LangGraph 内置基于 dict key 的状态合并 reducer，Pydantic 与之冲突。

    并行安全: Summary/Action/Insight 写入不同 key，不会冲突。
    """
    meeting_id: str
    status: str
    audio_data: bytes

    # TranscriptionAgent 输出
    transcript: Any       # TranscriptResult
    transcript_text: str

    # 并行 Agent 输出（写入不同 key，互不冲突）
    summary: Any          # MeetingSummary
    actions: Any          # ActionResult
    insights: Any         # MeetingInsight

    # FollowUpAgent 输出
    followup: Any         # FollowUpResult

    # 错误收集（所有 Agent 均可追加）
    errors: list[str]


# ============================================================
# 八、工厂函数
# ============================================================

def create_initial_state(
    meeting_id: str,
    audio_data: bytes = b"",
) -> MeetingState:
    """创建 Pipeline 的初始状态 —— 集中管理默认值，避免手写 dict"""
    return MeetingState(
        meeting_id=meeting_id,
        status=MeetingStatus.CREATED.value,
        audio_data=audio_data,
        transcript=None,
        transcript_text="",
        summary=None,
        actions=None,
        insights=None,
        followup=None,
        errors=[],
    )
