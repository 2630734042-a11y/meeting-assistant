# LLM 客户端替换设计说明

## 背景与目标

将项目 LLM 调用从 MiniMax 替换为 DeepSeek，同时保留对任意 OpenAI 兼容 API 的扩展能力。让项目在无需 MiniMax API Key 的情况下也能跑通 demo 模式，验证端到端流程。

## 现状与约束

- 现有 `MiniMaxClient` 使用 MiniMax 专有 API 格式（`/text/chatcompletion_v2` + GroupId 参数）
- 各 Agent 只依赖 `chat(messages)` 和 `chat_json(messages)` 两个方法，接口稳定
- DeepSeek 使用 OpenAI 兼容格式（`/chat/completions`），base URL 为 `https://api.deepseek.com`
- 项目未安装 openai SDK，需新增依赖或使用 httpx 直连

## 方案对比

### 方案一：通用 OpenAI 兼容客户端（推荐）

新建 `LLMClient`，用 httpx 直连 OpenAI 兼容 API，通过环境变量切换服务商。

- 优点：改动范围小（1 个文件替换），不引入新 SDK 依赖，任何 OpenAI 兼容服务都可用
- 缺点：需要手动处理流式（本项目无需流式）

### 方案二：引入 openai SDK

使用 `openai` Python SDK，设置 `base_url` 指向 DeepSeek。

- 优点：SDK 封装完善，功能多
- 缺点：引入大依赖（openai SDK ~50MB），过度工程，SDK 版本 API 频繁变动

## 推荐方案

**方案一**。项目已用 httpx 直连，换 base URL 和请求格式即可，改动最小，依赖不变。

## 详细设计

### 架构

```
LLMClient (httpx → DeepSeek/OpenAI 兼容 API)
    ├── chat() → messages → POST /chat/completions → text
    └── chat_json() → chat() + json.loads() → dict
```

### 关键组件

**LLMClient 类：**
- base_url → 环境变量 `LLM_BASE_URL`，默认 `https://api.deepseek.com`
- api_key → 环境变量 `LLM_API_KEY`
- model → 环境变量 `LLM_MODEL`，默认 `deepseek-chat`
- 请求格式：标准 OpenAI Chat Completions 格式
- 重试：保持 tenacity 3 次指数退避

### 改动清单

| 文件 | 操作 |
|------|------|
| `integrations/llm_client.py` | 新建，OpenAI 兼容客户端 |
| `integrations/minimax_client.py` | 删除 |
| `integrations/__init__.py` | 更新导出 `LLMClient` |
| `agents/summary_agent.py` | `MiniMaxClient` → `LLMClient` |
| `agents/action_agent.py` | `MiniMaxClient` → `LLMClient` |
| `agents/insight_agent.py` | `MiniMaxClient` → `LLMClient` |
| `graph/meeting_graph.py` | `MiniMaxClient` → `LLMClient` |
| `.env.example` | `MINIMAX_*` → `LLM_*` |

### 数据流

```
Agent.process()
    → llm.chat_json(messages, temperature=0.3)
        → LLMClient.chat(messages, response_format={"type": "json_object"})
            → POST https://api.deepseek.com/chat/completions
                Headers: Authorization: Bearer $LLM_API_KEY
                Body: {model, messages, temperature, response_format}
        ← JSON response
    ← Python dict
```

### 异常与边界处理

- 未配置 API Key → `_enabled=False`，各 Agent 走 fallback 逻辑
- API 返回非 200 → httpx 抛异常 → tenacity 重试 3 次 → 最终抛给 Agent catch，写入 state.errors
- JSON 解析失败 → 从返回文本中截取 `{...}` 再试

### 测试策略

- 单元测试：用 `responses` 或 `pytest-httpx` mock API 返回，验证 `chat()` 和 `chat_json()` 解析逻辑
- 集成测试：配真实 DeepSeek API Key，跑 demo 模式端到端

## 风险与待确认项

- DeepSeek 的 `response_format: {type: json_object}` 支持程度需实测验证
- 如 DeepSeek 不支持 json_object 模式，降级为在 prompt 中强调 JSON 输出 + 解析容错
