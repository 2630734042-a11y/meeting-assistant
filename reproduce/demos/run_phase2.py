"""
阶段2 验证脚本：基础设施层 — LLM + Jira + 飞书客户端
运行: python demos/run_phase2.py

验证内容:
- MiniMaxClient 创建和配置检测
- JiraClient 懒加载和 is_enabled 开关
- FeishuClient token 缓存和 is_enabled 开关
- 优先级映射函数
"""
import sys
import asyncio
from pathlib import Path

# TODO: sys.path.insert(0, str(Path(__file__).parent.parent))

# TODO: 从 src.integrations 导入 MiniMaxClient, JiraClient, FeishuClient

# TODO: 定义 async def demo() 异步函数，测试以下内容:
#   1. MiniMaxClient: 创建实例(api_key="test-key") → 打印 api_key/BASE_URL → close()
#   2. JiraClient: 创建实例 → 打印 is_enabled/project_key → 测试 map_priority("high")→"High", map_priority("urgent")→"Highest", map_priority("unknown")→"Medium"
#   3. FeishuClient: 创建实例 → 打印 is_enabled/webhook_url → close()
#   ✅ 阶段2验证通过

if __name__ == "__main__":
    # TODO: asyncio.run(demo())
    print("请实现 demo() 函数后运行")
