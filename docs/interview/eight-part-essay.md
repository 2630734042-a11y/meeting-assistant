# 八股文大全 - 多Agent智能会议助手

> 50+ 面试常见题目，涵盖 Agent/多Agent/LangGraph/RAG/工程化/语音/系统设计 七大类

---

## 一、Agent 基础（10题）

### Q1: Agent 和传统 LLM Chain 有什么区别？

**答**: 
- **LLM Chain**: 线性、硬编码的调用链，A→B→C 顺序固定，没有自主决策能力
- **Agent**: 具备自主推理循环（ReAct），能根据执行结果动态调整策略
- **核心区别**: Agent 有 Planning（规划）、Memory（记忆）、Tool Use（工具调用）三大能力
- **类比**: Chain像流水线工人按固定步骤操作；Agent像项目经理，能根据情况调整计划

### Q2: 解释 ReAct 模式的工作原理

**答**:
ReAct = Reason + Act，核心是「思考→行动→观察→循环」：
1. **Thought**: LLM思考当前应该做什么
2. **Action**: 调用工具执行操作
3. **Observation**: 获取工具返回结果
4. **Loop**: 根据观察结果继续思考，直到任务完成

在本项目中，每个Agent的process方法内部就是一个简化的ReAct循环。

### Q3: Agent的三大核心组件是什么？

**答**:
1. **Planning（规划）**: 将复杂任务分解为子任务的能力
2. **Memory（记忆）**: 短期（上下文窗口）+ 长期（向量数据库）
3. **Tool Use（工具调用）**: 调用外部API、数据库、搜索引擎等

本项目中：
- Planning: LangGraph状态图定义执行计划
- Memory: ChromaDB存储历史会议
- Tool: Whisper(转写) + Jira API + 飞书 API

### Q4: 什么是 Function Calling？和 Tool Use 有什么关系？

**答**:
- **Function Calling**: LLM判断应该调用哪个函数及参数（OpenAI首创）
- **Tool Use**: 更广义的概念，Agent调用外部工具的能力
- **关系**: Function Calling是Tool Use的一种技术实现方式

### Q5: Agent 的规划能力有哪几种实现方式？

**答**:
1. **预定义工作流**: 固定的任务执行图（本项目的LangGraph）
2. **LLM动态规划**: 让LLM生成任务清单再逐步执行
3. **ReAct循环**: 每步根据结果动态决定下一步
4. **Plan-and-Execute**: 先生成完整计划，再按计划执行

### Q6: 如何评估Agent的质量？

**答**:
- **任务完成率**: 是否正确完成了目标任务
- **步骤效率**: 完成任务用了多少步（越少越好）
- **错误处理**: 遇到错误能否自动恢复
- **幻觉率**: 输出中包含多少不真实的信息
- 本项目指标: 转写准确率95%+、待办同步率98%

### Q7: 什么是Agent的上下文窗口管理？

**答**:
LLM有token限制（如8K/32K/128K），需要管理输入长度：
- **滑动窗口**: 只保留最近N轮对话
- **摘要压缩**: 将历史对话压缩为摘要
- **关键信息提取**: 只保留重要信息
- 本项目: 长会议转写文本会先做分块摘要再合并

### Q8: Agent 的幻觉问题如何解决？

**答**:
1. **结构化输出约束**: 要求JSON Schema输出（本项目的方案）
2. **RAG增强**: 基于真实数据回答
3. **多Agent交叉验证**: 多个Agent互相检查
4. **置信度阈值**: 低于阈值的结果标记为不确定
5. **人工兜底**: Human-in-the-loop

### Q9: 工作流(Workflow) vs 自主智能体(Autonomous Agent)？

**答**:
| 维度 | 工作流 | 自主智能体 |
|------|--------|------------|
| 执行路径 | 预定义 | 动态规划 |
| 可预测性 | 高 | 低 |
| 灵活性 | 低 | 高 |
| 适用场景 | 明确流程 | 开放式任务 |

本项目选择**工作流**模式，因为会议处理流程是确定的。

### Q10: Agent的状态管理怎么做？

**答**:
- **内存状态**: 单次会议的临时状态（MeetingState）
- **持久化**: 完成后存入PostgreSQL
- **向量存储**: 会议内容存入ChromaDB供未来检索
- 本项目的MeetingState就是核心状态对象

---

## 二、多Agent系统（10题）

### Q11: 为什么需要多Agent而不是单Agent？

