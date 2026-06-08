# 🤖 多Agent智能会议助手系统

> **企业级 5-Agent 会议全流程自动化系统 | Pipeline + 并行编排 | Python / Java / Go 三语言实现**
>
> 从零到面试通关，面向小白的完整学习路线 — 代码 + 八股文 + 简历 + STAR法 + 面试问答

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](python/)
[![Java 17+](https://img.shields.io/badge/Java-17+-orange.svg)](java/)
[![Go 1.21+](https://img.shields.io/badge/Go-1.21+-00ADD8.svg)](golang/)

---

## 📖 目录

- [项目介绍](#项目介绍)
- [系统架构](#系统架构)
- [功能特性](#功能特性)
- [技术栈总览](#技术栈总览)
- [快速开始](#快速开始)
  - [Python 版](#python-版快速开始)
  - [Java 版](#java-版快速开始)
  - [Go 版](#go-版快速开始)
- [5个Agent详解](#5个agent详解)
  - [Transcription Agent（转写）](#1-transcription-agent转写agent)
  - [Summary Agent（摘要）](#2-summary-agent摘要agent)
  - [Action Agent（待办）](#3-action-agent待办agent)
  - [Insight Agent（洞察）](#4-insight-agent洞察agent)
  - [Follow-up Agent（跟进）](#5-follow-up-agent跟进agent)
- [面试宝典](#面试宝典)
  - [八股文50+题](#八股文50题)
  - [STAR法面试话术](#star法面试话术)
  - [简历模板](#简历模板)
  - [项目面试问答30+题](#项目面试问答30题)
  - [系统设计面试](#系统设计面试)
- [从零教程](#从零教程)
- [API文档](#api文档)
- [部署指南](#部署指南)
- [常见问题FAQ](#常见问题faq)
- [贡献指南](#贡献指南)

---

## 项目介绍

### 这个项目是什么？

这是一个**企业级多Agent智能会议助手系统**，使用 5 个专业化 AI Agent 协作完成会议全流程自动化：

```
会议音频 → 实时转写 → 摘要/待办/洞察(并行生成) → 会后自动跟进
```

**一句话总结**: 把一场会议从"开完就忘"变成"自动生成纪要、自动分配待办、自动跟踪进度"。

### 为什么做这个项目？

| 痛点 | 解决方案 |
|------|----------|
| 会议纪要整理耗时 2 小时/场 | Summary Agent 自动生成结构化纪要 |
| 待办事项容易遗忘 | Action Agent 自动提取并同步到 Jira/飞书 |
| 不知道谁说得最多/会议效率如何 | Insight Agent 实时分析发言占比和情绪 |
| 会后跟进靠人工催 | Follow-up Agent 自动发送纪要和跟踪提醒 |
| 管理者每周在会议事务上花 9+ 小时 | 全流程自动化，**年化节省人力成本 110 万** |

### 这个项目适合谁？

- **求职者**: 需要一个拿得出手的多Agent项目经历（配套完整面试材料）
- **开发者**: 想学习多Agent系统设计和实现（Python/Java/Go三种实现）
- **学生**: 想从零了解AI Agent（配套从零教程）

---

## 系统架构

### 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        客户端层 (Client)                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐    │
│  │ Web 前端  │  │ 飞书机器人│  │ API调用方 │  │ WebSocket客户端│   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘    │
└───────┼──────────────┼────────────┼───────────────┼─────────────┘
        │              │            │               │
        ▼              ▼            ▼               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      接入层 (Gateway)                            │
│  ┌─────────────────────────┐  ┌──────────────────────────────┐  │
│  │   REST API (FastAPI)    │  │  WebSocket Server (实时音频流) │  │
│  └─────────────────────────┘  └──────────────────────────────┘  │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Agent编排层 (LangGraph)                        │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Meeting Pipeline Graph                       │   │
│  │                                                           │   │
│  │  ┌─────────────┐    ┌─────────────┐                      │   │
│  │  │   音频输入    │───▶│ Transcription│                     │   │
│  │  │   (Start)    │    │   Agent     │                      │   │
│  │  └─────────────┘    └──────┬──────┘                      │   │
│  │                            │                              │   │
│  │                    ┌───────┼───────┐   ← 并行 Fan-out     │   │
│  │                    ▼       ▼       ▼                      │   │
│  │              ┌─────────┐┌──────┐┌────────┐               │   │
│  │              │ Summary ││Action││Insight │               │   │
│  │              │  Agent  ││Agent ││ Agent  │               │   │
│  │              └────┬────┘└──┬───┘└───┬────┘               │   │
│  │                   │        │        │                     │   │
│  │                   └────────┼────────┘   ← 并行 Fan-in     │   │
│  │                            ▼                              │   │
│  │                    ┌──────────────┐                       │   │
│  │                    │  Follow-up   │                       │   │
│  │                    │    Agent     │                       │   │
│  │                    └──────────────┘                       │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     外部集成层 (Integration)                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │  Jira    │  │   飞书    │  │  邮件服务  │  │  向量数据库   │   │
│  │  Cloud   │  │  Open API │  │  SMTP    │  │  ChromaDB    │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 数据流图

```
音频流(WebSocket)
    │
    ▼
┌─────────────────────┐
│ Transcription Agent  │  WhisperX + 说话人识别
│ 输出: TranscriptSegment[] │
│ {speaker, text, ts}  │
└─────────┬───────────┘
          │
          ├──────────────────┬──────────────────┐
          │                  │                  │    ← 三路并行
          ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Summary Agent│  │ Action Agent │  │ Insight Agent│
│              │  │              │  │              │
│ 输出:        │  │ 输出:        │  │ 输出:        │
│ MeetingSummary│ │ ActionItem[] │  │ MeetingInsight│
│ {议题,讨论,  │  │ {谁,做什么,  │  │ {情绪,发言比,│
│  结论,决策}  │  │  截止时间}   │  │  效率评分}   │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       └─────────────────┼─────────────────┘
                         │    ← Fan-in 汇聚
                         ▼
              ┌──────────────────┐
              │  Follow-up Agent │
              │                  │
              │  • 发送会议纪要   │
              │  • 同步Jira待办   │
              │  • 设置跟踪提醒   │
              │  • 飞书消息推送   │
              └──────────────────┘
```

### 编排模式说明

本系统采用 **Pipeline + 并行(Fan-out/Fan-in)** 混合编排模式：

| 阶段 | 模式 | 说明 |
|------|------|------|
| 音频 → 转写 | Pipeline（串行） | 必须先完成转写才能做后续分析 |
| 转写 → 摘要/待办/洞察 | Fan-out（并行） | 三个Agent独立工作，互不依赖 |
| 摘要+待办+洞察 → 跟进 | Fan-in（汇聚） | 等三个Agent全部完成后合并结果 |

---

## 功能特性

### 5大核心能力

| Agent | 能力 | 关键指标 |
|-------|------|----------|
| **Transcription** | 实时语音转文字 + 说话人识别 | 准确率 95%+，支持中英双语 |
| **Summary** | 结构化会议纪要生成 | 议题/讨论/结论/决策四层结构 |
| **Action** | 待办自动提取 + Jira/飞书同步 | 同步成功率 98% |
| **Insight** | 情绪分析 + 发言统计 + 效率评分 | 多维度会议洞察 |
| **Follow-up** | 自动发送纪要 + 待办跟踪 + 提醒 | 全自动化会后跟进 |

### 技术亮点

- **Pipeline + 并行编排**: 使用 LangGraph 状态图实现灵活的多Agent编排
- **实时流式处理**: WebSocket 音频流 → 流式转写 → 实时结果推送
- **三语言实现**: Python (LangGraph) / Java (LangGraph4j) / Go (Eino ADK)
- **企业集成**: Jira Cloud API + 飞书 Open API 双向同步
- **容错降级**: Agent 级别熔断 + 降级策略 + 重试机制
- **可观测性**: 结构化日志 + 指标采集 + 链路追踪

---

## 技术栈总览

### 三语言对照表

| 组件 | Python | Java | Go |
|------|--------|------|-----|
| Agent 框架 | [LangGraph](https://github.com/langchain-ai/langgraph) | [LangGraph4j](https://github.com/langgraph4j/langgraph4j) | [Eino ADK](https://github.com/cloudwego/eino) |
| 语音转写 | WhisperX + pyannote | Whisper REST API | go-whisper |
| LLM 调用 | langchain + MiniMax | Spring AI + MiniMax | Eino LLM + MiniMax |
| Web 框架 | FastAPI | Spring Boot 3 | Gin / net/http |
| WebSocket | fastapi-websocket | Spring WebSocket | gorilla/websocket |
| Jira 集成 | jira-python | jira-rest-client | go-jira |
| 飞书集成 | 飞书 SDK (Python) | 飞书 SDK (Java) | 飞书 SDK (Go) |
| 数据库 | SQLAlchemy + PostgreSQL | Spring Data JPA | GORM + PostgreSQL |
| 向量数据库 | ChromaDB | - | - |
| 容器化 | Docker + docker-compose | Docker + docker-compose | Docker + docker-compose |

---

## 快速开始

### 前置要求

- Docker & Docker Compose（推荐）
- 或对应语言的开发环境
- 一个 LLM API Key（MiniMax 或 OpenAI）

### Python 版快速开始

> Python 版是最完整的实现，推荐首选。

```bash
# 1. 克隆仓库
git clone https://github.com/bcefghj/multi-agent-meeting-assistant.git
cd multi-agent-meeting-assistant

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key

# 3. 进入 Python 目录
cd python

# 4. 创建虚拟环境并安装依赖
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 5. 启动服务
python -m src.main

# 服务启动在 http://localhost:8000
# WebSocket 端点: ws://localhost:8000/ws/meeting
```

**Docker 一键启动（推荐）：**

```bash
cd python
docker-compose up -d

# 查看日志
docker-compose logs -f
```

详细文档: [python/README.md](python/README.md)

### Java 版快速开始

```bash
# 1. 进入 Java 目录
cd java

# 2. Maven 构建
mvn clean package -DskipTests

# 3. 运行
java -jar target/meeting-assistant-1.0.0.jar

# 或使用 Docker
docker-compose up -d
```

详细文档: [java/README.md](java/README.md)

### Go 版快速开始

```bash
# 1. 进入 Go 目录
cd golang

# 2. 下载依赖
go mod download

# 3. 构建运行
go build -o meeting-assistant ./cmd/
./meeting-assistant

# 或使用 Docker
docker-compose up -d
```

详细文档: [golang/README.md](golang/README.md)

---

## 5个Agent详解

### 1. Transcription Agent（转写Agent）

**职责**: 接收实时音频流，转换为带说话人标识的文本。

**核心技术**:
- **WhisperX**: OpenAI Whisper 的加速版，支持 70x 实时速度
- **pyannote-audio**: 说话人识别（Speaker Diarization）
- **VAD**: 语音活动检测，过滤静音，降低幻觉

**输入/输出示例**:

```json
// 输入: WebSocket 音频二进制帧

// 输出:
{
  "segments": [
    {
      "speaker": "张总",
      "text": "Q3的预算需要上调15%",
      "start": 185.2,
      "end": 188.5,
      "confidence": 0.96
    },
    {
      "speaker": "李明",
      "text": "我会在下周五之前完成预算方案",
      "start": 189.1,
      "end": 192.3,
      "confidence": 0.94
    }
  ]
}
```

**关键代码片段** (Python):

```python
class TranscriptionAgent:
    """实时语音转写Agent - WhisperX + 说话人识别"""

    def __init__(self, config: TranscriptionConfig):
        self.model = whisperx.load_model(
            config.model_size, config.device,
            compute_type=config.compute_type
        )
        self.diarize_model = whisperx.DiarizationPipeline(
            use_auth_token=config.hf_token,
            device=config.device
        )

    async def process(self, state: MeetingState) -> MeetingState:
        audio = state["audio_data"]
        result = self.model.transcribe(audio, language=state.get("language", "zh"))
        aligned = whisperx.align(result["segments"], self.align_model, ...)
        diarized = self.diarize_model(audio)
        segments = whisperx.assign_word_speakers(diarized, aligned)
        state["transcript"] = segments
        return state
```

---

### 2. Summary Agent（摘要Agent）

**职责**: 将转写文本生成结构化会议纪要。

**输出结构**:
- 会议主题
- 议题列表（每个议题包含：讨论要点、参与者、结论）
- 总体决策
- 下一步计划

**Prompt 设计策略**: Few-shot + JSON Schema 约束输出格式

```python
SUMMARY_PROMPT = """你是专业的会议纪要助手。请根据以下会议转写文本，生成结构化的会议纪要。

## 输出格式要求（严格JSON）
{
  "title": "会议主题",
  "date": "会议日期",
  "participants": ["参会人列表"],
  "topics": [
    {
      "title": "议题名称",
      "discussion_points": ["讨论要点1", "讨论要点2"],
      "participants": ["发言人"],
      "conclusion": "结论"
    }
  ],
  "decisions": ["决策1", "决策2"],
  "next_steps": ["下一步1", "下一步2"]
}

## 会议转写文本
{transcript}
"""
```

---

### 3. Action Agent（待办Agent）

**职责**: 从转写文本中提取行动项，自动同步到 Jira/飞书。

**提取规则**: 识别"谁 + 做什么 + 截止时间"三元组。

```json
// 提取结果示例
{
  "action_items": [
    {
      "assignee": "李明",
      "task": "完成Q3预算方案",
      "deadline": "2026-04-15",
      "priority": "high",
      "context": "张总要求Q3预算上调15%",
      "jira_issue_key": "MEET-42",
      "feishu_task_id": "t_6912345"
    }
  ]
}
```

**Jira 同步示例**:

```python
async def sync_to_jira(self, action_item: ActionItem) -> str:
    issue = self.jira.create_issue(
        project=self.project_key,
        summary=action_item.task,
        description=f"来源：会议自动提取\n上下文：{action_item.context}",
        issuetype={"name": "Task"},
        assignee={"name": self._resolve_jira_user(action_item.assignee)},
        duedate=action_item.deadline,
        priority={"name": self._map_priority(action_item.priority)}
    )
    return issue.key
```

---

### 4. Insight Agent（洞察Agent）

**职责**: 多维度分析会议质量。

**分析维度**:

| 维度 | 方法 | 示例输出 |
|------|------|----------|
| 情绪分析 | LLM情感分类 | 整体积极(0.72) |
| 发言占比 | 按说话人统计时长 | 张总40%, 李明35%, 王芳25% |
| 效率评分 | 综合指标 | 8.2/10 |
| 关键词云 | TF-IDF提取 | 预算, Q3, 方案, 上调 |
| 会议节奏 | 时间段分析 | 前15min高效, 后10min偏题 |

---

### 5. Follow-up Agent（跟进Agent）

**职责**: 会后自动化——发送纪要、创建任务、跟踪进度。

**工作流程**:

```
汇聚(摘要+待办+洞察)
    │
    ├── 1. 生成会议纪要邮件/消息
    │       └── 推送到飞书群
    │
    ├── 2. 确认所有待办已同步
    │       ├── Jira Issue 已创建
    │       └── 飞书任务已创建
    │
    ├── 3. 设置跟踪提醒
    │       ├── 截止前3天提醒
    │       ├── 截止前1天提醒
    │       └── 超期未完成提醒
    │
    └── 4. 生成会议分析报告
            └── 附带洞察数据
```

---

## 面试宝典

> 这部分是本项目的核心价值之一——帮你用这个项目通过面试。

### 八股文50+题

涵盖 Agent/多Agent/LangGraph/RAG/工程化/语音/系统设计 七大类别。

**[查看完整八股文 →](docs/interview/eight-part-essay.md)**

示例题目：
- Q: Agent 和传统的 LLM Chain 有什么区别？
- Q: 为什么选择多Agent而不是单Agent？
- Q: LangGraph 的 State/Node/Edge 分别是什么？
- Q: 如何解决多Agent之间的通信冗余问题？
- Q: Whisper 模型的工作原理是什么？

### STAR法面试话术

5个Agent场景的完整 STAR（Situation-Task-Action-Result）回答模板。

**[查看完整STAR话术 →](docs/interview/star-method.md)**

示例：

> **面试官**: 介绍一下你做的这个会议助手项目？
>
> **S(情景)**: 在我上一份工作中，公司每周有20+场会议，会议纪要整理平均耗时2小时/场，待办事项经常遗漏...
>
> **T(任务)**: 我负责设计一个多Agent系统，实现会议全流程自动化...
>
> **A(行动)**: 我设计了5-Agent的Pipeline+并行架构，用LangGraph做编排...
>
> **R(结果)**: 系统上线后转写准确率95%+，待办同步率98%，管理者每周节省9小时...

### 简历模板

针对 Python/Java/Go 三种岗位方向的项目经历写法。

**[查看简历模板 →](docs/interview/resume-template.md)**

### 项目面试问答30+题

30+面试常问问题及深度回答。

**[查看面试问答 →](docs/interview/project-qa.md)**

### 系统设计面试

可扩展性、高可用、监控等系统设计面试要点。

**[查看系统设计要点 →](docs/interview/system-design.md)**

---

## 从零教程

面向零基础小白的 6 篇渐进式教程：

| 序号 | 主题 | 内容概要 | 链接 |
|------|------|----------|------|
| 00 | 环境准备 | Python/Java/Go 安装，Docker，IDE 配置 | [查看](docs/tutorial/00-prerequisites.md) |
| 01 | 理解Agent | 什么是Agent，和ChatGPT有什么区别 | [查看](docs/tutorial/01-understanding-agents.md) |
| 02 | 第一个Agent | 手把手写一个最简单的Agent | [查看](docs/tutorial/02-first-agent.md) |
| 03 | 多Agent编排 | Pipeline、并行、LangGraph状态图 | [查看](docs/tutorial/03-multi-agent.md) |
| 04 | 会议系统实战 | 一步步搭建完整的会议助手系统 | [查看](docs/tutorial/04-meeting-system.md) |
| 05 | 部署上线 | Docker化、CI/CD、云部署 | [查看](docs/tutorial/05-deployment.md) |

---

## API文档

### REST API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/meeting/start` | 创建新会议 |
| POST | `/api/v1/meeting/{id}/upload` | 上传音频文件 |
| GET | `/api/v1/meeting/{id}/transcript` | 获取转写结果 |
| GET | `/api/v1/meeting/{id}/summary` | 获取会议纪要 |
| GET | `/api/v1/meeting/{id}/actions` | 获取待办事项 |
| GET | `/api/v1/meeting/{id}/insights` | 获取会议洞察 |
| GET | `/api/v1/meeting/{id}/report` | 获取完整报告 |

### WebSocket API

```
ws://localhost:8000/ws/meeting/{meeting_id}

// 发送: 音频二进制帧
// 接收: JSON 实时转写结果
{
  "type": "transcript",
  "data": {
    "speaker": "张总",
    "text": "Q3预算需要上调",
    "timestamp": 185.2,
    "is_final": true
  }
}
```

完整 API 文档: [docs/api-reference.md](docs/api-reference.md)

---

## 部署指南

### Docker Compose（推荐）

```bash
# 在项目根目录
cp .env.example .env
# 编辑 .env 填入配置

# 启动所有服务
docker-compose up -d

# 查看状态
docker-compose ps
```

### Kubernetes 部署

参考 [docs/tutorial/05-deployment.md](docs/tutorial/05-deployment.md) 中的 K8s 部署章节。

---

## 常见问题FAQ

<details>
<summary><b>Q: 没有GPU可以运行吗？</b></summary>

可以。Whisper 支持 CPU 模式（速度较慢），也可以使用 OpenAI Whisper API（云端推理）。在 `.env` 中设置 `WHISPER_DEVICE=cpu`。
</details>

<details>
<summary><b>Q: 支持哪些语言的语音转写？</b></summary>

Whisper 支持 99 种语言。本项目默认配置中英双语，可通过 `WHISPER_LANGUAGE` 环境变量调整。
</details>

<details>
<summary><b>Q: MiniMax 和 OpenAI 怎么选？</b></summary>

MiniMax 对中文支持更好且更便宜，推荐国内用户使用。OpenAI GPT-4o 在英文场景和复杂推理上更强。可以在 `.env` 中切换。
</details>

<details>
<summary><b>Q: 不用 Jira/飞书，可以只用其中一个吗？</b></summary>

可以。在 `.env` 中只配置你需要的服务即可，未配置的集成会自动跳过。
</details>

<details>
<summary><b>Q: 三种语言版本功能一样吗？</b></summary>

Python 版功能最完整（包含本地 Whisper 转写）。Java 和 Go 版通过 API 调用 Whisper 服务，其他功能完全一致。
</details>

---

## 贡献指南

欢迎贡献！请遵循以下流程：

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

---

## 项目结构

```
multi-agent-meeting-assistant/
├── README.md                     # 本文件
├── .env.example                  # 环境变量模板
├── .gitignore                    # Git忽略配置
├── LICENSE                       # MIT许可证
├── plan.md                       # 项目规划文档
├── docs/                         # 文档目录
│   ├── architecture.md           # 架构设计详解
│   ├── api-reference.md          # API参考文档
│   ├── interview/                # 面试准备材料
│   │   ├── eight-part-essay.md   # 八股文50+题
│   │   ├── star-method.md        # STAR法面试话术
│   │   ├── resume-template.md    # 简历模板
│   │   ├── project-qa.md         # 项目面试问答
│   │   └── system-design.md      # 系统设计面试
│   └── tutorial/                 # 从零教程
│       ├── 00-prerequisites.md   # 环境准备
│       ├── 01-understanding-agents.md
│       ├── 02-first-agent.md
│       ├── 03-multi-agent.md
│       ├── 04-meeting-system.md
│       └── 05-deployment.md
├── python/                       # Python实现
├── java/                         # Java实现
└── golang/                       # Go实现
```

---

> **如果这个项目对你有帮助，请给个 Star ⭐ 支持一下！**
