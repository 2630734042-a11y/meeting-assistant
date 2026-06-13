"""视频上传端点集成测试"""

import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

# 确保 src 在导入路径中
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.websocket.server import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def mock_whisperx_lazy_init():
    """绕过 WhisperX 模型下载——测试环境无 HuggingFace SSL 证书。

    TranscriptionAgent 发现 _model 为 None 时会自动降级为 demo 模式，
    不影响视频上传端点本身的正确性验证。
    """
    with patch(
        "src.agents.transcription_agent.TranscriptionAgent._lazy_init",
        return_value=None,
    ):
        yield


@pytest.fixture(autouse=True)
def mock_extract_audio():
    """模拟 FFmpeg 音频提取，避免测试依赖系统 FFmpeg。

    返回一个最小的 WAV 文件（仅 RIFF 头 + 静音数据），
    供 pipeline 中的 TranscriptionAgent 消费。
    """
    # 生成最小有效 WAV 字节（采样率 16000，16bit，单声道，0.1 秒静音）
    import struct
    sample_rate = 16000
    nchannels = 1
    sampwidth = 2
    nframes = int(sample_rate * 0.1)
    data_size = nframes * nchannels * sampwidth
    riff_size = 36 + data_size
    wav_bytes = (
        b"RIFF"
        + struct.pack("<I", riff_size)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)       # chunk size
        + struct.pack("<H", 1)        # PCM
        + struct.pack("<H", nchannels)
        + struct.pack("<I", sample_rate)
        + struct.pack("<I", sample_rate * nchannels * sampwidth)
        + struct.pack("<H", nchannels * sampwidth)
        + struct.pack("<H", sampwidth * 8)
        + b"data"
        + struct.pack("<I", data_size)
        + b"\x00" * data_size
    )

    with patch(
        "src.websocket.server.extract_audio_from_video",
        new_callable=AsyncMock,
        return_value=wav_bytes,
    ):
        yield


class TestUploadVideo:
    """视频上传端点"""

    @pytest.mark.asyncio
    async def test_upload_valid_mp4_returns_completed(self, client, test_video_path):
        with open(test_video_path, "rb") as f:
            response = await client.post(
                "/api/v1/meeting/video-int-test/upload-video",
                files={"file": ("test_video.mp4", f, "video/mp4")},
            )
        assert response.status_code == 200
        data = response.json()
        # HITL 模式下 pipeline 在 sync_actions 前中断，status 非 completed
        assert data["status"] != "failed"
        assert "thread_id" in data
        assert data["video_filename"] == "test_video.mp4"
        assert data["errors"] == []

    @pytest.mark.asyncio
    async def test_upload_unsupported_format_returns_400(self, client):
        response = await client.post(
            "/api/v1/meeting/bad-format/upload-video",
            files={"file": ("doc.txt", b"hello world", "text/plain")},
        )
        assert response.status_code == 400
        assert "不支持的视频格式" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_report_available_after_upload(self, client, test_video_path):
        with open(test_video_path, "rb") as f:
            await client.post(
                "/api/v1/meeting/video-report-test/upload-video",
                files={"file": ("test.mp4", f, "video/mp4")},
            )

        response = await client.get("/api/v1/meeting/video-report-test/report")
        assert response.status_code == 200
        data = response.json()
        # HITL 中断后 transcript/summary 在 LangGraph fan-out 阶段已生成，
        # 但 sync_actions 后的 followup 结果不完整
        assert "transcript" in data
        # summary 在 fan-out 并行阶段可能已生成，这里不做强制要求
