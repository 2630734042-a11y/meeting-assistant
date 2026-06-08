# 架构设计详解

## 1. 整体架构

### 1.1 系统分层

```
┌─────────────────────────────────────────┐
│           接入层 (Gateway)               │
│  REST API / WebSocket / Webhook         │
├─────────────────────────────────────────┤
│           编排层 (Orchestration)         │
│  LangGraph / CompletableFuture / goroutine│
├─────────────────────────────────────────┤
│           Agent层 (Agents)              │
│  Transcription / Summary / Action /     │
│  Insight / Follow-up                    │
├─────────────────────────────────────────┤
│           集成层 (Integration)           │
│  LLM API / Jira / 飞书 / Whisper       │
├─────────────────────────────────────────┤
│           数据层 (Storage)              │
│  PostgreSQL / ChromaDB / Redis          │
└─────────────────────────────────────────┘
```

### 1.2 编排模式详解

本系统采用 **Pipeline + 并行(Fan-out/Fan-in)** 混合编排：

```
START → [Transcription] → Fan-out → [Summary | Action | Insight] → Fan-in → [Follow-up] → END
```

**为什么选择这种模式？**

| 模式 | 优点 | 适用场景 |
|------|------|----------|
| Pipeline（串行） | 简单可靠，前后依赖明确 | 音频→转写（必须先转写） |
| Fan-out（并行） | 减少总延迟，独立Agent互不干扰 | 摘要/待办/洞察（互相独立） |
| Fan-in（汇聚） | 等待所有结果后统一处理 | 跟进Agent需要所有数据 |

## 2. 数据流设计

### 2.1 状态驱动架构

核心设计思想：**所有Agent共享一个状态对象（MeetingState）**。

```
MeetingState = {
  meeting_id,      ← 全局标识
  audio_data,      ← 输入
  transcript,      ← TranscriptionAgent 写入
  transcript_text, ← TranscriptionAgent 写入
  summary,         ← SummaryAgent 写入（并行）
  actions,         ← ActionAgent 写入（并行）
  insights,        ← InsightAgent 写入（并行）
  followup,        ← FollowUpAgent 写入
  errors,          ← 所有Agent都可写入
}
```

**关键设计决策：**
- 每个Agent只读自己需要的字段，只写自己负责的字段
- 并行Agent写入不同字段，避免冲突
- 错误追加到errors数组，不中断Pipeline

### 2.2 并行安全

| 语言 | 并行机制 | 冲突处理 |
|------|----------|----------|
| Python | LangGraph 内置并行 | 框架自动合并 |
| Java | CompletableFuture | 状态副本 + 合并 |
| Go | goroutine + WaitGroup | sync.Mutex 保护写入 |

## 3. 容错设计

### 3.1 Agent级别容错

```
每个Agent的process方法:
  try:
    执行核心逻辑
  except:
    记录错误到 state.errors
    写入降级结果
    return state  ← 不抛异常，不中断Pipeline
```

### 3.2 降级策略

| Agent | 降级方案 |
|-------|----------|
| Transcription | 模型加载失败 → 使用 OpenAI Whisper API |
| Summary | LLM 调用失败 → 规则引擎提取关键句 |
| Action | LLM 失败 → 跳过提取，记录错误 |
| Insight | LLM 失败 → 仅输出规则统计结果 |
| Follow-up | 飞书/Jira不可用 → 本地保存报告 |

### 3.3 重试机制

使用 tenacity (Python) / retry (Java) / 自定义 (Go) 实现：
- 指数退避: 1s → 2s → 4s
- 最大重试: 3次
- 仅对可重试错误（网络超时、限流）重试

## 4. 可扩展性设计

### 4.1 新增Agent

1. 创建Agent类，实现 `process(state) -> state` 接口
2. 在Graph中注册节点
3. 定义边（确定执行顺序）

### 4.2 水平扩展

- 无状态Agent → 多实例部署
- 消息队列解耦 → Redis / RabbitMQ
- 会议状态持久化 → PostgreSQL

## 5. 监控与可观测性

### 5.1 日志规范

每个Agent日志格式：`[AgentName] action: meeting_id, detail`

### 5.2 关键指标

| 指标 | 采集方式 |
|------|----------|
| Pipeline 总耗时 | 入口/出口时间差 |
| 各Agent耗时 | 节点执行前后时间戳 |
| LLM调用次数/延迟 | HTTP客户端中间件 |
| 错误率 | state.errors 统计 |
| Jira/飞书同步成功率 | 集成客户端统计 |
