# 教程 04 - 会议系统实战

> 一步步搭建完整的多Agent会议助手

---

## 系统全貌

```
音频 → [Transcription] → [Summary|Action|Insight] → [Follow-up] → 飞书通知
```

本教程将逐步实现每个模块。

---

## Step 1: 数据模型

首先定义所有的数据结构（`models/schemas.py`）：

- `TranscriptSegment`: 谁说了什么（说话人+文本+时间戳）
- `MeetingSummary`: 结构化纪要（议题+讨论+结论）
- `ActionItem`: 待办事项（谁+做什么+截止时间）
- `MeetingInsight`: 会议洞察（情绪+发言统计+效率评分）

每个模型使用 Pydantic，支持自动验证和JSON序列化。

---

## Step 2: 实现每个 Agent

### Transcription Agent

核心流程:
1. 接收音频字节
2. WhisperX 转写（或使用演示数据）
3. pyannote 说话人识别
4. 合并结果写入 state

### Summary Agent

核心流程:
1. 读取 transcript_text
2. 构造 Prompt（System + JSON Schema + 数据）
3. 调用 LLM
4. 解析 JSON 结果
5. 写入 state.summary

### Action Agent

核心流程:
1. 读取 transcript_text
2. LLM 提取行动项三元组
3. 同步到 Jira（创建 Issue）
4. 同步到飞书（创建任务）
5. 写入 state.actions

### Insight Agent

核心流程:
1. 规则引擎：计算发言统计（确定性）
2. LLM：情绪分析和关键词提取（AI）
3. 综合评分算法
4. 写入 state.insights

### Follow-up Agent

核心流程:
1. 汇聚三个Agent的结果
2. 格式化 Markdown
3. 推送飞书消息
4. 设置定时提醒

---

## Step 3: LangGraph 编排

在 `graph/meeting_graph.py` 中：

```python
graph = StateGraph(GraphState)

# 注册 5 个 Node
graph.add_node("transcription", transcription_agent.process)
graph.add_node("summary", summary_agent.process)
graph.add_node("action", action_agent.process)
graph.add_node("insight", insight_agent.process)
graph.add_node("followup", followup_agent.process)

# 定义 Edge
graph.add_edge(START, "transcription")      # 串行
graph.add_edge("transcription", "summary")  # 并行
graph.add_edge("transcription", "action")
graph.add_edge("transcription", "insight")
graph.add_edge("summary", "followup")       # 汇聚
graph.add_edge("action", "followup")
graph.add_edge("insight", "followup")
graph.add_edge("followup", END)
```

---

## Step 4: WebSocket 服务

FastAPI 提供两种接入方式:

1. **WebSocket**: 实时音频流
2. **REST API**: 文件上传 + 结果查询

---

## Step 5: 测试运行

```bash
# 启动服务
cd python
python -m src.main

# 演示模式（无需音频）
curl -X POST http://localhost:8000/api/v1/meeting/demo/demo

# 查看结果
curl http://localhost:8000/api/v1/meeting/demo/report
```

---

下一篇: [05 - 部署上线](05-deployment.md)
