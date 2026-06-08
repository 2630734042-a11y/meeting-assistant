# 学习导航

## 当前状态

- 当前阶段：模块层
- 当前学习对象：等待用户选择模块
- 最近完成：总体架构分析
- 更新时间：2026-06-06

## 当前学习链路

- 仓库总览 ✅
- 当前模块：待选择
- 当前文件：待选择
- 当前函数/类：待选择

## 已完成

- [x] 总体架构

## 推荐下一步

### 推荐 1（⭐ 首选）
- 目标：`python/src/main.py`
- 类型：启动入口
- 原因：这是 FastAPI 应用的入口文件，从这里可以最快理解系统如何启动、各组件如何组装。先看入口是理解主流程的最佳起点。
- 学完收获：理解服务启动流程、WebSocket/API 端点注册、Agent 编排图的挂载方式

### 推荐 2
- 目标：`python/src/graph/meeting_graph.py`
- 类型：编排引擎
- 原因：LangGraph 状态图是整个系统的"大脑"，定义了 5 个 Agent 如何串行和并行协作。如果你更关心"Agent 之间如何配合"，可以从这里开始。
- 学完收获：理解 Pipeline + Fan-out/Fan-in 编排模式的具体实现

### 推荐 3
- 目标：`python/src/agents/`
- 类型：核心业务
- 原因：5 个 Agent 是系统真正的"干活的角色"。如果你想直接看每个 Agent 做什么、怎么做，可以选一个具体的 Agent 开始。
- 学完收获：理解单个 Agent 的输入/输出/处理逻辑

### 推荐 4
- 目标：`docs/interview/`
- 类型：面试准备材料
- 原因：如果你正在准备面试，这些材料（八股文、STAR法、简历模板、面试问答）是该项目"面试价值"最高的部分，可以先看代码再看材料，也可以穿插进行。
- 学完收获：获得完整的项目面试话术和知识点

## 你可以这样继续问我

### 选择学习方向
- "带我看 `python/src/main.py`" — 从入口开始理解主流程
- "先看 `meeting_graph.py` 了解编排" — 先搞清楚 Agent 怎么配合
- "我想先看 Transcription Agent" — 从第一个 Agent 开始逐个深入

### 了解当前全貌
- "5 个 Agent 之间数据是怎么流转的？"
- "为什么用 Pipeline + 并行而不是全串行或全并行？"
- "entrypoint `main.py` 里做了哪些初始化工作？"

### 同时准备面试
- "边看代码边帮我准备面试话术"
- "先给我看一下八股文里和 Agent 架构相关的题目"

## 待探索区域

- [x] `python/` — 顶层结构已扫描，内部模块待深入
- [x] `docs/` — 结构已扫描，内容待按需阅读
- [ ] `python/src/agents/` — 5 个 Agent 实现
- [ ] `python/src/graph/` — LangGraph 编排
- [ ] `python/src/integrations/` — 外部集成 (Jira/飞书/MiniMax)
- [ ] `python/src/websocket/` — 实时音频流处理
- [ ] `docs/interview/` — 面试材料
- [ ] `docs/tutorial/` — 从零教程

## 备注

- 当前仓库只有 Python 实现，Java 和 Go 版本尚未落地（README 中描述为规划状态）
- Python 版本功能最完整，包含本地 Whisper 转写、Jira/飞书集成、ChromaDB 向量存储
- 建议沿 `main.py → meeting_graph.py → agents → integrations → websocket` 的顺序逐步深入
