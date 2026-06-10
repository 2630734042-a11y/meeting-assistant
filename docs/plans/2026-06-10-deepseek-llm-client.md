# DeepSeek LLM 客户端 - 实施计划

> **给 Claude：** 必须使用 `superpowers:executing-plans` 子技能，按任务逐项执行本计划。

**目标：** 将 MiniMaxClient 替换为通用 OpenAI 兼容的 LLMClient，默认使用 DeepSeek API，同时支持任意 OpenAI 兼容服务。

**架构方案：** 新建 `LLMClient`（httpx 直连 `/chat/completions` 格式），替换 `MiniMaxClient`（MiniMax 专有格式），所有 5 个 Agent 和 graph 的导入改为 `LLMClient`，环境变量从 `MINIMAX_*` 迁移到 `LLM_*`。

**技术栈：** Python 3.10+ / httpx / tenacity / pydantic

---

### 任务 1：创建 LLMClient 替代 MiniMaxClient

**涉及文件：**
- 新建：`python/src/integrations/llm_client.py`
- 删除：`python/src/integrations/minimax_client.py`

**步骤 1：编写 LLMClient 实现**

```python
"""
通用 LLM 客户端 - 支持 DeepSeek 及任意 OpenAI 兼容 API

默认连接 DeepSeek API（OpenAI 兼容格式），通过环境变量切换服务商:
  LLM_BASE_URL  → 默认 https://api.deepseek.com
  LLM_API_KEY   → API Key
  LLM_MODEL     → 默认 deepseek-chat

兼容 OpenAI / DeepSeek / 通义千问 / 智谱 等所有 OpenAI 格式 API。
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential


class LLMClient:
    """
    通用 OpenAI 兼容 LLM 客户端

    API 格式: POST /v1/chat/completions
    文档: https://api-docs.deepseek.com/
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str = "deepseek-chat",
    ):
        self.base_url = base_url or os.getenv(
            "LLM_BASE_URL", "https://api.deepseek.com"
        ).rstrip("/")
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.model = model or os.getenv("LLM_MODEL", "deepseek-chat")

        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self._client = httpx.AsyncClient(
            timeout=120.0,
            headers=headers,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> str:
        """
        调用 LLM 聊天接口

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            temperature: 温度参数
            max_tokens: 最大生成 token 数
            response_format: 输出格式约束 (如 {"type": "json_object"})

        Returns:
            模型生成的文本
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        url = f"{self.base_url}/v1/chat/completions"

        response = await self._client.post(url, json=payload)
        response.raise_for_status()

        data = response.json()
        if "choices" in data and len(data["choices"]) > 0:
            content = data["choices"][0]["message"]["content"]
            return content

        logger.error(f"LLM API unexpected response: {data}")
        raise ValueError(f"Unexpected API response: {data}")

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict:
        """调用聊天接口并解析 JSON 输出"""
        text = await self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # JSON 解析失败的降级：尝试截取 {...} 片段
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
            raise

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
```

**步骤 2：删除旧文件**

```bash
rm python/src/integrations/minimax_client.py
```

**步骤 3：提交**

```bash
git add python/src/integrations/llm_client.py
git rm python/src/integrations/minimax_client.py
git commit -m "refactor: 用 LLMClient(OpenAI兼容) 替换 MiniMaxClient"
```

---

### 任务 2：更新 __init__.py 导出

**涉及文件：**
- 修改：`python/src/integrations/__init__.py`

**步骤 1：替换导出**

原文件只包含一行空内容，需要写入新内容：

```python
from .llm_client import LLMClient
from .jira_client import JiraClient
from .feishu_client import FeishuClient

__all__ = ["LLMClient", "JiraClient", "FeishuClient"]
```

**步骤 2：提交**

```bash
git add python/src/integrations/__init__.py
git commit -m "refactor: 更新 integrations __init__.py 导出 LLMClient"
```

---

### 任务 3：更新 3 个 Agent 的导入

**涉及文件：**
- 修改：`python/src/agents/summary_agent.py:15,74-75`
- 修改：`python/src/agents/action_agent.py:18,76,80`
- 修改：`python/src/agents/insight_agent.py:17,71-72`

**步骤 1：summary_agent.py — 替换导入和类型注解**

第 15 行，`MiniMaxClient` → `LLMClient`：
```python
from ..integrations.llm_client import LLMClient
```

第 74-75 行，类型注解和构造：
```python
    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()
```

**步骤 2：action_agent.py — 同上**

第 18 行：
```python
from ..integrations.llm_client import LLMClient
```

第 76 行：
```python
        llm_client: LLMClient | None = None,
```

第 80 行：
```python
        self.llm = llm_client or LLMClient()
```

**步骤 3：insight_agent.py — 同上**

第 17 行：
```python
from ..integrations.llm_client import LLMClient
```

第 71-72 行：
```python
    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()
```

**步骤 4：提交**

```bash
git add python/src/agents/summary_agent.py python/src/agents/action_agent.py python/src/agents/insight_agent.py
git commit -m "refactor: 三个Agent的MiniMaxClient导入改为LLMClient"
```

---

### 任务 4：更新 meeting_graph.py 的导入

**涉及文件：**
- 修改：`python/src/graph/meeting_graph.py:54,98,122`

**步骤 1：替换导入和所有引用**

第 54 行：
```python
from ..integrations.llm_client import LLMClient
```