**答**:
1. **专业化分工**: 每个Agent专注一项任务，提升质量
2. **并行加速**: 独立任务同时执行，减少总时间
3. **容错隔离**: 一个Agent失败不影响其他Agent
4. **可维护性**: 每个Agent独立开发、测试、部署
5. **注意力集中**: 避免单Agent处理复杂任务时"注意力漂移"

### Q12: 多Agent协作有哪几种模式？

**答**:
1. **中心化（Boss-Worker）**: 主Agent分配任务给子Agent
2. **流水线（Pipeline）**: 串行处理，前一个输出是下一个输入
3. **民主协作（Joint Discussion）**: 平等讨论达成一致
4. **Pipeline+并行（本项目）**: 混合模式，串行+并行

### Q13: 本项目为什么选Pipeline+并行？

**答**:
- **串行部分**: 音频→转写是强依赖，必须先完成转写
- **并行部分**: 摘要/待办/洞察三个任务互相独立
- **汇聚部分**: 跟进Agent需要所有结果才能工作
- 这种模式在保证正确性的同时最大化了并行度

### Q14: 多Agent之间如何通信？

**答**:
1. **共享状态**: 所有Agent读写同一个State对象（本项目方案）
2. **消息传递**: Agent之间发送消息（AutoGen方案）
3. **黑板模式**: 公共数据区，Agent自行读写
4. **事件驱动**: 发布/订阅模式

### Q15: 如何解决多Agent通信冗余？

**答**:
1. **状态分区**: 每个Agent只关注自己需要的字段
2. **通信摘要**: 只传递关键信息，不传原始数据
3. **明确接口**: 定义每个Agent的输入/输出Schema
4. **最大迭代次数**: 防止无限循环通信

### Q16: 多Agent系统的调试方法？

**答**:
1. **结构化日志**: 每个Agent输出带标签的日志
2. **状态快照**: 每个Node前后保存State快照
3. **LangGraph Studio**: 可视化Graph执行过程
4. **单元测试**: 每个Agent独立测试
5. **Mock依赖**: 用Mock替换LLM和外部API

### Q17: 并行Agent的结果如何合并？

**答**:
Fan-in合并策略：
- **Python/LangGraph**: 框架自动合并（多条边汇聚到同一节点）
- **Java**: CompletableFuture.allOf() 等待全部完成后手动合并
- **Go**: sync.WaitGroup + Mutex保护合并
- **冲突处理**: 本项目中并行Agent写入不同字段，不存在冲突

### Q18: 如果某个并行Agent失败了怎么办？

**答**:
本项目的容错策略：
1. 每个Agent内部try/catch，不抛异常到外部
2. 失败时写入降级结果 + 记录error到state.errors
3. Follow-up Agent检查errors，在报告中标注
4. 不会因为一个Agent失败而中断整个Pipeline

### Q19: 多Agent系统的性能优化？

**答**:
1. **并行执行**: 独立Agent同时运行（本项目已实现）
2. **LLM缓存**: 相同输入缓存结果
3. **流式处理**: 转写完一段就开始处理
4. **模型选择**: 简单任务用小模型，复杂任务用大模型
5. **异步IO**: 非阻塞的API调用

### Q20: 如何监控多Agent系统？

**答**:
- **指标**: 各Agent耗时、成功率、LLM调用量
- **日志**: 结构化日志 + 链路追踪ID
- **告警**: 超时、错误率阈值触发告警
- **可视化**: LangGraph Studio / Grafana Dashboard

---

## 三、LangGraph 专题（8题）

### Q21: LangGraph 的核心概念是什么？

**答**:
三个核心原语：
1. **State**: 在Graph中流转的共享状态
2. **Node**: 执行具体任务的函数（对应Agent）
3. **Edge**: 连接Node的边，定义执行顺序

### Q22: LangGraph 和 LangChain 的区别？

**答**:
- **LangChain**: 提供组件（LLM、Prompt、Tool），线性Chain
- **LangGraph**: 基于LangChain的编排层，支持图结构（包括循环）
- **关系**: LangGraph是LangChain的上层抽象

### Q23: LangGraph 如何实现并行执行？

**答**:
当从一个Node出发有多条Edge指向不同Node时，LangGraph自动并行：
```python
graph.add_edge("transcription", "summary")   # 三条边
graph.add_edge("transcription", "action")    # 从同一个Node
graph.add_edge("transcription", "insight")   # 出发 → 并行
```

### Q24: LangGraph 的条件路由是什么？

