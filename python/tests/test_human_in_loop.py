"""Human-in-the-Loop 审核流程集成测试"""

import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.websocket.server import app


@pytest.fixture(autouse=True)
def mock_all_services():
    """模拟所有外部服务: WhisperX, LLM, Jira, 飞书"""
    with (
        patch(
            "src.agents.transcription_agent.TranscriptionAgent._lazy_init",
            return_value=None,
        ),
        patch(
            "src.integrations.llm_client.LLMClient.chat_json",
            new_callable=AsyncMock,
            return_value={
                "action_items": [
                    {
                        "assignee": "李明",
                        "task": "整理Q3预算方案",
                        "deadline": "2026-06-20",
                        "priority": "high",
                        "context": "Q3需要上调预算15%",
                    },
                    {
                        "assignee": "王芳",
                        "task": "拟定招聘JD",
                        "deadline": "2026-06-15",
                        "priority": "medium",
                        "context": "招聘3名高级算法工程师",
                    },
                ]
            },
        ),
        patch(
            "src.integrations.llm_client.LLMClient.chat",
            new_callable=AsyncMock,
            return_value="mock llm response",
        ),
        patch(
            "src.integrations.jira_client.JiraClient.is_enabled",
            new_callable=MagicMock,
            return_value=True,
        ),
        patch(
            "src.integrations.jira_client.JiraClient.create_issue",
            return_value={"key": "MOCK-123"},
        ),
        patch(
            "src.integrations.jira_client.JiraClient.resolve_user",
            return_value="mock_user",
        ),
        patch(
            "src.integrations.feishu_client.FeishuClient.is_enabled",
            new_callable=MagicMock,
            return_value=True,
        ),
        patch(
            "src.integrations.feishu_client.FeishuClient.create_task",
            new_callable=AsyncMock,
            return_value={"task_id": "feishu-task-001"},
        ),
        patch(
            "src.integrations.feishu_client.FeishuClient.send_meeting_summary",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        yield


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHumanInTheLoop:
    """HITL 审核流程"""

    @pytest.mark.asyncio
    async def test_upload_interrupts_before_sync(self, client, test_audio_path):
        """上传音频后返回 thread_id，status 非 completed"""
        with open(test_audio_path, "rb") as f:
            response = await client.post(
                "/api/v1/meeting/hitl-int-test/upload",
                files={"file": ("test.wav", f, "audio/wav")},
            )
        assert response.status_code == 200
        data = response.json()
        assert "thread_id" in data
        assert data["status"] != "failed"
        # HITL 在 sync_actions 前中断，故不是 completed
        assert data["status"] != "completed"

    @pytest.mark.asyncio
    async def test_review_then_resume(self, client, test_audio_path):
        """提交审核 -> resume -> 待办被同步"""
        meeting_id = "hitl-review-test"
        with open(test_audio_path, "rb") as f:
            upload_resp = await client.post(
                f"/api/v1/meeting/{meeting_id}/upload",
                files={"file": ("test.wav", f, "audio/wav")},
            )
        data = upload_resp.json()
        assert data["status"] != "failed"
        thread_id = data["thread_id"]

        # 查询报告（审核前应有 pending 条目）
        report = await client.get(f"/api/v1/meeting/{meeting_id}/report")
        assert report.status_code == 200
        report_data = report.json()
        assert "actions" in report_data
        action_items_raw = report_data.get("actions", {}).get("action_items", [])
        assert len(action_items_raw) >= 2

        # 提交审核：确认第一条，删除第二条
        review_resp = await client.put(
            f"/api/v1/meeting/{meeting_id}/actions/review",
            json={
                "thread_id": thread_id,
                "items": [
                    {"index": 0, "review_status": "confirmed"},
                    {"index": 1, "review_status": "deleted"},
                ],
            },
        )
        assert review_resp.status_code == 200
        assert review_resp.json()["status"] == "reviewed"

        # Resume -> sync_actions -> FollowUp
        resume_resp = await client.post(
            f"/api/v1/meeting/{meeting_id}/resume",
            json={"thread_id": thread_id},
        )
        assert resume_resp.status_code == 200

        # 验证 resume 后报告包含 followup
        report2 = await client.get(f"/api/v1/meeting/{meeting_id}/report")
        assert report2.status_code == 200
        report2_data = report2.json()
        # followup 在 resume 后应该出现
        assert "followup" in report2_data

    @pytest.mark.asyncio
    async def test_review_nonexistent_meeting_returns_404(self, client):
        """对不存在的 meeting_id 提交审核返回 404"""
        response = await client.put(
            "/api/v1/meeting/nonexistent-xxx/actions/review",
            json={"thread_id": "t1", "items": []},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_resume_nonexistent_meeting_returns_404(self, client):
        """对不存在的 meeting_id 调用 resume 返回 404/500 或 body 含 failed"""
        response = await client.post(
            "/api/v1/meeting/nonexistent-yyy/resume",
            json={"thread_id": "t1"},
        )
        # resume 对不存在的 checkpoint：LangGraph 返回 status=failed 的 dict
        # 因此 endpoint 返回 200 但 body 含 "failed" 或 "errors"
        if response.status_code == 200:
            data = response.json()
            assert data.get("status") == "failed" or "errors" in data
        else:
            assert response.status_code in (404, 500)

    @pytest.mark.asyncio
    async def test_actions_endpoint_returns_review_status(self, client, test_audio_path):
        """/actions 端点返回的条目包含 review_status 字段"""
        meeting_id = "hitl-actions-test"
        with open(test_audio_path, "rb") as f:
            await client.post(
                f"/api/v1/meeting/{meeting_id}/upload",
                files={"file": ("test.wav", f, "audio/wav")},
            )

        response = await client.get(f"/api/v1/meeting/{meeting_id}/actions")
        assert response.status_code == 200
        data = response.json()
        assert "action_items" in data
        for item in data["action_items"]:
            assert "review_status" in item
            assert item["review_status"] == "pending"
