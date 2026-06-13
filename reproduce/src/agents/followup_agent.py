"""
Follow-up Agent（跟进Agent）—— Pipeline 最后一个节点 (Fan-in 汇聚)

职责:
- 等待 Summary/Action/Insight 三个并行 Agent 全部完成
- 汇聚结果，生成完整的 Markdown 会议报告
- 推送到飞书群 (FeishuClient.send_meeting_summary)
- 统计 Jira/飞书的同步结果
- 最终设置 state["status"] = MeetingStatus.COMPLETED

你需要:
1. 导入: datetime, loguru.logger
2. 从 ..integrations.feishu_client 导入 FeishuClient
3. 从 ..models.schemas 导入 ActionResult, FollowUpResult, MeetingInsight, MeetingStatus, MeetingSummary
"""
from __future__ import annotations

# TODO: 导入 datetime
# TODO: 从 typing 导入 Any
# TODO: 从 loguru 导入 logger
# TODO: 从 ..integrations.feishu_client 导入 FeishuClient
# TODO: 从 ..models.schemas 导入 ActionResult, FollowUpResult, MeetingInsight, MeetingStatus, MeetingSummary


# TODO: 定义 FollowUpAgent 类
#   class FollowUpAgent:
#       def __init__(self, feishu_client=None):
#           """feishu_client 默认 FeishuClient()"""
#
#       async def process(self, state: dict) -> dict:
#           """LangGraph 节点(Fan-in汇聚): 读 summary/actions/insights → Step1: _format_* 生成 Markdown → Step2: 飞书发送 send_meeting_summary → Step3: 统计 jira_issues_created/feishu_tasks_created → Step4: 根据 deadline 设置 reminders_scheduled → Step5: _generate_report() → 写入 state["followup"]; state["status"]=COMPLETED"""
#
#       @staticmethod
#       def _format_summary_markdown(summary) -> str:
#           """MeetingSummary → Markdown: 标题 + 参会人 + 各议题(讨论要点+结论) + 决策 + 下一步"""
#
#       @staticmethod
#       def _format_actions_markdown(actions) -> str:
#           """ActionResult → Markdown: 编号列表，含负责人/任务/截止日期/优先级/Jira飞书同步状态"""
#
#       @staticmethod
#       def _format_insights_markdown(insights) -> str:
#           """MeetingInsight → Markdown: 情绪+效率评分 + 发言统计(含柱状图 █) + 关键词 + 亮点 + 改进建议"""
#
#       @staticmethod
#       def _generate_report(meeting_id, summary_md, actions_md, insights_md) -> str:
#           """生成完整报告 → 返回 "/reports/{meeting_id}.md\""""
