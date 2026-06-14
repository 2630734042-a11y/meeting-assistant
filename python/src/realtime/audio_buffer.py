"""
AudioBuffer — WebRTC VAD 驱动的音频分块器

接收 PCM 字节流，用 VAD 检测语音/静音边界，
输出按语义边界切分的音频块。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from loguru import logger

try:
    import webrtcvad
    _VAD_AVAILABLE = True
except ImportError:
    _VAD_AVAILABLE = False
    logger.warning("webrtcvad not installed, falling back to fixed-duration chunking")


@dataclass
class AudioChunk:
    """一个音频块"""
    data: bytes            # PCM 16-bit, 16kHz, mono
    chunk_id: int          # 递增序号
    offset_ms: int         # 全局时间偏移（毫秒）
    is_speech: bool = True # VAD 是否检测到语音


class AudioBuffer:
    """
    VAD 驱动的音频分块器。

    关键参数:
        sample_rate: 16000
        vad_aggressiveness: 2 (0-3)
        silence_threshold_ms: 800ms 连续静音 -> 切分边界
        max_chunk_ms: 10000 (10 秒强制切分)
        min_speech_ms: 1500 (短于 1.5 秒的语音块丢弃)
    """

    FRAME_DURATION_MS = 30

    def __init__(
        self,
        sample_rate: int = 16000,
        vad_aggressiveness: int = 2,
        silence_threshold_ms: int = 800,
        max_chunk_ms: int = 10000,
        min_speech_ms: int = 1500,
    ):
        self.sample_rate = sample_rate
        self.silence_threshold_ms = silence_threshold_ms
        self.max_chunk_ms = max_chunk_ms
        self.min_speech_ms = min_speech_ms

        self._buffer = bytearray()
        self._chunk_counter = 0
        self._total_processed_ms = 0

        self._frame_bytes = int(sample_rate * self.FRAME_DURATION_MS / 1000) * 2

        if _VAD_AVAILABLE:
            self._vad = webrtcvad.Vad(vad_aggressiveness)
        else:
            self._vad = None

    # ---- public API ----

    def feed(self, pcm_bytes: bytes) -> None:
        """喂入原始 PCM 字节（16-bit, 16kHz, mono）。"""
        self._buffer.extend(pcm_bytes)

    def process(self) -> AudioChunk | None:
        """
        检测 buffer 中的语音边界，满足条件时切分并返回 AudioChunk。

        不消费 buffer —— 只在检测到边界时由 _cut_chunk 批量消费。
        """
        # 有多少个完整帧
        total_frames = len(self._buffer) // self._frame_bytes
        if total_frames == 0:
            return None

        speech_start: int | None = None   # 当前语音段起始帧号
        last_speech: int = -1             # 最后一帧语音的帧号

        for i in range(total_frames):
            start_byte = i * self._frame_bytes
            frame = bytes(self._buffer[start_byte:start_byte + self._frame_bytes])
            is_speech = self._is_speech_frame(frame)

            if is_speech:
                if speech_start is None:
                    speech_start = i
                last_speech = i
                # 检查是否达到最大长度
                speech_duration = (i - speech_start + 1) * self.FRAME_DURATION_MS
                if speech_duration >= self.max_chunk_ms:
                    return self._cut_chunk(i + 1, speech_start)
            else:
                if speech_start is not None:
                    silence_frames = i - last_speech
                    silence_ms = silence_frames * self.FRAME_DURATION_MS
                    if silence_ms >= self.silence_threshold_ms:
                        return self._cut_chunk(last_speech + 1, speech_start)

        return None

    def flush(self) -> AudioChunk | None:
        """
        强制输出 buffer 中剩余数据。
        用于会议停止时处理尾部语音。
        """
        remaining = bytes(self._buffer)
        self._buffer.clear()
        min_bytes = self._frame_bytes * (self.min_speech_ms // self.FRAME_DURATION_MS)
        if len(remaining) < min_bytes:
            self._total_processed_ms += len(remaining) // (self.sample_rate // 1000 * 2)
            return None

        # 判断是否包含语音
        has_speech = False
        for i in range(len(remaining) // self._frame_bytes):
            frame = bytes(remaining[i * self._frame_bytes:(i + 1) * self._frame_bytes])
            if self._is_speech_frame(frame):
                has_speech = True
                break

        chunk = AudioChunk(
            data=remaining,
            chunk_id=self._chunk_counter,
            offset_ms=self._total_processed_ms,
            is_speech=has_speech,
        )
        self._chunk_counter += 1
        self._total_processed_ms += len(remaining) // (self.sample_rate // 1000 * 2)
        return chunk

    # ---- internal ----

    def _is_speech_frame(self, frame: bytes) -> bool:
        if self._vad is None:
            count = len(frame) // 2
            samples = struct.unpack(f'<{count}h', frame)
            avg_amplitude = sum(abs(s) for s in samples) / count
            return avg_amplitude > 200
        try:
            return self._vad.is_speech(frame, self.sample_rate)
        except Exception:
            return True

    def _cut_chunk(self, end_frame: int, speech_start: int | None) -> AudioChunk | None:
        """消费 buffer 头部 end_frame 帧，生成 AudioChunk。"""
        consume_bytes = end_frame * self._frame_bytes
        chunk_data = bytes(self._buffer[:consume_bytes])
        del self._buffer[:consume_bytes]

        # 检查语音段最小长度
        if speech_start is not None:
            speech_frames = end_frame - speech_start
            speech_ms = speech_frames * self.FRAME_DURATION_MS
            if speech_ms < self.min_speech_ms:
                self._total_processed_ms += speech_ms
                return None

        chunk_duration_ms = len(chunk_data) // (self.sample_rate // 1000 * 2)
        chunk = AudioChunk(
            data=chunk_data,
            chunk_id=self._chunk_counter,
            offset_ms=self._total_processed_ms,
            is_speech=speech_start is not None,
        )
        self._chunk_counter += 1
        self._total_processed_ms += chunk_duration_ms

        logger.debug(
            f"AudioBuffer cut chunk {chunk.chunk_id}: "
            f"{chunk_duration_ms}ms, offset={chunk.offset_ms}ms, "
            f"speech={chunk.is_speech}"
        )
        return chunk
