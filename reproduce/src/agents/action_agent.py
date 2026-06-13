"""
Action Agent（待办Agent）—— 并行阶段的节点之一

职责:
- 从转写文本中提取行动项（谁/做什么/截止时间/优先级/背景）
- LLM Few-shot Prompt 提取结构化 ActionItem 列表
- 并行同步到 Jira Cloud 和飞书任务
- 支持幂等性保证（meeting-auto 标签 + meeting_id 去重）

你需要:
1. 导入: json, datetime (datetime), loguru.logger
2. 从 ..integrations 导入 MiniMaxClient, JiraClient, FeishuClient
3. 从 ..models.schemas 导入 ActionItem, ActionResult, Priority
"""
from __future__ import annotations

# TODO: 导入 json
# TODO: 从 datetime 导入 datetime
# TODO: 从 typing 导入 Any
# TODO: 从 loguru 导入 logger
# TODO: 从 ..integrations 导入 MiniMaxClient, JiraClient, FeishuClient
# TODO: 从 ..models.schemas 导入 ActionItem, ActionResult, Priority


# TODO: 定义 ACTION_SYSTEM_PROMPT (System Prompt)
#   告诉 LLM: 你是任务提取助手，只提取明确分配的任务，不要凭空创造，输出 JSON

# TODO: 定义 ACTION_USER_PROMPT (User Prompt 模板)
#   包含 {today} 和 {transcript} 占位符，指定 JSON 格式: action_items 数组 (assignee, task, deadline, priority, context)


# TODO: 定义 ActionAgent 类
#   class ActionAgent:
#       def __init__(self, llm_client=None, jira_client=None, feishu_client=None):
#           """三个 client 默认自动创建，支持依赖注入"""
#
#       async def process(self, state: dict) -> dict:
#           """LangGraph 节点: 读 transcript_text → _extract_actions() LLM提取 → _sync_to_external() 同步 Jira/飞书 → 写入 state["actions"] (ActionResult 含 sync_status)"""
#
#       async def _extract_actions(self, transcript: str) -> list[ActionItem]:
#           """构造 messages (today=datetime.now()) → llm.chat_json(temperature=0.2, max_tokens=2048) → 遍历构造 ActionItem，priority 转换 try/except ValueError 兜底"""
#
#       async def _sync_to_external(self, items, meeting_id) -> list[ActionItem]:
#           """遍历 items: jira.is_enabled → jira.create_issue() 回填 jira_issue_key; feishu.is_enabled → feishu.create_task() 回填 feishu_task_id"""
