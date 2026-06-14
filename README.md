# 🎙️ 多Agent智能会议助手

> 企业级会议全流程自动化系统 —— 从语音实时转写、多维度分析，到待办分发，5个AI Agent协作完成。

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![Vue](https://img.shields.io/badge/Vue-3.5-4FC08D.svg)](https://vuejs.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![WhisperX](https://img.shields.io/badge/WhisperX-latest-blueviolet.svg)](https://github.com/m-bain/whisperX)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 📖 目录

- [系统架构](#-系统架构)
- [核心特性](#-核心特性)
- [技术栈](#-技术栈)
- [快速开始](#-快速开始)
- [项目结构](#-项目结构)
- [API 概览](#-api-概览)
- [5-Agent Pipeline](#-5-agent-pipeline)
- [实时转写引擎](#-实时转写引擎)
- [前端界面](#-前端界面)
- [下一步计划](#-下一步计划)

---

## 🏗 系统架构

```
┌─────────────────────────────────────────────────────┐
│                    Browser (Vue 3)                   │
│  🎤 麦克风 + 🔊 系统音频 → PCM → WebSocket 实时推送  │
└────────────────────────┬────────────────────────────┘
                         │ WebSocket (ws://)
                         ▼
┌─────────────────────────────────────────────────────┐
│              FastAPI Server (Python)                 │
│                                                      │
│  ┌──────────┐   ┌────────────┐   ┌───────────────┐  │
│  │ AudioBuf │ → │ ChunkTrans │ → │ Incremental   │  │
│  │ (WebRTC  │   │ criber     │   │ Analyzer      │  │
│  │  VAD)    │   │ (WhisperX) │   │ (LLM定时分析) │  │
│  └──────────┘   └────────────┘   └───────────────┘  │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │           LangGraph 5-Agent Pipeline          │   │
│  │                                               │   │
│  │  Transcription → Summary ─┐                  │   │
│  │                → Action  ─┤→ FollowUp → END  │   │
│  │                → Insight ─┘ (Fan-in)         │   │
│  │                  (Fan-out)                     │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │   Integrations: DeepSeek | Jira | 飞书       │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 数据流

```
音频输入 → WebRTC VAD分块 → WhisperX转写 → 逐句推送前端(实时)
                                        → 累积文本 → LLM增量分析(定时)
                                                   → 最终5-Agent完整分析
```

---

## ✨ 核心特性

### 🎤 双模式输入

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| **实时会议** | 浏览器采集麦克风 + 系统音频，WebSocket 实时推流，边听边出字 | 在线会议、线下讨论 |
| **文件上传** | 上传音频/视频文件（mp3/wav/mp4/mkv等），异步处理生成报告 | 会议录音回放 |

### 🤖 5-Agent 协作 Pipeline

```
START → ① TranscriptionAgent → ② SummaryAgent    ↘
                               → ③ ActionAgent      → ⑤ FollowUpAgent → END
                               → ④ InsightAgent    ↗
                                    (并行 Fan-out)
```

| Agent | 职责 | 核心技术 |
|-------|------|---------|
| **TranscriptionAgent** | 语音转文字 + 说话人识别 | WhisperX + wav2vec2对齐 + pyannote说话人分离 |
| **SummaryAgent** | 结构化会议纪要 | LLM few-shot + 规则降级 |
| **ActionAgent** | 待办事项提取 + 同步分发 | LLM抽取 + Jira/飞书自动同步 |
| **InsightAgent** | 多维会议洞察 | 规则统计(发言占比/效率) + LLM情感/关键词分析 |
| **FollowUpAgent** | 汇聚结果 + 生成报告 | Fan-in汇聚 + Markdown报告 + 飞书推送 |

### 👤 Human-in-the-Loop（人机协同）

待办事项在自动分发前需人工审核——**这是企业级Agent系统与Demo的核心区别**：

```
ActionAgent生成待办 → ⏸ 暂停(Pending Review)
                        ↓
              用户在界面审核(编辑/确认/删除)
                        ↓
              确认后 → 同步到Jira/飞书 → 继续Pipeline
```

### ⚡ 实时增量分析

- **VAD 语音检测**：WebRTC VAD (silero)，自动切分语音/静音边界
- **增量转写**：每段语音独立转写，1-5秒出第一个chunk
- **定时LLM分析**：每10句或每60秒触发一次增量摘要/待办/洞察
- **全链路诊断**：15个检查点（①-⑮），快速定位问题

### 🔗 外部集成（可插拔）

| 集成 | 功能 | is_enabled 开关 |
|------|------|:---:|
| **DeepSeek** | LLM 推理（默认） | ✅ |
| **Jira** | 待办自动创建工单 | 🔄 自动检测凭证 |
| **飞书** | 消息推送 + 任务创建 | 🔄 自动检测凭证 |

所有外部集成都支持**优雅降级**：凭证未配置时自动切换为 Demo 模式，不阻塞主流程。

---

## 🛠 技术栈

### 后端
| 类别 | 技术 | 说明 |
|------|------|------|
| **Agent框架** | LangGraph 0.2+ | 有状态多Agent编排，Fan-out/Fan-in |
| **Web框架** | FastAPI + Uvicorn | 异步REST + WebSocket |
| **语音识别** | WhisperX (tiny→large-v2) | VAD + 转写 + 时间戳对齐 |
| **说话人分离** | pyannote-audio | Speaker embedding + 聚类 |
| **LLM** | DeepSeek (OpenAI兼容) | 可通过配置切换任意兼容模型 |
| **语音检测** | WebRTC VAD / Silero | 实时静音检测与切分 |
| **重试策略** | Tenacity | 指数退避 + 自动重试 |

### 前端
| 类别 | 技术 | 说明 |
|------|------|------|
| **框架** | Vue 3 (Composition API) | `<script setup>` + TypeScript |
| **UI组件库** | NaiveUI | 企业级组件，暗色主题友好 |
| **构建工具** | Vite 8 | 极速HMR + 生产构建 |
| **路由** | Vue Router 4 | Hash模式SPA |

### 基础设施
| 类别 | 技术 |
|------|------|
| **容器化** | Docker + Docker Compose |
| **数据库** | PostgreSQL 16 + Redis 7（规划中） |
| **Python** | 3.10+ |

---

## 🚀 快速开始

### 前置要求

- Python 3.10+
- Node.js 18+（仅前端开发需要）
- [可选] Docker & Docker Compose

### 1. 克隆项目

```bash
git clone https://github.com/2630734042-a11y/meeting-assistant.git
cd meeting-assistant
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，至少填写 LLM_API_KEY
```

必备配置：
```bash
LLM_API_KEY=sk-your-deepseek-key   # 必填：DeepSeek API Key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
```

可选配置：
```bash
WHISPER_MODEL_SIZE=tiny            # tiny/base/small/medium/large-v2
HF_ENDPOINT=https://hf-mirror.com  # 国内镜像加速模型下载
JIRA_SERVER=...                    # Jira集成（可选）
FEISHU_APP_ID=...                  # 飞书集成（可选）
```

### 3. 安装启动

```bash
cd python

# 安装依赖
pip install -e .

# 安装WhisperX（可选，未安装时自动使用Demo数据）
pip install whisperx

# 启动服务
python main.py
```

访问 `http://localhost:8000` 即可使用。

浏览器控制台和服务器终端均会输出全链路诊断日志（①-⑮），方便排查问题。

### 4. Docker 部署（推荐）

```bash
cd python
docker-compose up -d
```

---

## 📁 项目结构

```
multi-agent-meeting-assistant/
├── python/                          # Python 后端 + 前端
│   ├── src/
│   │   ├── agents/                  # 5个AI Agent
│   │   │   ├── transcription_agent.py   # 语音转写Agent
│   │   │   ├── summary_agent.py         # 摘要Agent
│   │   │   ├── action_agent.py          # 待办Agent
│   │   │   ├── insight_agent.py         # 洞察Agent
│   │   │   └── followup_agent.py        # 跟进Agent
│   │   ├── graph/
│   │   │   └── meeting_graph.py     # LangGraph编排（Fan-out/Fan-in）
│   │   ├── integrations/            # 外部服务集成
│   │   │   ├── llm_client.py            # LLM通用客户端
│   │   │   ├── jira_client.py           # Jira集成
│   │   │   └── feishu_client.py         # 飞书集成
│   │   ├── realtime/                # 实时会议引擎
│   │   │   ├── audio_buffer.py          # WebRTC VAD分块器
│   │   │   ├── chunk_transcriber.py     # 分块转写中间件
│   │   │   ├── incremental_analyzer.py  # 增量LLM分析器
│   │   │   └── session_manager.py       # WebSocket会话管理
│   │   ├── websocket/
│   │   │   └── server.py            # FastAPI + WebSocket服务
│   │   ├── models/
│   │   │   └── schemas.py           # Pydantic数据模型（40+类）
│   │   └── utils/
│   │       └── media_utils.py       # 音视频处理工具
│   ├── frontend/                    # Vue 3 前端
│   │   └── src/
│   │       ├── views/               # 4个页面
│   │       │   ├── LiveMeetingView.vue  # 实时会议
│   │       │   ├── UploadView.vue       # 文件上传
│   │       │   ├── ReportView.vue       # 会议报告
│   │       │   └── HistoryView.vue      # 历史记录
│   │       ├── components/          # 可复用组件
│   │       └── composables/         # Vue组合式函数
│   ├── static/                      # 前端构建产物
│   ├── tests/                       # 测试
│   ├── main.py                      # 启动入口
│   ├── Dockerfile
│   └── docker-compose.yml
├── docs/                            # 文档
│   ├── architecture/                # 架构文档
│   ├── interview/                   # 面试考点
│   └── superpowers/                 # 设计规格 & 实现计划
└── reproduce/                       # 教学复现场景（从零构建）
```

---

## 🔌 API 概览

### WebSocket

| 端点 | 说明 |
|------|------|
| `ws://host/ws/live/{meeting_id}` | 实时会议：发送PCM音频 + start/stop消息，接收转写/摘要/待办推送 |

### REST API

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/v1/upload` | 上传音频/视频文件 |
| `GET` | `/api/v1/meeting/{id}/status` | 查询会议处理状态 |
| `GET` | `/api/v1/meeting/demo/{id}` | 生成Demo会议报告 |
| `POST` | `/api/v1/meeting/{id}/review` | 提交待办审核结果（HITL） |
| `POST` | `/api/v1/transcribe` | 音频转写（独立接口） |

---

## 🤖 5-Agent Pipeline

### 设计哲学

每个 Agent 都实现了**三层降级策略**：

```
Level 1: LLM推理（最佳质量）
   ↓ 失败/不可用
Level 2: 规则引擎（可解释、确定性输出）
   ↓ 失败
Level 3: Demo数据（优雅降级、不阻塞Pipeline）
```

### LangGraph 编排

```python
# Fan-out 并行执行
graph.add_node("transcription", transcription_agent.process)
graph.add_node("summary", summary_agent.process)
graph.add_node("action", action_agent.process)
graph.add_node("insight", insight_agent.process)

# 并行分发
graph.add_edge("transcription", "summary")
graph.add_edge("transcription", "action")
graph.add_edge("transcription", "insight")

# Human-in-the-Loop 审核点
graph.compile(interrupt_before=["sync_actions"])
```

### 状态管理

使用 TypedDict 定义 `MeetingState`，包含：
- `transcript` — 带时间戳和说话人的转写段
- `summary` — 结构化会议纪要
- `actions` — 待办事项列表（含审核状态）
- `insights` — 发言统计 + 情绪 + 关键词
- `errors` — 各节点错误聚合（`operator.add` 累加）

---

## 🎧 实时转写引擎

### 三协程并发模型

```
┌─ receive_loop  ─┐   ┌─ transcribe_loop ─┐   ┌─ analyze_timer_loop ─┐
│                  │   │                    │   │                      │
│ WebSocket接收    │   │ buffer.process()   │   │ 每60秒或10句触发      │
│  → buffer.feed() │   │  → VAD切分chunk   │   │  → LLM增量分析       │
│  → stop消息路由  │   │  → WhisperX转写    │   │  → 推送摘要/待办     │
│                  │   │  → 逐句推送前端    │   │                      │
└──────────────────┘   └────────────────────┘   └──────────────────────┘
       asyncio.create_task()    asyncio.create_task()
```

### 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| VAD引擎 | WebRTC VAD (silero) | 实时、轻量、离线可用 |
| 转写模型 | WhisperX tiny → large-v2 | 可配置，tiny适合实时CPU场景 |
| 分块策略 | 静音800ms切分 + 最长5秒强制切分 | 平衡延迟与上下文完整性 |
| PCM传输 | 直接numpy → WhisperX | 绕过ffmpeg，减少延迟与依赖 |
| 时序处理 | `try/except TimeoutError` 在循环内 | 避免1秒无音频即断开连接 |

---

## 🖥 前端界面

| 页面 | 路由 | 功能 |
|------|------|------|
| **实时会议** | `#/live/:meetingId` | 双路音频采集、实时转写流、增量分析面板 |
| **文件上传** | `#/upload` | 拖拽上传、音视频格式自动检测、Demo模式 |
| **会议报告** | `#/report/:meetingId` | 4Tab：转写/摘要/待办/洞察，支持审核操作 |
| **历史记录** | `#/history` | 本地存储的会议历史列表 |

### 实时会议界面

```
┌──────────────────────────────────────────────┐
│  🔴 会议进行中  🎙+🔊 双路    00:05:23      │
│  · 23 句 · 4 人发言                          │
├────────────────────┬─────────────────────────┤
│  📝 实时转写 (55%) │  📋 实时摘要             │
│                    │  (增量更新)              │
│  张总 Q3预算评审... │                         │
│  李明 执行率87%...  │  📌 待办事项             │
│  王芳 有个建议...   │  (HITL审核)             │
│  ▊                 │                         │
│                    │  💡 会议洞察             │
│                    │  (发言统计/情绪)          │
├────────────────────┴─────────────────────────┤
│              ⏹ 结束会议                       │
└──────────────────────────────────────────────┘
```

---

## 📋 下一步计划

- [ ] **数据库持久化** — PostgreSQL 存储会议历史，Redis 缓存 session 状态
- [ ] **认证鉴权** — JWT + API Key 双重认证
- [ ] **测试覆盖** — Agent 单元测试 + E2E 测试，目标 80% 覆盖率
- [ ] **多租户** — 用户隔离、配额管理
- [ ] **更多集成** — 企业微信、钉钉、Notion、Slack
- [ ] **流式LLM** — SSE 流式输出摘要/洞察，减少等待
- [ ] **移动端适配** — PWA 或 React Native

---

## 📄 License

MIT License

---

<p align="center">
  <b>Built with ❤️ by Contributors</b><br>
  <sub>架构设计 | Agent编排 | 实时流处理 | 人机协同</sub>
</p>
