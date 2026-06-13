"""视频/音频处理工具 —— FFmpeg 音频提取"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import BinaryIO

from loguru import logger

SUPPORTED_VIDEO_EXTENSIONS: set[str] = {
    ".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv",
}

FFMPEG_AUDIO_EXTRACT_ARGS = [
    "-vn",
    "-acodec", "pcm_s16le",
    "-ar", "16000",
    "-ac", "1",
    "-f", "wav",
    "pipe:1",
]


def is_video_file(filename: str) -> bool:
    suffix = Path(filename).suffix.lower()
    return suffix in SUPPORTED_VIDEO_EXTENSIONS


async def save_upload_streaming(
    upload_file: BinaryIO,
    dest_path: Path,
    chunk_size: int = 1024 * 1024,
) -> int:
    total = 0
    with open(dest_path, "wb") as f:
        while chunk := await upload_file.read(chunk_size):
            f.write(chunk)
            total += len(chunk)
    logger.debug(f"Saved upload to {dest_path} ({total} bytes)")
    return total


async def extract_audio_from_video(video_path: Path) -> bytes:
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

        logger.info(f"Audio extracted: {len(stdout)} bytes from {video_path.name}")
        return bytes(stdout)

    except FileNotFoundError:
        raise FileNotFoundError(
            "FFmpeg 未安装或不在 PATH 中。请安装 FFmpeg: https://ffmpeg.org/download.html"
        )
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"音频提取过程异常: {e}")
