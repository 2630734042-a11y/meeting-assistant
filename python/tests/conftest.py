"""共享 fixtures 和工具函数"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


# ---- ffmpeg 路径解析 ----
# 测试环境中 ffmpeg 可能不在 Python subprocess 可见的 PATH 上。
# 优先级: PATH > FFMPEG_PATH 环境变量 > 报错
def resolve_ffmpeg() -> str:
    """返回可用的 ffmpeg 可执行文件路径"""
    found = shutil.which("ffmpeg")
    if found:
        return found
    # 允许 CI/其他开发者通过环境变量注入 ffmpeg 路径
    env_path = os.environ.get("FFMPEG_PATH", "")
    if env_path and Path(env_path).exists():
        return env_path
    raise FileNotFoundError(
        "ffmpeg not found. "
        "请安装 ffmpeg 或设置 FFMPEG_PATH 环境变量指向 ffmpeg 可执行文件。\n"
        "https://ffmpeg.org/download.html"
    )


@pytest.fixture
def ffmpeg() -> str:
    """ffmpeg 可执行文件路径"""
    return resolve_ffmpeg()


@pytest.fixture
def test_video_path(ffmpeg: str) -> Path:
    """生成一个 2 秒测试 MP4 视频"""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        video_path = Path(tmp.name)

    subprocess.run(
        [
            ffmpeg, "-y",
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
def test_audio_path(ffmpeg: str) -> Path:
    """生成 2 秒测试 WAV"""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = Path(tmp.name)
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=2", "-ac", "1",
         "-ar", "16000", str(wav_path)],
        check=True, capture_output=True,
    )
    yield wav_path
    wav_path.unlink(missing_ok=True)
