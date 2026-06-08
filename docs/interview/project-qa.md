# 项目面试问答 30+ 题

> 面试官针对多Agent会议助手项目可能问到的所有问题及参考答案

---

## 一、项目概述类（5题）

### Q1: 用一句话介绍你的项目

**答**: 这是一个企业级多Agent智能会议助手系统，使用5个专业化Agent（转写/摘要/待办/洞察/跟进）通过Pipeline+并行编排实现会议全流程自动化，支持Python/Java/Go三种语言实现。

### Q2: 为什么做这个项目？

**答**: 公司每周20+场会议，痛点是纪要整理耗时（2h/场）、待办遗忘（40%遗漏率）、无效率数据。目标是全流程自动化，帮管理者每周节省9小时。

### Q3: 你在项目中的角色？

**答**: 我是项目的核心开发者，负责整体架构设计、5个Agent的实现、LangGraph编排、外部系统集成（Jira/飞书），以及性能优化和容错设计。

### Q4: 项目上线了多久？效果如何？

**答**: 从设计到上线3个月。上线后转写准确率95%+，待办同步率98%，管理者反馈每周节省约9小时，年化节省人力成本约110万。

### Q5: 项目最大的技术挑战是什么？

**答**: 有三个主要挑战：
1. 如何在保证正确性的同时最大化并行度（最终设计了Pipeline+Fan-out/Fan-in混合模式）
2. LLM输出格式不稳定（JSON Schema约束+解析降级+重试）
3. 外部API可靠性（幂等设计+重试+降级）

---

## 二、架构设计类（8题）

### Q6: 为什么选择多Agent而不是单Agent？

**答**: 
1. **专业化**: 每个Agent专注一项任务，Prompt更精准，输出质量更高
2. **并行**: 独立任务同时执行，3个Agent并行从6分钟降到2分钟
3. **容错**: 一个Agent失败不影响其他，降级策略更灵活
4. **可维护**: 独立开发、测试、部署，符合单一职责原则

### Q7: 为什么用LangGraph而不是CrewAI/AutoGen？

**答**:
- **LangGraph**: 低级编排，控制粒度细，适合确定性工作流
- **CrewAI**: 角色模拟，适合开放式任务，但控制力弱
- **AutoGen**: 对话式协作，适合研究，生产可靠性低
- 本项目是确定性流程（转写→分析→跟进），LangGraph最合适

### Q8: 状态管理怎么设计的？

**答**: 
使用MeetingState作为共享状态，所有Agent读写同一个状态对象。关键设计：
- 每个Agent只写自己负责的字段（summary/actions/insights）
- 并行Agent写不同字段，无需加锁
- 错误追加到errors数组，不覆盖其他Agent的结果

### Q9: 数据是怎么在Agent之间流转的？

**答**:
```
Transcription写入 → transcript, transcript_text
Summary读取 transcript_text → 写入 summary
Action读取 transcript_text → 写入 actions
Insight读取 transcript → 写入 insights
Follow-up读取 summary + actions + insights → 写入 followup
```

### Q10: 如果让你重新设计，会有什么改进？

**答**:
1. 引入消息队列（RabbitMQ）解耦Agent通信
2. 添加事件总线支持实时通知
3. 使用微服务架构，每个Agent独立部署
4. 增加A/B测试框架评估不同Prompt效果
5. 引入Human-in-the-loop在关键节点人工审核

### Q11: 三种语言实现有什么区别？

**答**:
| 维度 | Python | Java | Go |
|------|--------|------|-----|
| 并行方式 | LangGraph内置 | CompletableFuture | goroutine+WaitGroup |
| 优势 | AI生态最好 | 企业级成熟 | 高性能+低资源 |
| 转写 | 本地WhisperX | API调用 | go-whisper |
| 适用场景 | AI团队 | 大型企业 | 高性能场景 |

### Q12: WebSocket和REST API怎么选？

**答**:
- **WebSocket**: 实时音频流传输 + 实时结果推送（长连接双向通信）
- **REST API**: 文件上传 + 结果查询（请求-响应模式）
- 本项目两者都支持，WebSocket用于实时场景，REST用于异步场景

### Q13: 为什么用MiniMax而不是OpenAI？

**答**:
- MiniMax对中文支持更好（中文会议场景）
- 成本更低（国内API）
- 延迟更低（国内服务器）
- 支持切换：通过环境变量配置，两个都可以用

---

## 三、技术实现类（10题）

### Q14: LangGraph的Node和Edge是怎么定义的？

**答**:
```python
graph.add_node("transcription", transcription_agent.process)  # Node = Agent函数
graph.add_edge(START, "transcription")     # Edge = 执行顺序
graph.add_edge("transcription", "summary") # 一对多 = 并行
```
Node是Python async函数，接收state返回state。

### Q15: 并行执行时如何保证线程安全？

**答**:
- **Python**: LangGraph框架管理，并行Node写不同字段
- **Java**: 创建state副本，各Agent独立执行，最后合并
- **Go**: sync.Mutex保护并行写入

