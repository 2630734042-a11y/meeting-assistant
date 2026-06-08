# 项目架构总览

## 1. 项目基本信息

| 项目 | 内容 |
|------|------|
| 名称 | 多Agent智能会议助手系统 (Multi-Agent Meeting Assistant) |
| 技术栈 | Python (LangGraph + FastAPI + WhisperX + ChromaDB) |
| 语言版本 | Python (已实现) / Java (规划中) / Go (规划中) |
| 构建方式 | pip + Docker / docker-compose |
| 核心架构 | 5-Agent Pipeline + 并行(Fan-out/Fan-in) 编排 |
| LLM | MiniMax M2.7 / OpenAI GPT-4o (可切换) |
| 目标用户 | 求职者(面试项目)、开发者(学习多Agent)、学生(从零入门) |

## 2. 目录结构分析

| 目录 | 功能 | 类型 | 依赖关系 |
|------|------|------|----------|
| `python/src/agents/` | 5个AI Agent的实现 | 核心业务 | 依赖 graph、integrations、models |
| `python/src/graph/` | LangGraph 状态图编排 | 编排引擎 | 依赖 agents |
| `python/src/integrations/` | Jira/飞书/MiniMax 外部集成 | 基础设施 | 被 agents 依赖 |
| `python/src/websocket/` | WebSocket 实时音频流服务 | 接入层 | 依赖 agents、graph |
| `python/src/models/` | Pydantic 数据模型/Schema | 数据层 | 被所有模块依赖 |
| `python/src/main.py` | FastAPI 应用入口 | 启动层 | 依赖所有模块 |
| `docs/` | 架构文档、面试材料、教程 | 文档 | 无代码依赖 |
| `docs/interview/` | 八股文、STAR法、简历、面试问答 | 面试准备 | 无代码依赖 |
| `docs/tutorial/` | 6篇从零到一渐进教程 | 学习材料 | 无代码依赖 |

> **注意**: `java/` 和 `golang/` 目录在当前版本中尚未实现，README 和 plan.md 中描述了它们的规划结构。本次学习将以 Python 版为主线。

## 3. 模块关系

```
main.py (FastAPI 入口)
  ├── websocket/server.py      ← 实时音频流接入
  │     └── graph/meeting_graph.py  ← LangGraph 编排引擎
  │           ├── agents/transcription_agent.py  [Pipeline 阶段1]
  │           └── agents/summary_agent.py         [Fan-out 并行]
  │           └── agents/action_agent.py          [Fan-out 并行]
  │           └── agents/insight_agent.py         [Fan-out 并行]
  │                 └── agents/followup_agent.py  [Fan-in 汇聚]
  ├── integrations/
  │     ├── jira_client.py     ← Jira Cloud API
  │     ├── feishu_client.py   ← 飞书 Open API
  │     └── minimax_client.py  ← LLM 调用
  └── models/                  ← 数据模型(Pydantic)
```

### 核心编排模式

```
音频流 → Transcription Agent (串行)
              │
     ┌────────┼────────┐
     ▼        ▼        ▼
  Summary  Action  Insight   (三路并行)
     └────────┼────────┘
              ▼
         Follow-up Agent      (汇聚)
```

## 4. 五个 Agent 职责一览

| Agent | 职责 | 输入 | 输出 | 核心技术 |
|-------|------|------|------|----------|
| Transcription | 实时语音转文字+说话人识别 | WebSocket 音频帧 | TranscriptSegment[] | WhisperX + pyannote |
| Summary | 生成结构化会议纪要 | 转写文本 | MeetingSummary (议题/讨论/结论/决策) | Few-shot + JSON Schema |
| Action | 提取待办+同步Jira/飞书 | 转写文本 | ActionItem[] (谁/做什么/截止) | NER + Jira/飞书 API |
| Insight | 会议质量多维分析 | 转写文本+音频特征 | MeetingInsight (情绪/发言比/效率) | LLM情感分析 + 规则统计 |
| Follow-up | 会后自动化跟进 | 前三个Agent的输出 | 飞书消息+提醒任务 | 消息推送 + 定时调度 |

## 5. 当前解析状态

- [x] 已解析目录: `python/`, `docs/`
- [x] 顶层文件: `README.md`, `plan.md`, `.env.example`, `requirements.txt`
- [ ] 未解析目录(TODO): `python/src/agents/`（5个Agent实现）
- [ ] 未解析目录(TODO): `python/src/graph/`（LangGraph编排）
- [ ] 未解析目录(TODO): `python/src/integrations/`（外部集成）
- [ ] 未解析目录(TODO): `python/src/websocket/`（实时通信）
- [ ] 未解析目录(TODO): `docs/interview/`、`docs/tutorial/`（面试材料与教程）

## 6. 推荐学习路径

基于该项目的结构，推荐以下渐进式学习路径：

1. **python/src/main.py** — 先看懂入口和整体启动流程
2. **python/src/graph/meeting_graph.py** — 理解 LangGraph 编排引擎（Pipeline + 并行）
3. **python/src/agents/** — 逐个深入 5 个 Agent 的实现
4. **python/src/integrations/** — 了解外部系统集成方式
5. **python/src/websocket/** — 理解实时音频流处理

如果需要面试准备，可以同时阅读 `docs/interview/` 下的材料。
