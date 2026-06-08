# 简历模板 - 多Agent智能会议助手

> 针对 Python/Java/Go 三种岗位方向的项目经历写法

---

## Python 方向简历

### 项目经历

**多Agent智能会议助手系统** | Python 后端/AI 工程师 | 2025.10 - 2026.03

技术栈：LangGraph / WhisperX / FastAPI / WebSocket / Jira API / 飞书 API / ChromaDB

- 设计并实现 **5-Agent 实时会议助手**，采用 Pipeline + 并行编排模式，转写/摘要/待办/洞察/跟进全流程自动化
- 使用 **WhisperX + pyannote-audio** 实现实时语音转写，准确率 **95%+**，支持中英双语和说话人识别，处理速度 70x 实时
- 基于 **LangGraph 状态图**编排 5 个 Agent，Fan-out/Fan-in 并行执行，总处理时间从 8 分钟优化至 **3 分钟**
- Action Agent 自动提取待办事项并同步到 **Jira Cloud + 飞书任务**，幂等设计保证同步率 **98%**，零重复创建
- 设计 Agent 级别容错机制（降级策略 + 指数退避重试 + 熔断器），系统可用性 **99.5%**
- 管理者每周节省 **9 小时**会议纪要工作，年化节省人力成本约 **110 万**

---

## Java 方向简历

### 项目经历

**多Agent智能会议助手系统** | Java 后端工程师 | 2025.10 - 2026.03

技术栈：Spring Boot 3 / LangGraph4j / CompletableFuture / WebSocket / Jira REST API / PostgreSQL

- 设计并实现 **5-Agent 会议全流程自动化系统**，Spring Boot 3 微服务架构，Pipeline + 并行混合编排
- 基于 **LangGraph4j** 实现状态图驱动的多Agent编排，使用 **CompletableFuture.allOf()** 实现Fan-out/Fan-in并行
- 设计 **MeetingState 共享状态模型**，并行Agent写入不同字段避免并发冲突，结合 ConcurrentHashMap 保证线程安全
- 实现 Jira Cloud REST API 集成，**幂等同步设计**（唯一键去重 + 指数退避重试），同步成功率 **98%**
- 设计 Agent 级别容错降级策略，单 Agent 失败不中断 Pipeline，系统可用性 **99.5%**
- 支持 REST + WebSocket 双协议接入，处理 1 小时会议仅需 **3 分钟**

---

## Go 方向简历

### 项目经历

**多Agent智能会议助手系统** | Go 后端工程师 | 2025.10 - 2026.03

技术栈：Go 1.21 / goroutine / channel / sync.WaitGroup / Gin / gorilla/websocket / Jira API

- 设计并实现 **5-Agent 会议全流程自动化系统**，利用 Go 原生并发能力实现 Pipeline + 并行编排
- 基于 **goroutine + sync.WaitGroup** 实现 Fan-out/Fan-in 并行编排，三个分析 Agent 同时执行，Mutex 保护状态合并
- 设计 **MeetingState 共享状态结构体**，利用 Go 的 struct 值语义创建并行 Agent 的安全副本
- 使用 **Gin + gorilla/websocket** 实现双协议服务，编译为单二进制部署，启动时间 < **50ms**
- 实现 Agent 级别容错（defer/recover + 降级结果），goroutine panic 不影响主流程
- 支持高并发会议处理，单实例 QPS **2000+**，内存占用仅 **30MB**

---

## 简历写作要点

### STAR 数据量化

| 指标 | 数值 | 来源 |
|------|------|------|
| 转写准确率 | 95%+ | WhisperX large-v2 测试集 |
| Jira同步率 | 98% | 生产环境统计 |
| 处理时间优化 | 8min→3min | 并行前后对比 |
| 每周节省时间 | 9小时 | 20场会议 × 27min节省 |
| 年化成本节省 | 110万 | 9h × 52周 × 平均时薪 |
| 系统可用性 | 99.5% | SLA统计 |

### 关键词建议

根据岗位JD调整以下关键词的出现频率：
- **通用**: 多Agent、Pipeline、并行、LLM、容错降级
- **Python**: LangGraph、FastAPI、WhisperX、asyncio
- **Java**: Spring Boot、CompletableFuture、LangGraph4j
- **Go**: goroutine、channel、WaitGroup、Gin

### 避免的写法

- ❌ "负责会议系统的开发" → 太笼统
- ❌ "使用了LangGraph框架" → 没有亮点
- ✅ "基于LangGraph状态图编排5个Agent，Fan-out/Fan-in并行执行" → 有技术深度
- ✅ "幂等设计保证同步率98%，零重复创建" → 有工程思维
