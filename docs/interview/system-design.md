# 系统设计面试要点 - 多Agent会议助手

> 从可扩展性、高可用、监控三个维度准备系统设计面试

---

## 一、可扩展性设计

### 1.1 水平扩展方案

```
                    ┌─────────────┐
                    │  负载均衡器   │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────┴─────┐ ┌───┴────┐ ┌────┴─────┐
        │ Instance 1 │ │ Inst 2 │ │ Inst 3   │
        │ (API+Agent)│ │        │ │          │
        └─────┬─────┘ └───┬────┘ └────┬─────┘
              │            │            │
        ┌─────┴────────────┴────────────┴─────┐
        │           消息队列 (RabbitMQ)         │
        └─────────────────┬───────────────────┘
                          │
              ┌───────────┼───────────┐
              │           │           │
        ┌─────┴─────┐ ┌──┴───┐ ┌────┴────┐
        │ GPU Worker │ │Worker│ │ Worker  │
        │ (Whisper)  │ │(LLM) │ │(LLM)   │
        └───────────┘ └──────┘ └─────────┘
```

### 1.2 无状态设计

- API 层无状态，可随时增减实例
- 会议状态存储在 PostgreSQL / Redis
- Agent 处理结果通过消息队列传递

### 1.3 新增 Agent 的扩展方式

```python
# Step 1: 实现新 Agent
class NewAgent:
    async def process(self, state: dict) -> dict:
        # 处理逻辑
        return state

# Step 2: 注册到 Graph
graph.add_node("new_agent", new_agent.process)
graph.add_edge("transcription", "new_agent")
graph.add_edge("new_agent", "followup")
```

---

## 二、高可用设计

### 2.1 容错分层

| 层级 | 策略 | 实现 |
|------|------|------|
| Agent 层 | try/catch + 降级 | 每个 Agent 内部捕获异常 |
| 集成层 | 重试 + 熔断 | tenacity + CircuitBreaker |
| 服务层 | 多实例 + 健康检查 | K8s Deployment + LivenessProbe |
| 数据层 | 主从复制 | PostgreSQL Streaming Replication |

### 2.2 熔断器设计

```
正常状态 (Closed)
    │
    │ 连续失败3次
    ▼
熔断状态 (Open) ──── 30秒后 ──── 半开状态 (Half-Open)
    │                                    │
    │ 直接返回降级结果                    │ 尝试一次请求
    │                                    │
    │                              成功 → 恢复正常
    │                              失败 → 继续熔断
```

### 2.3 降级矩阵

| Agent | 正常模式 | 降级模式 |
|-------|----------|----------|
| Transcription | WhisperX 本地 | OpenAI Whisper API |
| Summary | LLM 结构化摘要 | 规则引擎关键句提取 |
| Action | LLM 提取 + 同步 | 跳过同步，仅提取 |
| Insight | LLM + 规则 | 仅规则引擎统计 |
| Follow-up | 飞书推送 | 本地保存报告 |

---

## 三、监控与告警

### 3.1 四大黄金指标

| 指标 | 含义 | 阈值 |
|------|------|------|
| **延迟** | Pipeline 总处理时间 | P99 < 5 分钟 |
| **流量** | 每分钟处理会议数 | 监控趋势 |
| **错误** | Agent 失败率 | < 5% |
| **饱和度** | GPU/CPU 使用率 | < 80% |

### 3.2 日志规范

```json
{
  "timestamp": "2026-04-06T10:30:00Z",
  "level": "INFO",
  "agent": "SummaryAgent",
  "meeting_id": "m-abc123",
  "action": "process_complete",
  "duration_ms": 2300,
  "tokens_used": 1500
}
```

### 3.3 告警规则

- Pipeline 超时 > 10 分钟 → P1 告警
- Agent 错误率 > 10% → P2 告警
- LLM API 连续失败 > 5 次 → P1 告警
- GPU 使用率 > 90% → P3 告警

---

## 四、数据库设计

### 4.1 核心表结构

```sql
-- 会议表
CREATE TABLE meetings (
    id          VARCHAR(36) PRIMARY KEY,
    title       VARCHAR(500),
    status      VARCHAR(20) DEFAULT 'created',
    duration_s  INT,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

-- 转写表
CREATE TABLE transcripts (
    id          SERIAL PRIMARY KEY,
    meeting_id  VARCHAR(36) REFERENCES meetings(id),
    speaker     VARCHAR(100),
    text        TEXT,
    start_time  DECIMAL(10,2),
    end_time    DECIMAL(10,2),
    confidence  DECIMAL(3,2)
);

-- 待办表
CREATE TABLE action_items (
    id          VARCHAR(36) PRIMARY KEY,
    meeting_id  VARCHAR(36) REFERENCES meetings(id),
    assignee    VARCHAR(100),
    task        TEXT,
    deadline    DATE,
    priority    VARCHAR(20) DEFAULT 'medium',
    status      VARCHAR(20) DEFAULT 'pending',
    jira_key    VARCHAR(50),
    feishu_id   VARCHAR(50),
    created_at  TIMESTAMP DEFAULT NOW()
);

-- 索引
CREATE INDEX idx_transcripts_meeting ON transcripts(meeting_id);
CREATE INDEX idx_actions_meeting ON action_items(meeting_id);
CREATE INDEX idx_actions_assignee ON action_items(assignee);
```

---

## 五、安全设计

### 5.1 认证授权

```
客户端 → [JWT Token] → API Gateway → [权限校验] → Agent Pipeline
```

### 5.2 数据安全

- 传输层: TLS 1.3
- 存储层: AES-256 加密
- 音频: 处理完即删除，不持久化
- API Key: 环境变量注入，不入代码库

### 5.3 合规要求

- GDPR: 用户可请求删除数据
- 数据安全法: 敏感数据脱敏
- 审计日志: 所有操作可追溯
