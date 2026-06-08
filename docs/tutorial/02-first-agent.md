# 教程 02 - 第一个 Agent

> 用 30 行代码写一个最简单的 Agent

---

## 目标

写一个能自动总结文本的 Agent。输入一段文字，Agent 调用 LLM 返回摘要。

---

## 代码实现

创建文件 `my_first_agent.py`:

```python
"""我的第一个 Agent - 文本摘要"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

class SummaryAgent:
    """一个最简单的 Agent：接收文本，返回摘要"""

    def __init__(self):
        self.api_key = os.getenv("MINIMAX_API_KEY", "")
        self.base_url = "https://api.minimax.chat/v1"

    def summarize(self, text: str) -> str:
        """调用 LLM 生成摘要"""
        response = httpx.post(
            f"{self.base_url}/text/chatcompletion_v2",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": "abab6.5s-chat",
                "messages": [
                    {"role": "system", "content": "你是一个摘要助手，用3句话总结用户输入的文本。"},
                    {"role": "user", "content": text}
                ],
                "temperature": 0.3,
            },
            timeout=30,
        )
        data = response.json()
        return data["choices"][0]["message"]["content"]


if __name__ == "__main__":
    agent = SummaryAgent()

    text = """
    今天的Q3预算评审会议讨论了三个主要议题。
    首先，Q2预算执行率为87%，研发投入占比42%。
    其次，Q3计划将预算上调15%，主要投入AI基础设施和人才招聘。
    王芳建议招聘3名高级算法工程师，年薪80万。
    最后，赵伟正在对比服务器供应商，下周一出采购方案。
    """

    print("原文:", text)
    print("\n摘要:", agent.summarize(text))
```

运行：
```bash
python my_first_agent.py
```

---

## 代码解读

1. **`__init__`**: 初始化 Agent，加载 API Key
2. **`summarize`**: Agent 的核心能力——调用 LLM 生成摘要
3. **System Prompt**: 定义 Agent 的角色和行为规则
4. **Temperature 0.3**: 低随机性，摘要需要稳定输出

---

## 进化：让 Agent 更强大

这只是最基础的 Agent。在后续教程中，我们将逐步添加：
- **结构化输出**: JSON Schema 约束（教程03）
- **多Agent协作**: LangGraph 编排（教程03）
- **工具调用**: Jira/飞书集成（教程04）
- **实时处理**: WebSocket + 流式（教程04）

---

下一篇: [03 - 多Agent编排](03-multi-agent.md)
