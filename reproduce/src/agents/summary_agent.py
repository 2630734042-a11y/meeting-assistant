"""
Summary Agent（摘要Agent）—— 并行阶段的节点之一

职责:
- 从 state 读取 transcript_text（转写纯文本）
- 构造 Few-shot Prompt 调用 LLM
- 约束 JSON Schema 输出格式
- 解析并验证结果，生成结构化 MeetingSummary
- LLM 失败时降级到规则引擎（从文本中提取说话人列表）

你需要:
1. 导入: json, loguru.logger
2. 从 ..integrations.minimax_client 导入 MiniMaxClient
3. 从 ..models.schemas 导入 MeetingSummary, TopicSummary
"""
from __future__ import annotations

# TODO: 导入 json
# TODO: 从 typing 导入 Any
# TODO: 从 loguru 导入 logger
# TODO: 从 ..integrations.minimax_client 导入 MiniMaxClient
# TODO: 从 ..models.schemas 导入 MeetingSummary, TopicSummary


# TODO: 定义 SUMMARY_SYSTEM_PROMPT (System Prompt)
#   告诉 LLM: 你是会议纪要助手，提取议题/讨论要点/参与人/结论/决策/下一步，必须严格按 JSON 输出

# TODO: 定义 SUMMARY_USER_PROMPT (User Prompt 模板)
#   包含 {transcript} 占位符，指定 JSON 输出格式: title, date, participants, topics(嵌套: title/discussion_points/participants/conclusion), decisions, next_steps


# TODO: 定义 SummaryAgent 类
#   class SummaryAgent:
#       def __init__(self, llm_client=None):
#           """llm_client 默认 MiniMaxClient()"""
#
#       async def process(self, state: dict) -> dict:
#           """LangGraph 节点: 读 transcript_text → 空则返回空 MeetingSummary → 调 _generate_summary() → 写入 state["summary"] → 异常写 errors 并降级 _generate_fallback_summary()"""
#
#       async def _generate_summary(self, transcript: str) -> MeetingSummary:
#           """构造 messages=[system, user(填充transcript)] → llm.chat_json(temperature=0.3, max_tokens=4096) → TopicSummary(**topic) 解析嵌套 → MeetingSummary(**result)"""
#
#       @staticmethod
#       def _generate_fallback_summary(transcript: str) -> MeetingSummary:
#           """降级方案: 从每行按 ":" 分割提取说话人，处理时间戳格式 → MeetingSummary(participants=list(speakers), topics=[降级提示])"""
