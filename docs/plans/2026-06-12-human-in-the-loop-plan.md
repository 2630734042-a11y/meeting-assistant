# Human-in-the-Loop 待办审核 + 前端 实施计划

> **给 Claude：** 必须使用 `superpowers:executing-plans` 子技能，按任务逐项执行本计划。

**目标：** 后端插入 LangGraph interrupt_before 审核节点 + Vue 3 前端页面（上传/报告审核/历史），Human-in-the-Loop 逐条确认待办后才同步 Jira/飞书

**架构方案：** 拆分 ActionAgent（提取与同步解耦）→ 新增 sync_actions 节点 → Graph 编译时 interrupt_before=["sync_actions"] + MemorySaver → 前端 ActionsPanel 逐条审核 → PUT review + POST resume 继续执行

**技术栈：** Python + LangGraph + FastAPI（后端），Vue 3 + Vite + Naive UI（前端），StaticFiles 嵌入托管

---

## 任务拆解

### 任务 1：ActionItem 模型加审核字段

**涉及文件：**
- 修改：`python/src/models/schemas.py:130-144`

**步骤 1：在 ActionItem 前新增 ReviewStatus 枚举**

在 `class Priority(str, Enum)` 之后、`class ActionItem(BaseModel)` 之前插入：

```python
class ReviewStatus(str, Enum):
    """待办审核状态"""
    PENDING = "pending"       # 待审核
    CONFIRMED = "confirmed"   # 已确认，允许同步
    DELETED = "deleted"       # 已删除，不同步
    MODIFIED = "modified"     # 已修改，允许同步（用修改后的值）
```

**步骤 2：ActionItem 新增 review_status 字段**

在 `class ActionItem(BaseModel)` 的 `context: str` 字段之后、`jira_issue_key: str` 之前添加：

```python
    # 审核状态 — HITL
    review_status: str = Field(default="pending", description="审核状态: pending/confirmed/deleted/modified")
```

**步骤 3：运行已有测试确认无回归**

```bash
cd python && python -m pytest tests/ -v
```

预期：**20 个测试全部通过（PASS）**，模型变更向下兼容

**步骤 4：提交**

```bash
git add python/src/models/schemas.py
git commit -m "feat: add ReviewStatus + review_status field to ActionItem"
```

---

### 任务 2：拆分 ActionAgent — 提取与同步解耦

**涉及文件：**
- 修改：`python/src/agents/action_agent.py:84-125`

**步骤 1：将 `_sync_to_external` 从 `process()` 中分离**