### Q16: Prompt是怎么设计的？

**答**:
采用三层结构：
1. **System Prompt**: 定义角色和规则
2. **JSON Schema**: 约束输出格式
3. **User Prompt**: 包含实际数据 + 输出模板

关键技巧：Few-shot示例、response_format=json_object、温度0.3（低随机性）

### Q17: 怎么处理长会议文本超过Token限制？

**答**:
MapReduce策略：
1. 将转写文本按时间段分块（每块5分钟）
2. 每块独立生成摘要（Map）
3. 合并所有块摘要生成最终摘要（Reduce）

### Q18: 说话人识别怎么做的？

**答**:
1. pyannote-audio提取说话人embedding
2. 聚类算法分类不同说话人
3. WhisperX的assign_word_speakers将文本分配给说话人
4. 可以预注册说话人embedding提高准确率

### Q19: Action Agent怎么提取截止时间？

**答**:
1. LLM提取自然语言时间（"下周五"、"3天内"）
2. 将今天日期作为context传给LLM
3. LLM输出标准格式YYYY-MM-DD
4. 后处理校验日期合理性

### Q20: 效率评分算法怎么设计的？

**答**:
综合评分 = 0.4 × LLM评分 + 0.3 × 均衡度 + 0.3 × 时间利用率
- **LLM评分**: LLM根据会议内容评0-10分
- **均衡度**: 基于基尼系数（发言越均衡分越高）
- **时间利用率**: 有效发言时间/总时长

### Q21: 飞书消息怎么发的？

**答**:
1. Webhook机器人：配置webhook URL，POST卡片消息
2. Open API：获取tenant_access_token → 调用发送消息API
3. 卡片消息：使用Interactive Card格式，支持Markdown

### Q22: 如何处理网络异常？

**答**:
三层防护：
1. **重试**: tenacity指数退避重试（3次）
2. **超时**: 每个API调用30s超时
3. **降级**: 重试失败后返回降级结果，不中断流程

### Q23: 测试怎么做的？

**答**:
1. **单元测试**: 每个Agent独立测试，Mock LLM和外部API
2. **集成测试**: 完整Pipeline测试（用演示数据）
3. **性能测试**: 并发100个会议的处理能力
4. **端到端**: WebSocket客户端模拟真实场景

---

## 四、性能与优化类（5题）

### Q24: 系统处理一场会议需要多长时间？

**答**: 
1小时会议约3分钟：
- 转写: ~60s（70x实时速度）
- 并行分析: ~90s（三个Agent最慢的那个）
- 跟进: ~30s（同步+推送）

### Q25: 有做过什么性能优化？

**答**:
1. 并行执行（8min→3min，-62.5%）
2. WhisperX批量推理（faster-whisper后端）
3. LLM JSON模式减少解析错误
4. 连接池复用（HTTP/DB）
5. 懒加载模型（按需初始化）

### Q26: 并发多少个会议？

**答**: 
当前单实例支持10个并发会议。扩展方案：
- 消息队列 + 多Worker
- GPU资源池共享
- K8s HPA自动扩缩容

### Q27: 内存占用多少？

**答**:
- Python版: ~500MB（含Whisper模型）
- Java版: ~200MB
- Go版: ~30MB（最轻量）
- Whisper large-v2模型: ~3GB GPU显存

### Q28: 最大的性能瓶颈是什么？

**答**:
1. **Whisper转写**: GPU密集型，是最慢的环节
2. **LLM API延迟**: 网络调用1-3秒
3. **优化方向**: 流式转写（边转写边分析）、LLM缓存

---

## 五、开放讨论类（5题）

### Q29: 如果要支持视频会议（带画面）怎么做？

**答**:
1. 增加 Vision Agent: 分析PPT画面、白板内容
2. 视频抽帧 → OCR → 合并到转写文本
3. 多模态LLM（GPT-4V）理解图文

### Q30: 如果要支持实时字幕怎么做？

**答**:
1. 流式转写: 音频分块（500ms），增量返回
2. WebSocket实时推送文本
3. 前端渲染字幕overlay
4. 延迟目标: < 2秒

### Q31: 如果会议有100个人参加怎么办？

**答**:
1. 说话人识别：预注册embedding + 分组聚类
2. 发言控制：只识别主要发言人
3. 性能：分段并行转写
4. 摘要：分主题分组摘要再合并

### Q32: 如何保护会议隐私？

**答**:
1. 音频处理完立即删除
2. 转写文本加密存储
3. 访问控制（JWT+角色权限）
4. 审计日志记录所有访问
5. 合规：GDPR/数据安全法

### Q33: 下一步打算做什么改进？

**答**:
1. 流式处理：边转写边分析，减少等待
2. 多语言支持：日韩等更多语言
3. 个性化：学习用户偏好，定制纪要风格
4. 知识库：RAG关联历史会议和企业知识
5. 智能提醒：根据待办进度智能调整提醒策略