**答**:
根据State的内容动态决定下一个Node：
```python
graph.add_conditional_edges(
    "transcription",
    lambda state: "error" if state.get("errors") else "continue",
    {"error": "error_handler", "continue": "summary"}
)
```

### Q25: LangGraph 的 Checkpoint 机制？

**答**:
- 在每个Node执行后保存State快照
- 支持从任意Checkpoint恢复执行
- 用途：调试、断点恢复、人工审核后继续

### Q26: LangGraph4j (Java) 和 Python 版的区别？

**答**:
- API风格一致，Java版使用泛型和CompletableFuture
- Java版需要显式定义State类型（TypedDict vs POJO）
- 可视化支持PlantUML和Mermaid

### Q27: Go 版没有 LangGraph，如何等效实现？

**答**:
Go使用原生并发原语：
- **goroutine**: 替代Node
- **channel**: 替代Edge（数据传递）
- **sync.WaitGroup**: 替代Fan-in等待
- **struct**: 替代State

### Q28: LangGraph 的 Human-in-the-loop？

**答**:
在关键节点插入中断点，等待人工确认：
- Checkpoint保存当前状态
- 暴露Web界面让人审核
- 人工确认后从Checkpoint继续执行

---

## 四、RAG 与向量数据库（6题）

### Q29: 什么是 RAG？在本项目中怎么用？

**答**:
RAG = Retrieval-Augmented Generation（检索增强生成）：
1. 将历史会议内容存入向量数据库（ChromaDB）
2. 新会议时检索相关历史会议
3. 将历史context加入LLM prompt
4. 用途：识别recurring话题、关联历史决策

### Q30: Embedding 的原理？

**答**:
将文本映射为固定维度的向量（如768维），语义相似的文本在向量空间中距离更近。
常用模型：OpenAI text-embedding-3-small、BGE-M3

### Q31: Chunk 策略有哪些？

**答**:
1. **固定大小**: 每512个token切一块
2. **语义分割**: 按段落/句子切分
3. **递归分割**: 按标题→段落→句子→字符逐层切分
4. 本项目: 按说话人发言段切分（天然的语义单元）

### Q32: 向量检索的常见算法？

**答**:
- **暴力搜索**: 精确但慢 O(n)
- **HNSW**: 近似最近邻，高性能
- **IVF**: 倒排索引，适合大规模
- ChromaDB 默认使用 HNSW

### Q33: 重排序(Reranking)是什么？

**答**:
向量检索后用更精确的模型重新排序结果：
1. 向量检索取Top-K（如Top-20）
2. Reranker精排取Top-N（如Top-5）
3. 提升检索精度，降低噪声

### Q34: RAG 的评估指标？

**答**:
- **检索质量**: Recall@K, MRR
- **生成质量**: BLEU, ROUGE, 人工评分
- **端到端**: 任务完成率、用户满意度

---

## 五、工程化（8题）

### Q35: 如何处理 LLM 输出格式不稳定的问题？

**答**:
1. **JSON Schema约束**: response_format=json_object
2. **Few-shot示例**: 在prompt中给出输出样例
3. **解析降级**: 正则提取 → 宽松解析 → 默认值
4. **重试**: 格式不对自动重试（最多3次）

### Q36: Token 优化策略？

**答**:
1. **Prompt压缩**: 去除冗余描述
2. **分块处理**: 长文本分块处理后合并
3. **缓存**: 相同输入直接返回缓存
4. **模型选择**: 简单任务用便宜模型

### Q37: 异步/流式处理如何实现？

**答**:
- **Python**: async/await + FastAPI WebSocket
- **Java**: CompletableFuture + Spring WebSocket
- **Go**: goroutine + gorilla/websocket
- **流式转写**: 音频分块实时发送，结果实时返回

### Q38: 如何保证 Jira 同步的幂等性？

**答**:
1. **唯一标识**: meeting_id + task_hash 生成唯一键
2. **先查后写**: 创建前查询是否已存在
3. **标签标记**: 添加 meeting-{meeting_id} 标签便于查询
4. **结果缓存**: 已同步的结果缓存，防止重复调用

### Q39: 系统如何做日志管理？

**答**:
- **结构化日志**: JSON格式，包含时间、级别、Agent名、meeting_id
- **链路追踪**: 通过meeting_id关联整个Pipeline的日志
- **日志级别**: DEBUG(开发) → INFO(生产) → ERROR(告警)
- **Python**: loguru / **Java**: SLF4J / **Go**: log标准库

### Q40: 配置管理最佳实践？

