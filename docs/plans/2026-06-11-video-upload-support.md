# 视频上传 + 音频提取 实施计划

> **给 Claude：** 必须使用 `superpowers:executing-plans` 子技能，按任务逐项执行本计划。

**目标：** 新增视频上传接口，支持 MP4/MKV/WebM/AVI/MOV/FLV/WMV 格式，FFmpeg 提取音频后走现有 5-Agent Pipeline。

**架构方案：** 新建 `src/utils/media_utils.py` 封装 FFmpeg 音频提取逻辑，在 `server.py` 新增 `POST /upload-video` 端点，流式写临时文件 → FFmpeg pipe 提取 → 清理 → 调用现有 `run_meeting_pipeline()`。

**技术栈：** FFmpeg (系统级)、asyncio subprocess、FastAPI UploadFile

---

## 任务拆解

### 任务 1：创建 `media_utils.py` 工具模块

**涉及文件：**
- 新建：`python/src/utils/__init__.py`
- 新建：`python/src/utils/media_utils.py`

**步骤 1：创建 `__init__.py`**

```bash
mkdir -p python/src/utils
echo '"""会议助手工具模块"""' > python/src/utils/__init__.py
```

**步骤 2：编写 `media_utils.py` 完整实现**

文件内容：

```python
"""视频/音频处理工具 —— FFmpeg 音频提取"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import BinaryIO

from loguru import logger

# 支持的视频文件扩展名
SUPPORTED_VIDEO_EXTENSIONS: set[str] = {
    ".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv",
}

# FFmpeg 提取音频的参数
FFMPEG_AUDIO_EXTRACT_ARGS = [
    "-vn",                # 丢弃视频流
    "-acodec", "pcm_s16le",  # 16-bit PCM WAV
    "-ar", "16000",       # 16kHz 采样率（WhisperX 推荐）
    "-ac", "1",           # 单声道
    "-f", "wav",          # WAV 容器格式
    "pipe:1",             # 输出到 stdout
]


def is_video_file(filename: str) -> bool:
    """通过文件扩展名判断是否为支持的视频格式（大小写不敏感）"""
    suffix = Path(filename).suffix.lower()
    return suffix in SUPPORTED_VIDEO_EXTENSIONS


async def save_upload_streaming(
    upload_file: BinaryIO,
    dest_path: Path,
    chunk_size: int = 1024 * 1024,  # 1MB 块
) -> int:
    """
    分块写入上传文件到磁盘，避免大文件撑爆内存。
    返回写入的总字节数。
    """
    total = 0
    with open(dest_path, "wb") as f:
        while chunk := await upload_file.read(chunk_size):
            f.write(chunk)
            total += len(chunk)
    logger.debug(f"Saved upload to {dest_path} ({total} bytes)")
    return total


async def extract_audio_from_video(video_path: Path) -> bytes:
    """
    通过 FFmpeg 从视频文件中提取音频。

    参数:
        video_path: 视频文件的本地路径（已落盘）

    返回:
        16kHz 单声道 WAV 格式的音频字节数据

    异常:
        FileNotFoundError: 系统未安装 FFmpeg
        RuntimeError: FFmpeg 执行失败（视频损坏/无音频流等）
    """
    cmd = [
        "ffmpeg",
        "-i", str(video_path),
        *FFMPEG_AUDIO_EXTRACT_ARGS,
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace")[:500]
            logger.error(f"FFmpeg failed (code={process.returncode}): {stderr_text}")
            raise RuntimeError(
                f"音频提取失败: {stderr_text.splitlines()[-1] if stderr_text.splitlines() else '未知错误'}"
            )

        if not stdout:
            raise RuntimeError("无法从视频中提取音频流：输出为空")

        logger.info(
            f"Audio extracted: {len(stdout)} bytes from {video_path.name}"
        )
        return bytes(stdout)

    except FileNotFoundError:
        raise FileNotFoundError(
            "FFmpeg 未安装或不在 PATH 中。请安装 FFmpeg: https://ffmpeg.org/download.html"
        )
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"音频提取过程异常: {e}")
```

**步骤 3：验证导入**

```bash
cd python && python -c "from src.utils.media_utils import is_video_file, extract_audio_from_video; print('Import OK')"
```

预期：**Import OK**

---

### 任务 2：编写 `media_utils` 单元测试

**涉及文件：**
- 新建：`python/tests/__init__.py`（如果不存在）
- 新建：`python/tests/test_media_utils.py`

**步骤 1：创建测试目录基础文件**

```bash
cd python
[ ! -f tests/__init__.py ] && echo "" > tests/__init__.py
```

**步骤 2：编写测试文件 `tests/test_media_utils.py`**

```python
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
        """用 FFmpeg 生成一个测试视频 → 验证能提取出音频并返回非空 WAV bytes"""
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
```

**步骤 3：运行测试，确认失败**

```bash
cd python && pytest tests/test_media_utils.py -v
```

预期：**全部 14 个测试通过（PASS）**

> 注意：如果系统 FFmpeg 未安装，`test_extracts_audio_from_valid_mp4` 和 `test_corrupted_video_raises_runtime_error` 会失败。在已安装 FFmpeg 的环境下应全部通过。

---

### 任务 3：在 `server.py` 新增视频上传端点

**涉及文件：**
- 修改：`python/src/websocket/server.py` — 在音频 `upload` 端点后新增视频端点

**步骤 1：添加导入**

在 `server.py` 第 23 行（`from ..graph.meeting_graph import ...`）之后插入：

```python
from ..utils.media_utils import is_video_file, save_upload_streaming, extract_audio_from_video
```

