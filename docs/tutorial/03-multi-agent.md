# 教程 03 - 多Agent编排

> 用 LangGraph 把多个 Agent 连接成一个工作流

---

## 什么是 LangGraph？

LangGraph 是一个状态图（StateGraph）编排框架。你可以把它理解为：

- **Node** = 干活的人（Agent）
- **Edge** = 工作流程（谁先做、谁后做）
- **State** = 共享的文件夹（大家读写同一份数据）

---

## 最简单的两Agent Pipeline

```python
"""最简单的多Agent示例：转写 → 摘要"""

from langgraph.graph import StateGraph, START, END
from typing import TypedDict


# Step 1: 定义共享状态
class MyState(TypedDict):
    raw_text: str       # 原始文本
    summary: str        # 摘要结果


# Step 2: 定义 Agent（Node）
def transcription_agent(state: MyState) -> MyState:
    """模拟转写Agent"""
    state["raw_text"] = "张总说Q3预算上调15%。李明负责预算方案。"
    print("[转写Agent] 完成转写")
    return state


def summary_agent(state: MyState) -> MyState:
    """模拟摘要Agent"""
    state["summary"] = f"摘要: {state['raw_text'][:20]}..."
    print("[摘要Agent] 完成摘要")
    return state


# Step 3: 构建 Graph
graph = StateGraph(MyState)

graph.add_node("transcription", transcription_agent)
graph.add_node("summary", summary_agent)

graph.add_edge(START, "transcription")       # 开始 → 转写
graph.add_edge("transcription", "summary")   # 转写 → 摘要
graph.add_edge("summary", END)               # 摘要 → 结束

# Step 4: 编译并运行
app = graph.compile()
result = app.invoke({"raw_text": "", "summary": ""})

print(f"\n最终结果: {result['summary']}")
```

---

## 加入并行：三个Agent同时工作

```python
from langgraph.graph import StateGraph, START, END
from typing import TypedDict


class MeetingState(TypedDict):
    transcript: str
    summary: str
    actions: str
    insights: str


def transcription(state):
    state["transcript"] = "会议内容..."
    return state

def summary(state):
    state["summary"] = "摘要结果"
    return state

def action(state):
    state["actions"] = "待办: 李明做预算"
    return state

def insight(state):
    state["insights"] = "效率评分: 8.2"
    return state


graph = StateGraph(MeetingState)

graph.add_node("transcription", transcription)
graph.add_node("summary", summary)
graph.add_node("action", action)
graph.add_node("insight", insight)

# Pipeline: START → 转写
graph.add_edge(START, "transcription")

# Fan-out: 转写 → 三个Agent（并行！）
graph.add_edge("transcription", "summary")
graph.add_edge("transcription", "action")
graph.add_edge("transcription", "insight")

# Fan-in: 三个Agent → END
graph.add_edge("summary", END)
graph.add_edge("action", END)
graph.add_edge("insight", END)

app = graph.compile()
result = app.invoke({
    "transcript": "", "summary": "",
    "actions": "", "insights": "",
})
print(result)
```

**关键点**: 当从一个Node出发有多条Edge时，LangGraph自动并行执行！

---

## 三种语言的并行实现对比

| 语言 | 实现方式 | 代码量 |
|------|----------|--------|
| Python | LangGraph add_edge（自动并行）| 3行 |
| Java | CompletableFuture.allOf() | 15行 |
| Go | goroutine + WaitGroup | 20行 |

---

下一篇: [04 - 会议系统实战](04-meeting-system.md)