**答**:
1. **环境变量**: 敏感信息（API Key）通过.env注入
2. **配置文件**: 非敏感配置用yaml/properties
3. **默认值**: 所有配置都有合理默认值
4. **.env.example**: 提供配置模板，不含真实值

### Q41: 如何做版本兼容？

**答**:
- **API版本**: /api/v1/ 路径前缀
- **Schema版本**: 数据模型向后兼容
- **依赖锁定**: requirements.txt / pom.xml / go.mod

### Q42: CI/CD 流程设计？

**答**:
```
代码提交 → Lint检查 → 单元测试 → 集成测试 → 构建Docker镜像 → 部署Staging → 部署Production
```

---

## 六、语音技术（5题）

### Q43: Whisper 模型的工作原理？

**答**:
- **架构**: Encoder-Decoder Transformer
- **输入**: 30秒音频的Mel频谱图
- **输出**: 文本token序列
- **多任务**: 语言检测 + 转写 + 翻译
- **训练**: 68万小时弱监督数据

### Q44: 为什么用 WhisperX 而不是原版 Whisper？

**答**:
1. **速度**: faster-whisper批量推理，70x实时速度
2. **时间戳**: wav2vec2强制对齐，精确到词级别
3. **说话人识别**: 集成pyannote-audio
4. **VAD预处理**: 降低幻觉，过滤静音段

### Q45: 说话人识别(Speaker Diarization)原理？

**答**:
1. **提取特征**: 从音频中提取speaker embedding
2. **聚类**: 将embedding聚类到不同说话人
3. **分配**: 将每个语音片段分配给对应说话人
4. 常用工具: pyannote-audio, Diart

### Q46: VAD(语音活动检测)有什么用？

**答**:
- 检测音频中的有声/无声段
- 过滤静音和噪声，减少无效处理
- 降低Whisper的幻觉（静音段容易产生幻觉）
- 提升转写效率（只处理有声段）

### Q47: 如何支持中英双语转写？

**答**:
1. **Whisper多语言**: 原生支持99种语言
2. **语言检测**: 前30秒自动检测语言
3. **混合模式**: language=None让模型自动判断
4. **后处理**: 对中英混合文本做分词优化

---

## 七、系统设计（8题）

### Q48: 如何处理大规模并发会议？

**答**:
1. **消息队列**: 会议任务入队，Worker消费处理
2. **水平扩展**: 无状态Agent多实例部署
3. **GPU资源池**: Whisper推理共享GPU
4. **异步处理**: 非实时任务异步化

### Q49: 如何保证系统高可用？

**答**:
1. **多实例部署**: 每个服务至少2个副本
2. **健康检查**: /health 端点 + K8s存活探针
3. **熔断器**: 外部服务不可用时快速失败
4. **降级策略**: 核心功能保证，非核心降级

### Q50: 数据安全如何保证？

**答**:
1. **传输加密**: HTTPS/WSS
2. **存储加密**: 数据库加密存储
3. **访问控制**: API Key + JWT认证
4. **音频处理**: 处理完立即删除原始音频
5. **合规**: 符合GDPR/数据安全法

### Q51: 如何做性能优化？

**答**:
1. **缓存**: LLM结果缓存 + Redis
2. **流式**: 边转写边处理
3. **批处理**: 多段音频批量转写
4. **模型优化**: int8量化 + TensorRT加速

### Q52: 如何设计会议数据模型？

**答**:
```sql
Meeting: id, title, created_at, status, duration
Transcript: id, meeting_id, speaker, text, start_time, end_time
ActionItem: id, meeting_id, assignee, task, deadline, status
```

### Q53: WebSocket 连接管理？

**答**:
1. **心跳检测**: 定期ping/pong，检测断连
2. **重连机制**: 客户端断连后自动重连
3. **连接限制**: 单会议最大连接数
4. **消息压缩**: 大数据量使用压缩

### Q54: 如何做灰度发布？

**答**:
1. **按会议ID**: 部分会议走新版本
2. **按用户**: 部分用户使用新功能
3. **流量比例**: 10% → 50% → 100% 逐步放量
4. **一键回滚**: 出问题立即切回旧版本

### Q55: 成本控制策略？

**答**:
| 资源 | 优化方法 |
|------|----------|
| LLM Token | 缓存 + 简短Prompt + 小模型 |
| GPU | 共享GPU + 队列调度 |
| 存储 | 定期清理 + 冷热分离 |
| API调用 | 合并请求 + 限流 |