同时将第 17 行 FastAPI 导入加上 `HTTPException`：

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException
```

**步骤 2：在第 231 行（`/upload` 端点函数结束处）之后插入新端点**

```python
@app.post("/api/v1/meeting/{meeting_id}/upload-video")
async def upload_video(meeting_id: str, file: UploadFile = File(...)):
    """
    上传视频文件并处理

    支持格式: MP4, MKV, WebM, AVI, MOV, FLV, WMV
    自动提取音频后走完整 5-Agent Pipeline
    """
    # 1. 校验文件格式
    if not file.filename or not is_video_file(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的视频格式，支持的格式: {', '.join(sorted(SUPPORTED_VIDEO_EXTENSIONS))}",
        )

    # 2. 校验文件非空
    # FastAPI 默认无此校验，手动检查
    if not file.size:
        raise HTTPException(status_code=400, detail="上传文件为空")

    logger.info(
        f"Received video upload: {meeting_id}, "
        f"file={file.filename}, size={file.size} bytes"
    )

    # 3. 流式写入临时文件
    suffix = Path(file.filename).suffix or ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)

    audio_bytes = None
    try:
        # 分块写入磁盘
        await save_upload_streaming(file, tmp_path)
        file_size_on_disk = tmp_path.stat().st_size
        logger.debug(f"Video saved: {tmp_path} ({file_size_on_disk} bytes)")

        # 4. FFmpeg 提取音频
        audio_bytes = await extract_audio_from_video(tmp_path)
        logger.info(f"Audio extracted: {len(audio_bytes)} bytes")

    except FileNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail=f"服务器未安装 FFmpeg: {e}",
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=422,
            detail=str(e),
        )
    finally:
        # 5. 清理临时视频文件
        try:
            tmp_path.unlink()
            logger.debug(f"Cleaned up temp file: {tmp_path}")
        except FileNotFoundError:
            pass

    # 6. 走现有 Pipeline
    result = await run_meeting_pipeline(
        meeting_id=meeting_id,
        audio_data=audio_bytes,
    )
    meeting_results[meeting_id] = result

    return {
        "meeting_id": meeting_id,
        "video_filename": file.filename,
        "video_size": file.size,
        "audio_size": len(audio_bytes),
        "status": result.get("status", "completed"),
        "errors": result.get("errors", []),
    }
```

**步骤 3：验证服务器能正常启动**

```bash
# 先停掉旧服务器
# 再重新启动
cd python && python -m uvicorn src.websocket.server:app --host 0.0.0.0 --port 8000
```

预期：服务器正常启动，无导入错误。

**步骤 4：手动测试新端点**

```bash
# 生成测试视频
ffmpeg -y -f lavfi -i "testsrc=duration=3:size=160x120:rate=5" -f lavfi -i "sine=frequency=440:duration=3" -c:v libx264 -c:a aac -shortest test_meeting.mp4

# 上传到新接口
curl -X POST -F "file=@test_meeting.mp4" http://localhost:8000/api/v1/meeting/video-test/upload-video

# 查看报告
curl http://localhost:8000/api/v1/meeting/video-test/report

# 清理
rm test_meeting.mp4
```

预期：
- 返回 JSON 包含 `"status": "completed"`, `"video_filename": "test_meeting.mp4"`, `"errors": []`
- 报告接口返回完整的 5 Agent 结果

**步骤 5：补充 server.py 中缺失的 `tempfile` 和 `Path` 导入**

确认 server.py 顶部有这些 import（如没有则补充）：
```python
import tempfile
from pathlib import Path
```

> 检查：当前 server.py 没有 `tempfile` 和 `Path` 导入，需要在步骤 1 一并添加。

---

### 任务 4：编写集成测试

**涉及文件：**
- 新建：`python/tests/test_video_upload.py`

**步骤 1：编写集成测试**

```python
"""视频上传端点集成测试"""

import subprocess
import tempfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# 导入 FastAPI app
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.websocket.server import app


@pytest.fixture
def test_video_path() -> Path:
    """生成一个 2 秒测试 MP4 视频"""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        video_path = Path(tmp.name)

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=160x120:rate=5",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-c:a", "aac",
            "-shortest",
            str(video_path),
        ],
        check=True,
        capture_output=True,
    )
    yield video_path
    video_path.unlink(missing_ok=True)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


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
        assert data["status"] == "completed"
        assert data["video_filename"] == "test_video.mp4"
        assert data["errors"] == []

    @pytest.mark.asyncio
    async def test_upload_unsupported_format_returns_400(self, client):
        response = await client.post(
            "/api/v1/meeting/bad-format/upload-video",
            files={"file": ("doc.txt", b"hello", "text/plain")},
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
        assert "transcript" in data
        assert "summary" in data
```

**步骤 2：运行集成测试**

```bash
cd python && pip install httpx -q 2>&1 | tail -1  # 确保 httpx 已安装
cd python && pytest tests/test_video_upload.py -v
```

预期：**3 个测试全部通过（PASS）**

---

## 验证方式

全部完成后运行全量测试确认无回归：

```bash
cd python && pytest tests/ -v
```

预期：**17 个测试全部通过**（14 个单元测试 + 3 个集成测试），无现有功能回归。

## 风险与注意事项

1. **FFmpeg 依赖**：测试和运行都依赖系统安装 FFmpeg。Windows 用户需从 https://ffmpeg.org/download.html 下载并加入 PATH。
2. **测试视频生成**：测试中用 `subprocess.run(["ffmpeg", ...])` 生成测试视频，确保测试机器有 FFmpeg。
3. **大文件并发**：当前单进程处理，大视频并发上传会产生磁盘和 CPU 压力。生产环境建议加请求队列或 worker 池。
4. **server.py import 调整**：需确认 `tempfile` 和 `Path` 的导入不与其他 import 冲突。
