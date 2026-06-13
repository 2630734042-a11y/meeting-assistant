# Human-in-the-Loop 待办审核 设计说明

## 背景与目标

当前系统在 ActionAgent 提取待办后立即同步到 Jira 和飞书，零人工审核。LLM 幻觉可能导致错误分配负责人、截止时间或凭空创造不存在的任务，外部系统直接受影响。

**目标：** 在 Action 提取和外部同步之间插入人工审核节点，用户逐条确认/修改/删除待办后，仅同步已确认条目。

**成功标准：**
- 用户可在前端逐条审核待办（编辑/删除/确认）
- 只同步 `review_status == "confirmed"` 的条目到 Jira/飞书
- 全部删除时正常结束，不报错
- 中断恢复：页面关闭后重开，能恢复审核进度
- 服务器重启时状态可丢失（MemorySaver），生产环境再换持久化

## 现状与约束

- LangGraph `StateGraph` 已支持 `interrupt_before` 中断机制
- `ActionAgent.process()` 当前提取 + 同步耦合在一起
- `create_initial_state()` 创建的初始 state 无 `review_status` 字段
- Vue 3 + Naive UI 前端已有报告页（TranscriptPanel / SummaryPanel / ActionsPanel / InsightsPanel）
- 依赖：LangGraph checkpoint (MemorySaver)，Vue 3 响应式，Naive UI 组件

## 方案对比

### 方案一：LangGraph interrupt_before（推荐）

在 Graph 编译时设定 `interrupt_before=["sync_actions"]`，图在 sync 前自动暂停。前端通过 PUT + POST resume 继续执行。

- 优点：LangGraph 原生支持，状态自动保存（MemorySaver），恢复逻辑简单
- 缺点：强依赖 LangGraph checkpoint 机制

### 方案二：手动暂停（REST flag）

在 `run_meeting_pipeline()` 提前返回，让前端调 resume 时重新执行整个 Pipeline 但 skip 已完成节点。

- 优点：不依赖 LangGraph 中断机制
- 缺点：需要手动实现节点跳过逻辑，状态恢复复杂，大量重复代码

### 方案三：WebSocket 双向确认

Pipeline 执行到 Action 时通过 WebSocket 推送待办给前端，等待用户回复后继续。

- 优点：实时性好，适合远程场景
- 缺点：后端需维护 WebSocket 生命周期，前端刷新即断连，状态恢复困难

## 推荐方案

**方案一（LangGraph interrupt_before）**。理由：LangGraph 原生支持，StateGraph checkpoint 自动管理中断状态，代码改动最小。

## 详细设计

### 架构

```
Transcription → [Summary + Action(仅提取) + Insight] → ⏸ interrupt → sync_actions → FollowUp → END
                                                          ↑
                                                    人工逐条审核
                                                    前端 PUT review
                                                    前端 POST resume
```

### 关键组件

**后端变更：**

1. **拆分 ActionAgent** — `process()` 只做 LLM 提取，不调 `_sync_to_external`。新增独立 `sync_actions` 节点负责同步已确认条目。

2. **GraphState 新字段** — `review_status: Annotated[dict, ...]` 存储每条待办的审核状态。

3. **compile_meeting_graph 加 interrupt + checkpointer** — 编译时指定 `interrupt_before=["sync_actions"]`，传入 `MemorySaver` checkpointer。

4. **新增 REST 端点：**
   - `PUT /api/v1/meeting/{id}/actions/review` — 提交审核结果（逐条 review_status + 修改字段）
   - `POST /api/v1/meeting/{id}/resume` — 从中断点继续执行 sync + followup

5. **`run_meeting_pipeline` 新增 `thread_id` 参数** — 用于 checkpoint 恢复，返回值含 `status: "awaiting_review"` 时表示中断等待。

**前端变更（ActionsPanel）：**

- 每条待办：可编辑字段（任务描述、截止、优先级、负责人）、删除按钮、确认按钮
- 状态标签：pending(灰) / confirmed(绿) / deleted(灰+删除线) / modified(蓝)
- 底部「全部确认并发送」按钮 → PUT review + POST resume → 轮询 report 直到 completed

### 数据流

```
POST /upload-video → run_meeting_pipeline(thread_id="mtg-xxx")
  │
  ├─ Transcription ✅ → Summary ✅ + Action(extract) ✅ + Insight ✅
  │
  ├─ ⏸ interrupt_before=["sync_actions"]
  │   返回 state，status="awaiting_review"，action_items=[...]
  │
  │   ... 用户在前端逐条审核 ...
  │
  ├─ PUT /actions/review + body {items: [...], thread_id}
  ├─ POST /resume + body {thread_id}
  │
  ├─ sync_actions → FollowUp → END
  │
  └─ GET /report → status="completed"
```

### API 设计

**PUT /api/v1/meeting/{id}/actions/review**

Request:
```json
{
  "thread_id": "mtg-xxx",
  "items": [
    {
      "index": 0,
      "review_status": "confirmed",
      "assignee": "李明",
      "task": "负责整理Q3预算方案",
      "deadline": "2026-06-20",
      "priority": "high"
    },
    {
      "index": 1,
      "review_status": "deleted"
    },
    {
      "index": 2,
      "review_status": "modified",
      "assignee": "赵伟",
      "task": "联系服务器供应商",
      "deadline": "2026-06-18"
    }
  ]
}
```

Response:
```json
{
  "meeting_id": "mtg-xxx",
  "reviewed_count": 3,
  "status": "reviewed"
}
```

**POST /api/v1/meeting/{id}/resume**

Request:
```json
{
  "thread_id": "mtg-xxx"
}
```

Response:
```json
{
  "meeting_id": "mtg-xxx",
  "status": "syncing",
  "message": "Pipeline resumed, sync in progress"
}
```

### 异常与边界处理

| 场景 | 后端行为 | 前端表现 |
|---|---|---|
| 待办列表为空 | 正常返回，不触发中断 | 显示「无待办」，发送按钮置灰 |
| 用户关闭页面 | MemorySaver 保留 state | 重开时检测 `status!=completed`，恢复审核进度 |
| 全删待办 | `sync_actions` 跳空，正常结束 | 弹出确认提示 |
| 断网/超时 | 500 | 按钮变红 + toast 提示重试 |
| 重复 resume | 幂等检查 `jira_issue_key==""` | 按钮在完成后置换 |
| Jira/飞书部分失败 | 单条 catch，记录 errors | ✅/🔴 逐条状态 |
| 服务器重启 | MemorySaver 丢失，返回 404 | 提示「审核已过期，请重新上传」 |

### 测试策略

- **单元测试**：`sync_actions` 节点只同步 confirmed 条目
- **集成测试**：`interrupt_before` 正确中断 + PUT review + POST resume 恢复
- **前端测试**：Playwright — 编辑/删除/确认待办 + 全删确认对话框

## 风险与待确认项

- MemorySaver 不持久化，服务器重启丢失中断状态 → 生产换 SqliteSaver/Redis
- `interrupt_before` 需要 LangGraph `checkpointer` 参数，需确认版本兼容性
- 前端审核交互需要后端 `review_status` 字段精确同步