第 98 行，函数签名中的类型注解：
```python
    llm_client: LLMClient | None = None,
```

第 122 行，默认实例化：
```python
    llm = llm_client or LLMClient()
```

**步骤 2：提交**

```bash
git add python/src/graph/meeting_graph.py
git commit -m "refactor: meeting_graph 中 MiniMaxClient 改为 LLMClient"
```

---

### 任务 5：更新环境变量模板

**涉及文件：**
- 修改：`.env.example:7-15`

**步骤 1：替换 LLM 配置段**

删掉旧的 MiniMax + OpenAI 段（第 7-15 行），替换为：

```
# ---------- LLM API ----------
# DeepSeek API (默认)
# 获取 Key: https://platform.deepseek.com/api_keys
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=your_deepseek_api_key_here
LLM_MODEL=deepseek-chat

# 切换到其他 OpenAI 兼容服务示例:
# OpenAI:     LLM_BASE_URL=https://api.openai.com  LLM_MODEL=gpt-4o
# 通义千问:    LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode
# 智谱:        LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
# MiniMax:     LLM_BASE_URL=https://api.minimax.chat/v1
```

**步骤 2：提交**

```bash
git add .env.example
git commit -m "config: 环境变量从 MINIMAX_* 迁移到 LLM_*，默认 DeepSeek"
```

---

### 任务 6：验证全量导入通过

**步骤 1：语法检查所有 .py 文件**

```bash
cd python
python -c "
import ast, os
errors = []
for root, dirs, files in os.walk('src'):
    for f in files:
        if f.endswith('.py'):
            with open(os.path.join(root, f), 'r', encoding='utf-8') as fh:
                try:
                    ast.parse(fh.read())
                except SyntaxError as e:
                    errors.append(f'{root}/{f}: {e}')
print(f'{len(errors)} errors') if errors else print('All OK')
for e in errors: print(e)
"
```

预期输出：`All OK`

**步骤 2：验证模型导入链路完整**

```bash
cd python
python -c "
from src.integrations.llm_client import LLMClient
from src.integrations import LLMClient, JiraClient, FeishuClient
from src.models.schemas import MeetingStatus, create_initial_state

# 验证 LLMClient 默认指向 DeepSeek
client = LLMClient()
assert 'deepseek' in client.base_url, f'Expected deepseek, got {client.base_url}'
assert client.model == 'deepseek-chat'
print(f'Base URL: {client.base_url}')
print(f'Model: {client.model}')
print('Import chain OK')
"
```

预期输出：`Import chain OK`，base_url 包含 `deepseek`

**步骤 3：确认旧文件已不存在且无残留引用**

```bash
test ! -f python/src/integrations/minimax_client.py && echo "old file removed ✓"
grep -r "MiniMaxClient\|minimax_client" python/src/ && echo "RESIDUAL REFS FOUND!" || echo "no residual refs ✓"
```

预期输出：`old file removed ✓` / `no residual refs ✓`

**步骤 4：提交验证结果**

```bash
git add -A && git diff --cached --stat
git commit -m "verify: 确认所有导入链路正确，无残留MiniMax引用"
```
（仅当无残留引用时；如有残留引用，先修复再提交）

---

### 任务 7：端到端 Demo 验证

**前置条件：** 配置好 `LLM_API_KEY`（真实 DeepSeek Key）

**步骤 1：配置 .env**

```bash
cd python
cp ../.env.example ../.env
# 编辑 ../.env，填入 LLM_API_KEY=sk-xxxxx
```

**步骤 2：跑 demo 模式**

```bash
cd python
python -c "
import asyncio
import sys
sys.path.insert(0, '.')
from src.graph.meeting_graph import run_meeting_pipeline

async def main():
    result = await run_meeting_pipeline(meeting_id='test-demo', audio_data=b'')
    print('Status:', result.get('status'))
    summary = result.get('summary')
    if summary:
        print('Summary title:', getattr(summary, 'title', 'N/A'))
    actions = result.get('actions')
    if actions:
        print('Actions count:', len(getattr(actions, 'action_items', [])))
    errors = result.get('errors', [])
    if errors:
        print('Errors:', errors)
    else:
        print('No errors!')

asyncio.run(main())
"
```

预期输出：Status 为 completed，有 summary 和 actions，errors 为空。

**步骤 3：提交**

```bash
git add -A
git commit -m "verify: 端到端 demo 验证通过"
```

---

### 验证方式

完成所有任务后，运行以下命令做终验：

```bash
# 1. 无残留引用
grep -r "MiniMaxClient\|minimax_client" python/src/ 2>/dev/null || true

# 2. 全量语法检查
cd python && python -c "import ast,os;[ast.parse(open(os.path.join(r,f),encoding='utf-8').read()) for r,_,fs in os.walk('src') for f in fs if f.endswith('.py')]" && echo "All OK"

# 3. 导入链路
cd python && python -c "from src.integrations.llm_client import LLMClient; c=LLMClient(); print(c.base_url, c.model)"
```

---

### 风险与注意事项

- `response_format: {"type": "json_object"}` 需要 DeepSeek 支持。实测若失败，降级为在 prompt 内强调 JSON 输出 + 解析容错（`chat_json` 已有截取 `{...}` 的降级逻辑）
- 旧的 `GROUP_ID` 参数是 MiniMax 特有，不再需要
- `python/requirements.txt` 中 `openai>=1.50.0` 依赖可保留（其他功能可能用到），也可按需删除
