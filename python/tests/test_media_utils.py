"""media_utils 单元测试"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# 确保 src 在导入路径中
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.media_utils import (
    SUPPORTED_VIDEO_EXTENSIONS,
    is_video_file,
    save_upload_streaming,
    extract_audio_from_video,
)


class TestIsVideoFile:
    """文件类型判断"""

    def test_mp4_lowercase(self):
        assert is_video_file("meeting.mp4") is True

    def test_mp4_uppercase(self):
        assert is_video_file("meeting.MP4") is True

    def test_mkv(self):
        assert is_video_file("recording.mkv") is True

    def test_webm(self):
        assert is_video_file("google-meet.webm") is True

    def test_avi(self):
        assert is_video_file("old-camera.avi") is True

    def test_mov(self):
        assert is_video_file("quicktime.mov") is True

    def test_flv(self):
        assert is_video_file("stream.flv") is True

    def test_wmv(self):
        assert is_video_file("windows.wmv") is True

    def test_wav_not_video(self):
        assert is_video_file("audio.wav") is False

    def test_txt_not_video(self):
        assert is_video_file("notes.txt") is False

    def test_no_extension(self):
        assert is_video_file("noextension") is False

    def test_empty_string(self):
        assert is_video_file("") is False

    def test_all_supported_formats_in_set(self):
        """确认所有支持的格式都在常量集合中"""
        expected = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv"}
        assert SUPPORTED_VIDEO_EXTENSIONS == expected


class TestSaveUploadStreaming:
    """流式写入磁盘"""

    @pytest.mark.asyncio
    async def test_writes_full_content(self):
        data = b"x" * 3000  # 跨越多个 chunk（chunk_size=1024）

        class MockUploadFile:
            async def read(self, size):
                nonlocal _pos
                chunk = data[_pos : _pos + size]
                _pos += size
                return chunk

        _pos = 0
        mock = MockUploadFile()

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            dest = Path(tmp.name)

        try:
            total = await save_upload_streaming(mock, dest, chunk_size=1024)
            assert total == 3000
            assert dest.read_bytes() == data
        finally:
            dest.unlink(missing_ok=True)


class TestExtractAudioFromVideo:
    """FFmpeg 音频提取"""

    @pytest.mark.asyncio
    async def test_extracts_audio_from_valid_mp4(self):
        """用 FFmpeg 生成一个测试视频 ��� 验证能提取出音频并返回非空 WAV bytes"""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            video_path = Path(tmp.name)

        try:
            # FFmpeg 生成 3 秒测试视频（带 440Hz 正弦波音频）
            import subprocess
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    "-c:v", "libx264", "-c:a", "aac",
                    "-shortest",
                    str(video_path),
                ],
                check=True,
                capture_output=True,
            )

            result = await extract_audio_from_video(video_path)
            # WAV 格式前 4 字节是 "RIFF"
            assert len(result) > 0
            assert result[:4] == b"RIFF"

        finally:
            video_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_corrupted_video_raises_runtime_error(self):
        """损坏的文件应抛出 RuntimeError"""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(b"this is not a valid video file")
            video_path = Path(tmp.name)

        try:
            with pytest.raises(RuntimeError):
                await extract_audio_from_video(video_path)
        finally:
            video_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_nonexistent_file_raises_runtime_error(self):
        """不存在的文件应抛出 RuntimeError"""
        with pytest.raises(RuntimeError):
            await extract_audio_from_video(Path("/nonexistent/video.mp4"))