将 [action_agent.py:84-125](python/src/agents/action_agent.py#L84-L125) 的 `process()` 方法修改为只提取、不同步：

```python
async def process(self, state: dict) -> dict:
    """
    LangGraph 节点函数 —— 仅提取待办，不同步到外部系统。

    同步操作移到了独立的 sync_actions 节点，在 Human-in-the-Loop 审核之后执行。
    """
    meeting_id = state.get("meeting_id", "unknown")
    logger.info(f"[ActionAgent] Processing meeting: {meeting_id}")

    transcript_text = state.get("transcript_text", "")
    if not transcript_text:
        logger.warning("[ActionAgent] No transcript text available")
        state["actions"] = ActionResult(
            meeting_id=meeting_id, action_items=[]
        )
        return state

    try:
        action_items = await self._extract_actions(transcript_text)
        # 所有条目初始状态为 pending，留待人工审核
        for item in action_items:
            item.review_status = "pending"

        state["actions"] = ActionResult(
            meeting_id=meeting_id,
            action_items=action_items,
            sync_status={
                "jira": "enabled" if self.jira.is_enabled else "disabled",
                "feishu": "enabled" if self.feishu.is_enabled else "disabled",
            },
        )
        logger.info(
            f"[ActionAgent] Extracted {len(action_items)} action items "
            f"(pending review)"
        )
    except Exception as e:
        logger.error(f"[ActionAgent] Error: {e}")
        state["errors"] = state.get("errors", []) + [
            f"ActionAgent: {str(e)}"
        ]
        state["actions"] = ActionResult(
            meeting_id=meeting_id, action_items=[]
        )

    return state
```

**步骤 2：把 `_sync_to_external` 改造为独立的 `sync_actions` 函数**

在文件末尾新增一个独立函数（不是 ActionAgent 方法，直接作为 Graph 节点）：

```python
async def sync_actions_node(state: dict) -> dict:
    """
    LangGraph 节点 —— 同步已审核通过的待办到 Jira 和飞书。

    仅同步 review_status 为 "confirmed" 或 "modified" 的条目，
    review_status 为 "deleted" 的条目跳过。
    已有 jira_issue_key / feishu_task_id 的条目幂等跳过。
    """
    from ..integrations.jira_client import JiraClient
    from ..integrations.feishu_client import FeishuClient

    meeting_id = state.get("meeting_id", "unknown")
    logger.info(f"[sync_actions] Syncing for meeting: {meeting_id}")

    actions: ActionResult | None = state.get("actions")
    if not actions or not actions.action_items:
        logger.info("[sync_actions] No action items to sync")
        return state

    jira = JiraClient()
    feishu = FeishuClient()
    sync_errors = []

    for item in actions.action_items:
        # 跳过不需要同步的条目
        if item.review_status in ("deleted", "pending"):
            continue
        if item.jira_issue_key and item.feishu_task_id:
            # 已同步，幂等跳过
            continue

        # Jira 同步
        if jira.is_enabled:
            try:
                jira_result = jira.create_issue(
                    summary=f"[会议待办] {item.task}",
                    description=(
                        f"来源：会议 {meeting_id}\n"
                        f"负责人：{item.assignee}\n"
                        f"上下文：{item.context}"
                    ),
                    assignee=jira.resolve_user(item.assignee),
                    due_date=item.deadline or None,
                    priority=JiraClient.map_priority(item.priority.value),
                    labels=["meeting-auto", f"meeting-{meeting_id}"],
                )
                item.jira_issue_key = jira_result["key"]
            except Exception as e:
                msg = f"Jira sync failed for '{item.task}': {e}"
                logger.error(msg)
                sync_errors.append(msg)

        # 飞书同步
        if feishu.is_enabled:
            try:
                from datetime import datetime
                due_ts = None
                if item.deadline:
                    due_dt = datetime.strptime(item.deadline, "%Y-%m-%d")
                    due_ts = int(due_dt.timestamp())

                feishu_result = await feishu.create_task(
                    summary=f"[会议待办] {item.task}",
                    description=(
                        f"负责人：{item.assignee}\n"
                        f"来源会议：{meeting_id}\n"
                        f"上下文：{item.context}"
                    ),
                    due_timestamp=due_ts,
                )
                item.feishu_task_id = feishu_result.get("task_id")
            except Exception as e:
                msg = f"Feishu sync failed for '{item.task}': {e}"
                logger.error(msg)
                sync_errors.append(msg)

    if sync_errors:
        state["errors"] = state.get("errors", []) + sync_errors
    logger.info(
        f"[sync_actions] Done: synced={sum(1 for i in actions.action_items if i.jira_issue_key or i.feishu_task_id)}, "
        f"errors={len(sync_errors)}"
    )
    return state
```

**步骤 3：验证导入**

```bash
cd python && python -c "from src.agents.action_agent import ActionAgent, sync_actions_node; print('Import OK')"
```

预期：**Import OK**

**步骤 4：提交**

```bash
git add python/src/agents/action_agent.py
git commit -m "refactor: split ActionAgent — extract only, defer sync to sync_actions_node"
```

---

### 任务 3：重建 Graph — 插入 interrupt + sync_actions 节点

**涉及文件：**
- 修改：`python/src/graph/meeting_graph.py`

**步骤 1：修改 import**

在 [meeting_graph.py:52](python/src/graph/meeting_graph.py#L52) 添加 `sync_actions_node` 导入，同时导入 `MemorySaver`：

```python
from ..agents.action_agent import ActionAgent, sync_actions_node
from langgraph.checkpoint.memory import MemorySaver
```

**步骤 2：GraphState 新增 `thread_id` 字段（可选）**

在 [GraphState](python/src/graph/meeting_graph.py#L68-L86) 中添加：

```python
    thread_id: Annotated[str, lambda a, b: a or b]
```

**步骤 3：注册 sync_actions 节点 + 修改边**

在 `build_meeting_graph()` 函数中，注册 `sync_actions` 节点（在第 137 行 `followup_agent` 注册之后）：

```python
    # 注册 sync_actions 节点（HITL 审核后执行）
    graph.add_node("sync_actions", sync_actions_node)
```

修改边定义——将 `action` → `followup` 改为 `action` → `sync_actions` → `followup`：

```python
    # Fan-out 并行: Transcription → [Summary, Action, Insight]
    graph.add_edge("transcription", "summary")
    graph.add_edge("transcription", "action")
    graph.add_edge("transcription", "insight")

    # Fan-in 汇聚: Summary → Follow-up
    graph.add_edge("summary", "followup")
    # Action 先经过 sync_actions 再进入 Follow-up（HITL 介入点）
    graph.add_edge("action", "sync_actions")
    graph.add_edge("sync_actions", "followup")
    # Insight 直接进入 Follow-up
    graph.add_edge("insight", "followup")
```

**步骤 4：修改 `compile_meeting_graph()` — 加 checkpointer + interrupt**

```python
def compile_meeting_graph(**kwargs) -> Any:
    """构建并编译 Graph（编译后可直接调用）"""
    graph = build_meeting_graph(**kwargs)
    checkpointer = MemorySaver()
    compiled = graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["sync_actions"],
    )
    logger.info("Meeting graph compiled successfully (HITL: interrupt_before sync_actions)")
    return compiled
```

**步骤 5：修改 `run_meeting_pipeline()` — 加 thread_id + config**

`run_meeting_pipeline` 接受可选的 `thread_id` 参数，用于 checkpoint 恢复：

```python
async def run_meeting_pipeline(
    meeting_id: str,
    audio_data: bytes = b"",
    thread_id: str = "",
    **kwargs,
) -> dict:
    """
    执行完整的会议处理 Pipeline

    如果 thread_id 为空，自动生成。Graph 在 sync_actions 前中断，
    需要外部调用 POST /resume 提交审核结果后继续。
    """
    logger.info(f"Starting meeting pipeline: {meeting_id} (thread={thread_id or 'new'})")

    thread_id = thread_id or f"thread-{meeting_id}"
    initial_state = create_initial_state(meeting_id, audio_data)
    initial_state["thread_id"] = thread_id

    compiled_graph = compile_meeting_graph(**kwargs)
    config = {"configurable": {"thread_id": thread_id}}

    final_state = await compiled_graph.ainvoke(initial_state, config=config)

    errors = final_state.get("errors", [])
    if errors:
        logger.warning(f"Pipeline completed with errors: {errors}")
    else:
        logger.info(f"Pipeline completed successfully for: {meeting_id}")

    # 标记是否中断（前端据此判断是否需要展示审核界面）
    final_state["thread_id"] = thread_id
    return final_state
```

**步骤 6：新增 `resume_meeting_pipeline()` — 恢复中断**

在文件末尾新增：

```python
async def resume_meeting_pipeline(thread_id: str, **kwargs) -> dict:
    """
    从中断点恢复 Pipeline 执行。

    前提：用户已通过 PUT /actions/review 提交审核结果。
    """
    logger.info(f"Resuming pipeline: thread={thread_id}")
    compiled_graph = compile_meeting_graph(**kwargs)
    config = {"configurable": {"thread_id": thread_id}}
    
    # LangGraph resume: 传入 None 表示继续从上次中断点执行
    final_state = await compiled_graph.ainvoke(None, config=config)

    errors = final_state.get("errors", [])
    if errors:
        logger.warning(f"Resumed pipeline completed with errors: {errors}")
    else:
        logger.info(f"Resumed pipeline completed for: {thread_id}")

    return final_state
```

**步骤 7：验证 Graph 编译**

```bash
cd python && python -c "from src.graph.meeting_graph import build_meeting_graph, compile_meeting_graph; g = compile_meeting_graph(); print('Graph compiled OK')"
```

预期：**Graph compiled OK**

**步骤 8：提交**

```bash
git add python/src/graph/meeting_graph.py
git commit -m "feat: insert HITL interrupt + sync_actions node into graph"
```

---

### 任务 4：新增 REST 端点 — PUT review + POST resume

**涉及文件：**
- 修改：`python/src/websocket/server.py`

**步骤 1：添加 import**

在 [server.py:25](python/src/websocket/server.py#L25) 添加 `resume_meeting_pipeline` 导入：

```python
from ..graph.meeting_graph import run_meeting_pipeline, resume_meeting_pipeline
```

**步骤 2：新增 `PUT /actions/review` 端点**

在 `/upload-video` 端点之后（第 316 行附近）插入：

```python
@app.put("/api/v1/meeting/{meeting_id}/actions/review")
async def review_actions(meeting_id: str, request: Request):
    """
    提交待办审核结果（HITL 介入点）

    接收前端逐条编辑/确认/删除后的最终待办列表，
    更新 meeting_results 中的 ActionItems，
    后续 POST /resume 时 sync_actions 节点按 review_status 同步。
    """
    result = meeting_results.get(meeting_id)
    if not result:
        raise HTTPException(status_code=404, detail="Meeting not found")

    body = await request.json()
    reviewed_items = body.get("items", [])

    actions: ActionResult | None = result.get("actions")
    if not actions:
        raise HTTPException(status_code=404, detail="No action items found")

    updated_count = 0
    for review in reviewed_items:
        idx = review.get("index", -1)
        if 0 <= idx < len(actions.action_items):
            item = actions.action_items[idx]
            item.review_status = review.get("review_status", item.review_status)

            if item.review_status in ("confirmed", "modified"):
                # 应用用户修改的字段
                item.assignee = review.get("assignee", item.assignee)
                item.task = review.get("task", item.task)
                item.deadline = review.get("deadline", item.deadline)
                if "priority" in review:
                    try:
                        item.priority = Priority(review["priority"])
                    except ValueError:
                        pass
            updated_count += 1

    logger.info(
        f"Review submitted for {meeting_id}: "
        f"{updated_count} items updated"
    )

    return {
        "meeting_id": meeting_id,
        "reviewed_count": updated_count,
        "status": "reviewed",
    }
```

注意需要在 server.py 顶部添加 `from ..models.schemas import Priority`（如果尚不存在）。

**步骤 3：新增 `POST /resume` 端点**

```python
@app.post("/api/v1/meeting/{meeting_id}/resume")
async def resume_pipeline(meeting_id: str, request: Request):
    """
    确认审核完毕，继续执行 sync_actions + FollowUp

    用户在前端逐条确认待办后，调用此端点从中断点恢复 Graph 执行。
    """
    result = meeting_results.get(meeting_id)
    if not result:
        raise HTTPException(status_code=404, detail="Meeting not found")

    body = await request.json()
    thread_id = body.get("thread_id", f"thread-{meeting_id}")

    logger.info(f"Resuming pipeline: {meeting_id} (thread={thread_id})")

    try:
        final_state = await resume_meeting_pipeline(thread_id=thread_id)
        meeting_results[meeting_id] = final_state
        return {
            "meeting_id": meeting_id,
            "status": final_state.get("status", "syncing"),
            "message": "Pipeline resumed, sync in progress",
        }
    except Exception as e:
        logger.error(f"Resume failed: {e}")
        raise HTTPException(status_code=500, detail=f"恢复执行失败: {e}")
```

**步骤 4：修改 `upload` / `upload-video` / `demo` 端点返回值加 `thread_id`**

修改这三个端点的 `run_meeting_pipeline()` 调用，传入 `thread_id`：

`upload` 端点（第 230 行附近）：
```python
    thread_id = f"thread-{meeting_id}"
    result = await run_meeting_pipeline(
        meeting_id=meeting_id,
        audio_data=audio_data,
        thread_id=thread_id,
    )
    meeting_results[meeting_id] = result

    return {
        "meeting_id": meeting_id,
        "thread_id": thread_id,
        "status": result.get("status", "completed"),
        "errors": result.get("errors", []),
    }
```

同样改 `upload-video` 和 `demo` 端点，返回值加 `"thread_id": thread_id`。

**步骤 5：导入 `Request`**

确认 server.py 顶部有：
```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException, Request
```

**步骤 6：验证服务器启动**

```bash
cd python && timeout 5 python -m uvicorn src.websocket.server:app --host 0.0.0.0 --port 8000 2>&1 || true
```

预期：**无导入错误，服务器正常启动**

**步骤 7：提交**

```bash
git add python/src/websocket/server.py
git commit -m "feat: add PUT /actions/review + POST /resume HITL endpoints"
```

---

### 任务 5：HITL 流程集成测试

**涉及文件：**
- 新建：`python/tests/test_human_in_loop.py`

**步骤 1：编写 HITL 集成测试**

```python
"""Human-in-the-Loop 审核流程集成测试"""

import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.websocket.server import app


@pytest.fixture(autouse=True)
def mock_external_services():
    """模拟所有外部服务：WhisperX、LLM、Jira、飞书"""
    with (
        patch(
            "src.agents.transcription_agent.TranscriptionAgent._lazy_init",
            return_value=None,
        ),
        patch(
            "src.integrations.llm_client.LLMClient.chat_json",
            new_callable=AsyncMock,
            return_value={
                "action_items": [
                    {
                        "assignee": "李明",
                        "task": "整理Q3预算方案",
                        "deadline": "2026-06-20",
                        "priority": "high",
                        "context": "Q3需要上调预算15%",
                    },
                    {
                        "assignee": "王芳",
                        "task": "拟定招聘JD",
                        "deadline": "2026-06-15",
                        "priority": "medium",
                        "context": "招聘3名高级算法工程师",
                    },
                ]
            },
        ),
        patch(
            "src.integrations.llm_client.LLMClient.chat",
            new_callable=AsyncMock,
            return_value="mock llm response",
        ),
        patch(
            "src.integrations.jira_client.JiraClient.is_enabled",
            new_callable=MagicMock,
            return_value=True,
        ),
        patch(
            "src.integrations.jira_client.JiraClient.create_issue",
            return_value={"key": "MOCK-123"},
        ),
        patch(
            "src.integrations.jira_client.JiraClient.resolve_user",
            return_value="mock_user",
        ),
        patch(
            "src.integrations.feishu_client.FeishuClient.is_enabled",
            new_callable=MagicMock,
            return_value=True,
        ),
        patch(
            "src.integrations.feishu_client.FeishuClient.create_task",
            new_callable=AsyncMock,
            return_value={"task_id": "feishu-task-001"},
        ),
        patch(
            "src.integrations.feishu_client.FeishuClient.send_meeting_summary",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        yield


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHumanInTheLoop:
    """HITL 审核流程"""

    @pytest.mark.asyncio
    async def test_interrupt_after_action_extraction(self, client):
        """上传音频后 pipeline 应在 sync_actions 前中断"""
        # 生成测试音频
        import subprocess, tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=2", "-ac", "1",
             "-ar", "16000", str(wav_path)],
            check=True, capture_output=True,
        )
        try:
            with open(wav_path, "rb") as f:
                response = await client.post(
                    "/api/v1/meeting/hitl-test-1/upload",
                    files={"file": ("test.wav", f, "audio/wav")},
                )
        finally:
            wav_path.unlink(missing_ok=True)

        assert response.status_code == 200
        data = response.json()
        # 中断后 state 应包含提取的待办
        assert "thread_id" in data

        # 查询待办（审核前）
        report = await client.get("/api/v1/meeting/hitl-test-1/report")
        assert report.status_code == 200
        report_data = report.json()
        assert "actions" in report_data

    @pytest.mark.asyncio
    async def test_review_then_resume(self, client):
        """提交审核 → resume → 待办被同步"""
        import subprocess, tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=2", "-ac", "1",
             "-ar", "16000", str(wav_path)],
            check=True, capture_output=True,
        )
        try:
            with open(wav_path, "rb") as f:
                response = await client.post(
                    "/api/v1/meeting/hitl-test-2/upload",
                    files={"file": ("test.wav", f, "audio/wav")},
                )
        finally:
            wav_path.unlink(missing_ok=True)

        data = response.json()
        thread_id = data["thread_id"]

        # 提交审核：确认第一条，删除第二条
        review_response = await client.put(
            "/api/v1/meeting/hitl-test-2/actions/review",
            json={
                "thread_id": thread_id,
                "items": [
                    {"index": 0, "review_status": "confirmed"},
                    {"index": 1, "review_status": "deleted"},
                ],
            },
        )
        assert review_response.status_code == 200
        assert review_response.json()["status"] == "reviewed"

        # Resume → sync_actions → FollowUp
        resume_response = await client.post(
            "/api/v1/meeting/hitl-test-2/resume",
            json={"thread_id": thread_id},
        )
        assert resume_response.status_code == 200

        # 最终报告应包含同步结果
        report = await client.get("/api/v1/meeting/hitl-test-2/report")
        assert report.status_code == 200
        report_data = report.json()
        print("HITL Report:", report_data)

    @pytest.mark.asyncio
    async def test_review_nonexistent_meeting_returns_404(self, client):
        response = await client.put(
            "/api/v1/meeting/nonexistent/actions/review",
            json={"thread_id": "t1", "items": []},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_resume_nonexistent_meeting_returns_404(self, client):
        response = await client.post(
            "/api/v1/meeting/nonexistent/resume",
            json={"thread_id": "t1"},
        )
        assert response.status_code == 404
```

**步骤 2：运行集成测试**

```bash
cd python && export PATH="/c/Users/Eric/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1.1-full_build/bin:$PATH" && python -m pytest tests/test_human_in_loop.py -v
```

预期：**4 个测试全部通过（PASS）**

**步骤 3：全量回归测试**

```bash
cd python && export PATH="/c/Users/Eric/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1.1-full_build/bin:$PATH" && python -m pytest tests/ -v
```

预期：**24 个测试全部通过（20 已有 + 4 新增），无回归**

**步骤 4：提交**

```bash
git add python/tests/test_human_in_loop.py
git commit -m "test: add HITL interrupt + review + resume integration tests"
```

---

### 任务 6：Vue 3 前端项目搭建

**涉及文件：**
- 新建：`python/frontend/` 整个目录

**步骤 1：用 Vite 脚手架创建项目**

```bash
cd python && npm create vite@latest frontend -- --template vue-ts
cd frontend && npm install
```

**步骤 2：安装 Naive UI + 依赖**

```bash
cd python/frontend && npm install naive-ui @vicons/ionicons5 vue-router@4
```

**步骤 3：配置 Vite — 支持打包到 FastAPI static 目录**

修改 `python/frontend/vite.config.ts`：

```typescript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
```

**步骤 4：配置路由**

修改 `python/frontend/src/main.ts`：

```typescript
import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'

const routes = [
  { path: '/', redirect: '/upload' },
  { path: '/upload', component: () => import('./views/UploadView.vue') },
  { path: '/report/:id', component: () => import('./views/ReportView.vue') },
  { path: '/history', component: () => import('./views/HistoryView.vue') },
]

const router = createRouter({ history: createWebHashHistory(), routes })
const app = createApp(App)
app.use(router)
app.mount('#app')
```

**步骤 5：配置 Naive UI 全局**

在 `main.ts` 中（router 之前）：

```typescript
import naive from 'naive-ui'
app.use(naive)
```

**步骤 6：验证 dev server 启动**

```bash
cd python/frontend && timeout 8 npm run dev 2>&1 || true
```

预期：**Vite dev server 在 localhost:5173 启动**

**步骤 7：提交**

```bash
git add python/frontend/ python/static/.gitkeep
git commit -m "feat: scaffold Vue 3 + Vite + Naive UI frontend"
```

---

### 任务 7：TypeScript 类型定义 + API 封装

**涉及文件：**
- 新建：`python/frontend/src/shared/types.ts`
- 新建：`python/frontend/src/shared/api.ts`

**步骤 1：编写 `types.ts` — 对齐 Pydantic 模型**

```typescript
// 枚举
export type MeetingStatus = 'created' | 'transcribing' | 'summarying' |
  'extracting' | 'analyzing' | 'following_up' | 'completed' | 'failed'

export type Priority = 'low' | 'medium' | 'high' | 'urgent'

export type ReviewStatus = 'pending' | 'confirmed' | 'deleted' | 'modified'

export type SentimentType = 'positive' | 'neutral' | 'negative'

// 转写
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

// 摘要
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

// 待办（HITL 核心）
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

// 洞察
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

// 跟进
export interface FollowUpResult {
  meeting_id: string
  summary_sent: boolean
  recipients: string[]
  jira_issues_created: string[]
  feishu_tasks_created: string[]
  reminders_scheduled: number
  report_url: string
}

// 完整报告
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
```

**步骤 2：编写 `api.ts` — 封装所有 REST 调用**

```typescript
import type { MeetingReport } from './types'

const BASE = ''  // 嵌入 FastAPI 时同源，无需完整 URL

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

// 创建会议
export function createMeeting(): Promise<{ meeting_id: string }> {
  return request('/api/v1/meeting/start', { method: 'POST' })
}

// 上传音频
export function uploadAudio(meetingId: string, file: File) {
  const form = new FormData()
  form.append('file', file)
  return fetch(`/api/v1/meeting/${meetingId}/upload`, { method: 'POST', body: form })
    .then(r => r.json())
}

// 上传视频
export function uploadVideo(meetingId: string, file: File) {
  const form = new FormData()
  form.append('file', file)
  return fetch(`/api/v1/meeting/${meetingId}/upload-video`, { method: 'POST', body: form })
    .then(r => r.json())
}

// 演示模式
export function runDemo(meetingId: string) {
  return request(`/api/v1/meeting/${meetingId}/demo`, { method: 'POST' })
}

// 获取完整报告
export function getReport(meetingId: string): Promise<MeetingReport> {
  return request(`/api/v1/meeting/${meetingId}/report`)
}

// 提交待办审核（HITL 核心）
export function reviewActions(meetingId: string, threadId: string, items: any[]) {
  return request(`/api/v1/meeting/${meetingId}/actions/review`, {
    method: 'PUT',
    body: JSON.stringify({ thread_id: threadId, items }),
  })
}

// 恢复执行（HITL 核心）
export function resumePipeline(meetingId: string, threadId: string) {
  return request(`/api/v1/meeting/${meetingId}/resume`, {
    method: 'POST',
    body: JSON.stringify({ thread_id: threadId }),
  })
}
```

**步骤 3：验证 TypeScript 编译**

```bash
cd python/frontend && npx vue-tsc --noEmit 2>&1
```

预期：**无类型错误**

**步骤 4：提交**

```bash
git add python/frontend/src/shared/
git commit -m "feat: add TypeScript types + API layer for frontend"
```

---

### 任务 8：上传页面（UploadView）

**涉及文件：**
- 新建：`python/frontend/src/views/UploadView.vue`
- 新建：`python/frontend/src/components/UploadZone.vue`
- 新建：`python/frontend/src/components/ProcessingStatus.vue`
- 新建：`python/frontend/src/components/RecentMeetings.vue`

**步骤 1：编写 AppShell（App.vue）**

用 Naive Layout 包裹路由：

```vue
<template>
  <n-layout style="min-height: 100vh">
    <n-layout-header bordered>
      <n-menu mode="horizontal" :value="currentPath" :options="menuOptions"
        @update:value="(v: string) => router.push(v)" />
    </n-layout-header>
    <n-layout-content style="padding: 24px; max-width: 1200px; margin: 0 auto">
      <router-view />
    </n-layout-content>
  </n-layout>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
const router = useRouter()
const route = useRoute()
const currentPath = computed(() => route.path)

const menuOptions = [
  { label: '上传', key: '/upload' },
  { label: '历史', key: '/history' },
]
</script>
```

**步骤 2：编写 UploadZone.vue — 拖拽+点击上传**

- Naive UI `NUpload` 组件，`accept="video/*,audio/*"`，`multiple=false`
- 校验格式：`isVideoFile` / `isAudioFile` 函数（后端有 format 校验，前端预检）
- 选择文件后自动触发上传
- 支持三种入口：拖拽区域（音频/视频）、Demo 按钮

**步骤 3：编写 ProcessingStatus.vue — 处理阶段动画**

- 三阶段进度：上传 ✅ → 提取中 / 处理中 ⏳ → 完成 ✅
- 用 Naive UI `NSteps` 展示
- 完成后自动跳转到 `/report/:id`

**步骤 4：编写 RecentMeetings.vue**

- 从 `localStorage` 读取最近 5 条会议记录
- Naive UI `NCard` 卡片展示，点击跳转报告页

**步骤 5：编写 UploadView.vue — 组合**

```vue
<template>
  <n-space vertical size="large">
    <UploadZone @done="onUploadDone" />
    <ProcessingStatus v-if="processing" :stage="stage" />
    <RecentMeetings v-else @select="id => router.push(`/report/${id}`)" />
  </n-space>
</template>
```

**步骤 6：Vite dev 验证上传页渲染**

```bash
cd python/frontend && timeout 10 npm run dev 2>&1 || true
```

在浏览器访问 `http://localhost:5173/upload`。
预期：**上传区域 + 最近会议列表正确渲染**

**步骤 7：提交**

```bash
git add python/frontend/src/views/UploadView.vue python/frontend/src/components/ python/frontend/src/App.vue
git commit -m "feat: upload page with drag-drop zone + processing status"
```

---

### 任务 9：报告页面 + HITL 审核面板（核心）

**涉及文件：**
- 新建：`python/frontend/src/views/ReportView.vue`
- 新建：`python/frontend/src/components/TranscriptPanel.vue`
- 新建：`python/frontend/src/components/SummaryPanel.vue`
- 新建：`python/frontend/src/components/ActionsPanel.vue` ⬅ HITL 核心
- 新建：`python/frontend/src/components/InsightsPanel.vue`

**步骤 1：编写 TranscriptPanel.vue**

- 时间轴风格，`NTimeline` 组件
- 每条 fragment：时间戳 + 说话人气泡 + 文本
- 不同说话人不同颜色

**步骤 2：编写 SummaryPanel.vue**

- Markdown 渲染（`marked` 库或纯文本格式化）
- 议题列表、决策列表、下一步计划卡片

**步骤 3：编写 ActionsPanel.vue — HITL 审核界面（核心）**

```vue
<template>
  <n-space vertical size="medium">
    <n-alert v-if="!reviewed && actions?.action_items?.length"
      type="warning" title="待审核" :bordered="false">
      请逐条审核待办事项，确认后点击底部按钮发送到 Jira 和飞书
    </n-alert>

    <n-card v-for="(item, idx) in actions?.action_items" :key="idx"
      :bordered="true"
      :style="{ opacity: item.review_status === 'deleted' ? 0.4 : 1 }">
      <template #header>
        <n-space align="center" justify="space-between">
          <n-tag v-if="item.review_status === 'pending'" type="default">待审核</n-tag>
          <n-tag v-else-if="item.review_status === 'confirmed'" type="success">已确认</n-tag>
          <n-tag v-else-if="item.review_status === 'deleted'" type="error">已删除</n-tag>
          <n-tag v-else-if="item.review_status === 'modified'" type="info">已修改</n-tag>
          <n-text depth="2">#{{ idx + 1 }}</n-text>
        </n-space>
      </template>

      <!-- 编辑模式 v-if="editing === idx" -->
      <n-form v-if="editing === idx">
        <n-form-item label="任务">
          <n-input v-model:value="edits.task" />
        </n-form-item>
        <n-form-item label="负责人">
          <n-input v-model:value="edits.assignee" />
        </n-form-item>
        <n-form-item label="截止日期">
          <n-date-picker v-model:value="edits.deadlineDate" type="date" />
        </n-form-item>
        <n-form-item label="优先级">
          <n-select v-model:value="edits.priority" :options="priorityOptions" />
        </n-form-item>
        <n-space>
          <n-button size="small" type="primary" @click="saveEdit(idx)">保存修改</n-button>
          <n-button size="small" @click="editing = -1">取消</n-button>
        </n-space>
      </n-form>

      <!-- 展示模式 -->
      <template v-else>
        <n-descriptions :column="2" size="small" bordered>
          <n-descriptions-item label="任务">{{ item.task }}</n-descriptions-item>
          <n-descriptions-item label="负责人">{{ item.assignee }}</n-descriptions-item>
          <n-descriptions-item label="截止">{{ item.deadline || '未指定' }}</n-descriptions-item>
          <n-descriptions-item label="优先级">
            <n-tag :type="priorityColor(item.priority)">{{ item.priority }}</n-tag>
          </n-descriptions-item>
        </n-descriptions>
      </template>

      <template #action v-if="!reviewed">
        <n-space>
          <n-button size="small" type="primary" @click="startEdit(idx)">✏️ 编辑</n-button>
          <n-button size="small" type="success" @click="confirmItem(idx)">✅ 确认</n-button>
          <n-button size="small" type="error" @click="deleteItem(idx)">⛔ 删除</n-button>
        </n-space>
      </template>
    </n-card>

    <n-empty v-if="!actions?.action_items?.length"
      description="本会议无提取到的待办事项" />

    <!-- 底部操作栏 -->
    <n-space v-if="!reviewed && actions?.action_items?.length" justify="end"
      style="margin-top: 16px">
      <n-button type="primary" size="large" :loading="submitting"
        @click="submitReview">
        📤 全部确认并发送
      </n-button>
    </n-space>
  </n-space>
</template>
```

核心逻辑（`<script setup>`）：

```typescript
const reviewed = ref(false)
const editing = ref(-1)
const edits = reactive({ task: '', assignee: '', deadlineDate: null as number | null, priority: 'medium' })

function startEdit(idx: number) { /* 进入编辑模式 */ }
function saveEdit(idx: number) { /* item.review_status = 'modified', 应用编辑值 */ }
function confirmItem(idx: number) { /* item.review_status = 'confirmed' */ }
function deleteItem(idx: number) { /* item.review_status = 'deleted' */ }

async function submitReview() {
  const items = actions.action_items.map((item, idx) => ({
    index: idx,
    review_status: item.review_status,
    assignee: item.assignee,
    task: item.task,
    deadline: item.deadline,
    priority: item.priority,
  }))
  await api.reviewActions(meetingId, threadId, items)
  await api.resumePipeline(meetingId, threadId)
  // 轮询等待 completed
  reviewed.value = true
}
```

**步骤 4：编写 InsightsPanel.vue**

- 发言统计：`NProgress` 柱状条（每位说话人的占比）
- 效率评分 + 情绪卡片
- 关键词标签 `NTag`
- 亮点 + 改进建议列表

**步骤 5：编写 ReportView.vue — Tab 容器**

```vue
<template>
  <n-tabs type="line" animated>
    <n-tab-pane name="transcript" tab="📝 转写">
      <TranscriptPanel :data="report?.transcript" />
    </n-tab-pane>
    <n-tab-pane name="summary" tab="📋 纪要">
      <SummaryPanel :data="report?.summary" />
    </n-tab-pane>
    <n-tab-pane name="actions" tab="✅ 待办">
      <ActionsPanel :data="report?.actions" :thread-id="report?.thread_id"
        :meeting-id="report?.meeting_id" />
    </n-tab-pane>
    <n-tab-pane name="insights" tab="🔍 洞察">
      <InsightsPanel :data="report?.insights" />
    </n-tab-pane>
  </n-tabs>
</template>
```

报告页加载时调 `api.getReport(id)` 获取数据，每 3 秒轮询直到 `status === 'completed'` 或达到上限（30 次）。

**步骤 6：Vite dev 验证报告页渲染**

浏览器访问 `http://localhost:5173/report/demo`。
预期：**四个 Tab 正确渲染，待办 Tab 显示审核操作按钮**

**步骤 7：提交**

```bash
git add python/frontend/src/views/ReportView.vue python/frontend/src/components/ python/frontend/src/shared/
git commit -m "feat: report page with HITL action review panels"
```

---

### 任务 10：历史页面

**涉及文件：**
- 新建：`python/frontend/src/views/HistoryView.vue`

**步骤 1：编写 HistoryView.vue**

- 从 `localStorage` 读取所有历史会议 ID 列表
- 批量调 `getReport`（或单独一个列表 endpoint）获取摘要
- Naive UI `NDataTable`：会议 ID | 日期 | 状态 | 操作
- 点击行跳转 `/report/:id`
- 支持搜索 + 状态筛选

**步骤 2：提交**

```bash
git add python/frontend/src/views/HistoryView.vue
git commit -m "feat: history page with meeting list"
```

---

### 任务 11：生产构建 + 嵌入 FastAPI

**涉及文件：**
- 修改：`python/src/websocket/server.py` — 加 StaticFiles
- 修改：`python/frontend/.gitignore`

**步骤 1：Vite 生产构建**

```bash
cd python/frontend && npm run build
```

预期：**产物输出到 `python/static/` 目录（index.html + assets）**

**步骤 2：FastAPI 挂载 StaticFiles**

在 [server.py:36](python/src/websocket/server.py#L36) `app = FastAPI(...)` 之后、CORS 中间件之前，加：

```python
from fastapi.staticfiles import StaticFiles

# 为前端 SPA 提供服务 — 开发模式用 Vite dev server 代理，
# 生产模式 pip install aiofiles && npm run build 后自动托管
static_path = Path(__file__).resolve().parent.parent.parent / "static"
if static_path.exists() and (static_path / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(static_path), html=True), name="static")
```

同时确认 `pyproject.toml` 的 dependencies 中有 `aiofiles`，如没有则加。

**步骤 3：SPA fallback 处理**

Naive UI 的 `StaticFiles(html=True)` 模式会自动 fallback 到 `index.html`，让 Vue Router 的 hash/history 模式工作。

**步骤 4：验证生产模式**

```bash
cd python && pip install aiofiles -q
cd python && python -m uvicorn src.websocket.server:app --host 0.0.0.0 --port 8000 &
sleep 2
curl http://localhost:8000/  # 应返回 HTML 页面
```

预期：**返回 Vue SPA 的 index.html**

**步骤 5：提交**

```bash
git add python/src/websocket/server.py python/pyproject.toml python/static/
git commit -m "feat: embed Vue SPA via FastAPI StaticFiles"
```

---

### 任务 12：端到端验证

**步骤 1：启动完整服务**

```bash
cd python && python -m uvicorn src.websocket.server:app --host 0.0.0.0 --port 8000
```

**步骤 2：浏览器测试完整流程**

1. 打开 `http://localhost:8000` → 看到上传页面
2. 生成测试视频：`ffmpeg -y -f lavfi -i testsrc=duration=2:size=160x120 -f lavfi -i sine=frequency=440:duration=2 -c:v libx264 -c:a aac -shortest test.mp4`
3. 拖拽 `test.mp4` 到上传区域
4. 等待处理完成 → 自动跳转报告页
5. 待办 Tab 展示提取的待办（来自 mock LLM）
6. 逐条确认/编辑/删除
7. 点「全部确认并发送」
8. 报告页最终状态为 completed

**步骤 3：清理**

```bash
rm test.mp4
```

---

## 验证方式

全部完成后运行全量测试确认无回归：

```bash
cd python && export PATH="/c/Users/Eric/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1.1-full_build/bin:$PATH" && python -m pytest tests/ -v
```

预期：**24 个测试全部通过（20 已有 + 4 HITL 集成测试）**

## 风险与注意事项

1. **LangGraph MemorySaver**：内存存储，服务器重启后中断状态丢失。生产环境应替换为 `SqliteSaver` 或 Redis-backed checkpointer
2. **前端路由**：SPA hash 路由模式下，后端无需额外 fallback，但 SSR 刷新时需确认 StaticFiles(html=True) 行为
3. **Mock 依赖**：HITL 集成测试需要大量 mock（LLM + Jira + 飞书），mock 变更需同步更新测试
4. **并发中断**：多个 meeting 并发时 MemorySaver 按 thread_id 隔离，理论上安全，但未做并发压测
5. **aiofiles**：StaticFiles 依赖 aiofiles，需确认已加入 `pyproject.toml` dependencies
