# 实时会议助手（WebSocket 流式）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 Batch 模式基础上新增实时会议模式：音频流式转写 + 增量 LLM 分析 + 前端直播仪表盘

**Architecture:** 4 个新后端组件（AudioBuffer → ChunkTranscriber → IncrementalAnalyzer → LiveSessionManager）串成实时 Pipeline，通过 WebSocket 与前端 LiveMeetingView 双向通信。复用现有 Agent 的 LLM 调用逻辑和 Pydantic 数据模型。

**Tech Stack:** Python (asyncio, webrtcvad, WhisperX), FastAPI WebSocket, Vue 3 + Naive UI, TypeScript, Web Audio API

---

## 文件结构

```
新增:
  python/src/realtime/__init__.py            — 模块导出
  python/src/realtime/audio_buffer.py         — VAD 分块器
  python/src/realtime/chunk_transcriber.py    — 分块转写器
  python/src/realtime/incremental_analyzer.py — 增量分析器
  python/src/realtime/session_manager.py      — 会话管理器
  python/frontend/src/composables/useLiveSession.ts — WebSocket + 麦克风
  python/frontend/src/views/LiveMeetingView.vue     — 实时仪表盘

修改:
  python/src/agents/transcription_agent.py    — 抽取 _transcribe_bytes()
  python/src/websocket/server.py              — 新增 /ws/live/{id}
  python/frontend/src/main.ts                 — 新增路由
  python/frontend/src/views/UploadView.vue    — 新增入口按钮
```

---

### Task 1: 安装依赖 + 创建模块骨架

**Files:**
- Create: `python/src/realtime/__init__.py`

- [ ] **Step 1: 安装 webrtcvad**

```bash
cd python && pip install webrtcvad
```

Expected: `Successfully installed webrtcvad`

- [ ] **Step 2: 创建 realtime 模块 `__init__.py`**

```python
"""
实时会议模块

组件流水线:
    AudioBuffer (VAD 分块)
    → ChunkTranscriber (分块转写)
    → IncrementalAnalyzer (增量分析)
    → LiveSessionManager (会话管理)
"""

from .audio_buffer import AudioBuffer, AudioChunk
from .chunk_transcriber import ChunkTranscriber
from .incremental_analyzer import IncrementalAnalyzer
from .session_manager import LiveSessionManager

__all__ = [
    "AudioBuffer",
    "AudioChunk",
    "ChunkTranscriber",
    "IncrementalAnalyzer",
    "LiveSessionManager",
]
```

- [ ] **Step 3: 验证模块可导入**

```bash
cd python && python -c "import src.realtime; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add python/src/realtime/__init__.py
git commit -m "chore: add realtime module skeleton + webrtcvad dependency"
```

---

### Task 2: AudioBuffer — VAD 分块器

**Files:**
- Create: `python/src/realtime/audio_buffer.py`
- Test: `python/src/tests/test_audio_buffer.py`

- [ ] **Step 1: 写失败测试**

```python
# python/src/tests/test_audio_buffer.py
"""AudioBuffer VAD 分块器测试"""

import pytest
from src.realtime.audio_buffer import AudioBuffer, AudioChunk


def generate_silence_ms(ms: int, sample_rate: int = 16000) -> bytes:
    """Generate `ms` milliseconds of silence (all zeros) in PCM 16-bit mono."""
    num_samples = int(sample_rate * ms / 1000)
    return b'\x00\x00' * num_samples


def generate_tone_ms(ms: int, freq: float = 440.0, sample_rate: int = 16000) -> bytes:
    """Generate `ms` milliseconds of a sine tone in PCM 16-bit mono."""
    import math
    import struct
    num_samples = int(sample_rate * ms / 1000)
    samples = []
    for i in range(num_samples):
        t = i / sample_rate
        val = int(16000 * math.sin(2 * math.pi * freq * t))
        samples.append(struct.pack('<h', max(-32768, min(32767, val))))
    return b''.join(samples)


class TestAudioBuffer:
    """AudioBuffer 单元测试"""

    def test_initial_state(self):
        """初始状态：空 buffer，无 chunk 输出"""
        buf = AudioBuffer()
        assert buf.process() is None

    def test_feed_and_process_short_speech(self):
        """喂入短暂语音后 process 返回 None（未达到边界）"""
        buf = AudioBuffer()
        buf.feed(generate_tone_ms(500, 440.0))   # 0.5s tone
        result = buf.process()
        assert result is None  # too short, no silence boundary yet

    def test_silence_triggered_chunk(self):
        """说话 → 800ms 静音 → 触发 chunk 输出"""
        buf = AudioBuffer()
        buf.feed(generate_tone_ms(2000, 440.0))   # 2s speech
        buf.feed(generate_silence_ms(1000))        # 1s silence (> 800ms threshold)
        chunk = buf.process()
        assert chunk is not None
        assert chunk.is_speech is True
        assert len(chunk.data) > 0
        assert chunk.chunk_id == 0
        assert chunk.offset_ms == 0

    def test_max_chunk_length(self):
        """超过 10 秒强制切块"""
        buf = AudioBuffer()
        buf.feed(generate_tone_ms(11000, 440.0))  # 11s continuous speech
        chunk = buf.process()
        assert chunk is not None  # forced cut at 10s
        assert chunk.is_speech is True

    def test_noise_too_short_discarded(self):
        """小于 1.5 秒的噪声块被丢弃"""
        buf = AudioBuffer()
        buf.feed(generate_tone_ms(800, 440.0))    # 0.8s speech
        buf.feed(generate_silence_ms(1000))        # then silence
        chunk = buf.process()
        # Should be None because speech was < 1.5s min chunk
        assert chunk is None

    def test_flush_returns_remaining(self):
        """flush() 强制输出剩余 buffer"""
        buf = AudioBuffer()
        buf.feed(generate_tone_ms(3000, 440.0))
        chunk = buf.flush()
        assert chunk is not None
        assert len(chunk.data) > 0
        assert chunk.offset_ms >= 0

    def test_offset_accumulates(self):
        """多次切块后 offset 正确累积"""
        buf = AudioBuffer()
        # First chunk: 2s speech + 1s silence
        buf.feed(generate_tone_ms(2000, 440.0))
        buf.feed(generate_silence_ms(1000))
        c1 = buf.process()
        assert c1 is not None
        assert c1.offset_ms == 0

        # Second chunk: 2s speech + 1s silence
        buf.feed(generate_tone_ms(2000, 440.0))
        buf.feed(generate_silence_ms(1000))
        c2 = buf.process()
        assert c2 is not None
        # offset should be approximately the duration of first chunk
        assert c2.offset_ms >= 2500  # >= 2s speech + some silence
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd python && python -m pytest src/tests/test_audio_buffer.py -v
```

Expected: 7/7 tests FAIL (AudioBuffer not defined)

- [ ] **Step 3: 实现 AudioBuffer**

```python
# python/src/realtime/audio_buffer.py
"""
AudioBuffer — WebRTC VAD 驱动的音频分块器

接收 PCM 字节流，用 VAD 检测语音/静音边界，
输出按语义边界切分的音频块。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

# webrtcvad 是可选依赖 —— 未安装时降级为固定时长分块
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
        sample_rate: 16000 (WebRTC VAD 要求)
        vad_aggressiveness: 2 (中等激进，0-3)
        silence_threshold_ms: 800ms 连续静音 → 切分边界
        max_chunk_ms: 10000 (10 秒强制切分)
        min_speech_ms: 1500 (短于 1.5 秒的语音块丢弃)
    """

    FRAME_DURATION_MS = 30  # VAD 帧长（webrtcvad 支持 10/20/30ms）

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
        self._total_processed_ms = 0   # 已输出的累积时长
        self._current_speech_start: int | None = None  # 当前语音段在 buffer 中的起始帧索引
        self._frame_index = 0  # buffer 中的全局帧索引

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
        处理 buffer 中的帧，检测到边界时返回一个 AudioChunk。

        边界条件（满足任一即切分）:
        1. 语音段后连续静音 >= silence_threshold_ms
        2. 语音段持续时间 >= max_chunk_ms（强制切分）

        Returns:
            AudioChunk 当边界被触发，否则 None
        """
        while self._has_full_frame():
            frame_bytes = self._pop_frame()
            is_speech = self._is_speech_frame(frame_bytes)

            if is_speech:
                if self._current_speech_start is None:
                    self._current_speech_start = self._frame_index
                    self._speech_start_byte = self._frame_index * self._frame_bytes
            else:
                if self._current_speech_start is not None:
                    # 检查是否达到静音阈值
                    silence_frames = self._frame_index - self._last_speech_frame
                    silence_ms = silence_frames * self.FRAME_DURATION_MS
                    if silence_ms >= self.silence_threshold_ms:
                        return self._cut_chunk(self._last_speech_frame + 1)

            if is_speech:
                self._last_speech_frame = self._frame_index
                # 检查是否达到最大长度
                if self._current_speech_start is not None:
                    speech_duration = (
                        (self._frame_index - self._current_speech_start + 1)
                        * self.FRAME_DURATION_MS
                    )
                    if speech_duration >= self.max_chunk_ms:
                        return self._cut_chunk(self._frame_index + 1)

        return None

    def flush(self) -> AudioChunk | None:
        """
        强制输出 buffer 中剩余数据为一帧。

        用于会议停止时，处理未被 silence 截断的尾部语音。
        """
        remaining = bytes(self._buffer)
        self._buffer.clear()
        if len(remaining) < self._frame_bytes * (self.min_speech_ms // self.FRAME_DURATION_MS):
            self._total_processed_ms += len(remaining) // (self.sample_rate // 1000 * 2)
            return None
        chunk = AudioChunk(
            data=remaining,
            chunk_id=self._chunk_counter,
            offset_ms=self._total_processed_ms,
            is_speech=self._current_speech_start is not None,
        )
        self._chunk_counter += 1
        self._total_processed_ms += len(remaining) // (self.sample_rate // 1000 * 2)
        return chunk

    # ---- internal ----

    def _has_full_frame(self) -> bool:
        return len(self._buffer) >= self._frame_bytes

    def _pop_frame(self) -> bytes:
        frame = bytes(self._buffer[:self._frame_bytes])
        del self._buffer[:self._frame_bytes]
        return frame

    def _is_speech_frame(self, frame: bytes) -> bool:
        if self._vad is None:
            # 降级：无 VAD 时，非零幅度超过阈值就判定为语音
            import struct
            count = len(frame) // 2
            samples = struct.unpack(f'<{count}h', frame)
            avg_amplitude = sum(abs(s) for s in samples) / count
            return avg_amplitude > 200  # 经验阈值
        try:
            return self._vad.is_speech(frame, self.sample_rate)
        except Exception:
            return True  # VAD 出错时保守处理：当作语音

    def _cut_chunk(self, end_frame: int) -> AudioChunk | None:
        """从 buffer 头部提取一个音频块。"""
        # 计算要消费的字节数
        consume_bytes = end_frame * self._frame_bytes
        chunk_data = bytes(self._buffer[:consume_bytes])
        del self._buffer[:consume_bytes]

        # 检查语音段是否达到最小长度
        if self._current_speech_start is not None:
            speech_frames = end_frame - self._current_speech_start
            speech_ms = speech_frames * self.FRAME_DURATION_MS
            if speech_ms < self.min_speech_ms:
                # 太短，丢弃但更新 offset
                self._total_processed_ms += speech_ms
                self._current_speech_start = None
                self._frame_index = 0
                return None

        chunk = AudioChunk(
            data=chunk_data,
            chunk_id=self._chunk_counter,
            offset_ms=self._total_processed_ms,
            is_speech=self._current_speech_start is not None,
        )
        self._chunk_counter += 1

        chunk_duration_ms = len(chunk_data) // (self.sample_rate // 1000 * 2)
        self._total_processed_ms += chunk_duration_ms
        self._current_speech_start = None
        self._frame_index = 0

        logger.debug(
            f"AudioBuffer cut chunk {chunk.chunk_id}: "
            f"{chunk_duration_ms}ms, offset={chunk.offset_ms}ms, "
            f"speech={chunk.is_speech}"
        )
        return chunk
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd python && python -m pytest src/tests/test_audio_buffer.py -v
```

Expected: 7/7 PASS

- [ ] **Step 5: Commit**

```bash
git add python/src/realtime/audio_buffer.py python/src/tests/test_audio_buffer.py
git commit -m "feat: add AudioBuffer with WebRTC VAD chunking"
```

---

### Task 3: 重构 TranscriptionAgent — 抽取 _transcribe_bytes()

**Files:**
- Modify: `python/src/agents/transcription_agent.py`

- [ ] **Step 1: 添加 `_transcribe_bytes()` 静态/独立方法**

在 `TranscriptionAgent` 类的 `_transcribe()` 方法之后、`_generate_demo_transcript()` 之前，新增一个独立方法：

```python
    async def transcribe_bytes(
        self, audio_data: bytes, language: str | None = None
    ) -> TranscriptResult:
        """
        对原始音频字节执行转写（独立于 LangGraph state）。

        供 ChunkTranscriber 调用，避免依赖 state 字典。
        """
        lang = language or self.config.language
        if self._model is None:
            self._lazy_init()

        if self._model is None:
            return self._generate_demo_chunk_transcript(
                audio_data, lang
            )

        import whisperx

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            tmp.write(audio_data)
            tmp.flush()

            # Step 1: WhisperX 转写
            result = self._model.transcribe(
                tmp.name,
                batch_size=self.config.batch_size,
                language=lang,
            )

            # Step 2: 时间戳对齐
            if self._align_model is None:
                model_a, metadata = whisperx.load_align_model(
                    language_code=lang,
                    device=self.config.device,
                )
                self._align_model = (model_a, metadata)

            aligned = whisperx.align(
                result["segments"],
                self._align_model[0],
                self._align_model[1],
                tmp.name,
                self.config.device,
            )

            # Step 3: 说话人识别
            if self._diarize_pipeline is None and self.config.hf_token:
                self._diarize_pipeline = whisperx.DiarizationPipeline(
                    use_auth_token=self.config.hf_token,
                    device=self.config.device,
                )

            if self._diarize_pipeline:
                diarize_result = self._diarize_pipeline(tmp.name)
                final = whisperx.assign_word_speakers(
                    diarize_result, aligned
                )
            else:
                final = aligned

        segments = []
        for seg in final.get("segments", []):
            segments.append(
                TranscriptSegment(
                    speaker=seg.get("speaker", "Unknown"),
                    text=seg.get("text", "").strip(),
                    start=seg.get("start", 0.0),
                    end=seg.get("end", 0.0),
                    confidence=seg.get("confidence", 0.0),
                )
            )

        duration = segments[-1].end if segments else 0.0
        full_text = " ".join(s.text for s in segments)

        return TranscriptResult(
            meeting_id="chunk",
            segments=segments,
            language=lang,
            duration_seconds=duration,
            full_text=full_text,
        )
```

- [ ] **Step 2: 添加 demo chunk 降级方法**

在 `_generate_demo_transcript()` 之后新增：

```python
    @staticmethod
    def _generate_demo_chunk_transcript(
        audio_data: bytes, language: str
    ) -> TranscriptResult:
        """
        为 chunk 生成模拟转写 —— 模型未加载时的降级。
        用音频长度推算 demo 的句子数。
        """
        # 估算音频时长（PCM 16-bit 16kHz mono = 32000 bytes/s）
        estimated_duration = len(audio_data) / 32000.0

        # 从 demo 池中轮播句子
        demo_texts = [
            ("张总", "好的，我们继续讨论下一个议题。"),
            ("李明", "我这边数据已经准备好了，可以先汇报一下。"),
            ("王芳", "关于这个方案我有个建议。"),
            ("赵伟", "收到，我会跟进这个事情。"),
            ("张总", "这个方向没问题，大家还有什么补充的吗？"),
        ]

        seg_count = max(1, int(estimated_duration / 3.0))
        segments = []
        offset = 0.0
        for i in range(min(seg_count, len(demo_texts))):
            speaker, text = demo_texts[i % len(demo_texts)]
            seg_duration = estimated_duration / seg_count
            segments.append(
                TranscriptSegment(
                    speaker=speaker,
                    text=text,
                    start=offset,
                    end=offset + seg_duration,
                    confidence=0.92,
                )
            )
            offset += seg_duration

        full_text = "\n".join(
            f"[{s.speaker}] {s.text}" for s in segments
        )
        return TranscriptResult(
            meeting_id="chunk-demo",
            segments=segments,
            language=language,
            duration_seconds=estimated_duration,
            full_text=full_text,
        )
```

- [ ] **Step 3: 验证现有代码无回归**

```bash
cd python && python -c "
from src.agents.transcription_agent import TranscriptionAgent
agent = TranscriptionAgent()
import asyncio
result = asyncio.run(agent.transcribe_bytes(b'\x00\x00' * 16000 * 2, 'zh'))
print(f'Transcribed {len(result.segments)} segments, duration={result.duration_seconds:.1f}s')
"
```

Expected: 输出转写结果（demo 模式），无异常

- [ ] **Step 4: Commit**

```bash
git add python/src/agents/transcription_agent.py
git commit -m "refactor: extract transcribe_bytes() for chunk-mode reuse"
```

---

### Task 4: ChunkTranscriber — 分块转写器

**Files:**
- Create: `python/src/realtime/chunk_transcriber.py`

- [ ] **Step 1: 实现 ChunkTranscriber**

```python
# python/src/realtime/chunk_transcriber.py
"""
ChunkTranscriber — 对音频块执行转写并逐句推送

每个 chunk 独立通过 WhisperX 转写，时间戳转换为全局偏移，
结果以 TranscriptSegment 列表形式返回。
"""

from __future__ import annotations

import asyncio
from typing import Callable, Awaitable

from loguru import logger

from ..agents.transcription_agent import TranscriptionAgent, TranscriptionConfig
from ..models.schemas import TranscriptSegment, TranscriptResult
from .audio_buffer import AudioChunk


# 回调类型：当新句子就绪时调用
OnSentenceCallback = Callable[[TranscriptSegment], Awaitable[None]]


class ChunkTranscriber:
    """
    分块转写器。

    职责:
    1. 接收 AudioChunk → 调用 WhisperX 转写
    2. 将 chunk 内时间戳转为全局绝对时间戳
    3. 逐句通过回调推送给调用方（通常是 WebSocket）
    4. 累积 transcript_text 供增量分析使用
    """

    def __init__(
        self,
        config: TranscriptionConfig | None = None,
        on_sentence: OnSentenceCallback | None = None,
    ):
        self._agent = TranscriptionAgent(config)
        self._on_sentence = on_sentence
        self._accumulated_segments: list[TranscriptSegment] = []
        self._accumulated_text: str = ""
        self._chunk_count = 0

    @property
    def accumulated_text(self) -> str:
        """获取累积的纯文本全文（供 IncrementalAnalyzer 使用）。"""
        return self._accumulated_text

    @property
    def segment_count(self) -> int:
        """已转写的句子总数。"""
        return len(self._accumulated_segments)

    async def transcribe_chunk(self, chunk: AudioChunk) -> list[TranscriptSegment]:
        """
        转写一个音频块。

        Args:
            chunk: 音频块（含数据和全局时间偏移）

        Returns:
            转写片段列表（时间戳已转为全局绝对时间）
        """
        self._chunk_count += 1
        logger.debug(
            f"ChunkTranscriber: chunk #{chunk.chunk_id} "
            f"({len(chunk.data)} bytes, offset={chunk.offset_ms}ms)"
        )

        # 模型未加载时走 demo 模式 —— transcribe_bytes 内部处理降级
        try:
            result = await self._agent.transcribe_bytes(chunk.data)
        except Exception as e:
            logger.error(f"ChunkTranscriber error on chunk #{chunk.chunk_id}: {e}")
            return []

        # 时间戳转换: chunk 内相对时间 → 全局绝对时间
        offset_seconds = chunk.offset_ms / 1000.0
        global_segments: list[TranscriptSegment] = []

        for seg in result.segments:
            global_seg = TranscriptSegment(
                speaker=seg.speaker,
                text=seg.text,
                start=round(seg.start + offset_seconds, 2),
                end=round(seg.end + offset_seconds, 2),
                confidence=seg.confidence,
            )
            global_segments.append(global_seg)

            # 累积
            self._accumulated_segments.append(global_seg)
            if self._accumulated_text:
                self._accumulated_text += "\n"
            self._accumulated_text += (
                f"[{global_seg.start:.1f}s-{global_seg.end:.1f}s] "
                f"{global_seg.speaker}: {global_seg.text}"
            )

            # 逐句回调推送
            if self._on_sentence:
                try:
                    await self._on_sentence(global_seg)
                except Exception as e:
                    logger.error(f"on_sentence callback error: {e}")

        logger.info(
            f"ChunkTranscriber: chunk #{chunk.chunk_id} → "
            f"{len(global_segments)} segments, "
            f"total={len(self._accumulated_segments)}"
        )
        return global_segments

    def build_transcript_result(self, meeting_id: str) -> TranscriptResult:
        """构建累积的完整 TranscriptResult。"""
        full_text = " ".join(s.text for s in self._accumulated_segments)
        duration = (
            self._accumulated_segments[-1].end
            if self._accumulated_segments
            else 0.0
        )
        return TranscriptResult(
            meeting_id=meeting_id,
            segments=self._accumulated_segments,
            language=self._agent.config.language,
            duration_seconds=duration,
            full_text=full_text,
        )
```

- [ ] **Step 2: 验证 demo 模式可用**

```bash
cd python && python -c "
import asyncio
from src.realtime.audio_buffer import AudioBuffer, AudioChunk
from src.realtime.chunk_transcriber import ChunkTranscriber

async def test():
    tc = ChunkTranscriber()
    # 模拟一个 3 秒的 chunk
    chunk = AudioChunk(data=b'\x00\x00' * 16000 * 3, chunk_id=1, offset_ms=0, is_speech=True)
    segs = await tc.transcribe_chunk(chunk)
    print(f'Got {len(segs)} segments')
    print(f'Accumulated text length: {len(tc.accumulated_text)}')
    for s in segs:
        print(f'  [{s.start:.1f}s] {s.speaker}: {s.text[:50]}...')

asyncio.run(test())
"
```

Expected: 输出 demo 片段，时间戳正确（从 0.0s 开始）

- [ ] **Step 3: Commit**

```bash
git add python/src/realtime/chunk_transcriber.py
git commit -m "feat: add ChunkTranscriber for per-chunk transcription"
```

---

### Task 5: IncrementalAnalyzer — 增量分析器

**Files:**
- Create: `python/src/realtime/incremental_analyzer.py`
- Test: `python/src/tests/test_incremental_analyzer.py`

- [ ] **Step 1: 写失败测试**

```python
# python/src/tests/test_incremental_analyzer.py
"""IncrementalAnalyzer 增量分析器测试"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.realtime.incremental_analyzer import IncrementalAnalyzer


class TestIncrementalAnalyzer:
    """IncrementalAnalyzer 单元测试（不调用真实 LLM）"""

    @pytest.fixture
    def mock_llm(self):
        """创建 mock LLM 客户端"""
        llm = MagicMock()
        llm.chat_json = AsyncMock(return_value={
            # Summary mock
            "title": "测试会议",
            "date": "2026-06-14",
            "participants": ["张总", "李明"],
            "topics": [{
                "title": "Q3 预算",
                "discussion_points": ["上调 15%"],
                "participants": ["张总", "李明"],
                "conclusion": "通过预算方案",
            }],
            "decisions": ["预算上调 15%"],
            "next_steps": ["李明整理方案"],
        })
        return llm

    @pytest.fixture
    def analyzer(self, mock_llm):
        return IncrementalAnalyzer(llm_client=mock_llm)

    def test_initial_state(self, analyzer):
        """初始状态：无待处理句子，无上次结果"""
        assert analyzer.pending_count == 0
        assert analyzer.previous_results == {}

    def test_trigger_on_sentence_count(self, analyzer):
        """累积 10 句后触发"""
        sentences = [f"句子{i}" for i in range(10)]
        assert analyzer._should_trigger(len(sentences)) is True

    def test_no_trigger_below_threshold(self, analyzer):
        """不足 10 句且时间未到，不触发"""
        sentences = [f"句子{i}" for i in range(5)]
        # 不设 last_analysis_time（模拟刚分析完）
        analyzer._last_analysis_time = asyncio.get_event_loop().time()
        assert analyzer._should_trigger(len(sentences)) is False

    def test_trigger_on_time_elapsed(self, analyzer):
        """超过 60 秒后，即使只有 1 句也触发"""
        analyzer._last_analysis_time = 0  # 很久以前
        assert analyzer._should_trigger(1) is True

    def test_sliding_window_truncation(self, analyzer):
        """滑动窗口只取最近 20 句"""
        all_sentences = [f"句子{i}" for i in range(30)]
        window = analyzer._get_window_sentences(all_sentences)
        assert len(window) == 20
        assert window[0] == "句子10"
        assert window[-1] == "句子29"

    @pytest.mark.asyncio
    async def test_run_analysis_updates_previous_results(self, analyzer, mock_llm):
        """分析后 previous_results 被更新"""
        await analyzer._run_analysis(
            recent_text="张总：我们讨论一下预算。\n李明：建议上调15%。",
            all_sentences=["张总：我们讨论一下预算。", "李明：建议上调15%。"],
            speaker_stats_text="- 张总: 占比50%\n- 李明: 占比50%",
        )
        # 验证 LLM 被调用了 3 次（summary/actions/insights）
        assert mock_llm.chat_json.call_count == 3
        # 验证 previous_results 有内容
        assert "summary" in analyzer.previous_results
        assert "actions" in analyzer.previous_results
        assert "insights" in analyzer.previous_results
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd python && python -m pytest src/tests/test_incremental_analyzer.py -v
```

Expected: 7/7 tests FAIL

- [ ] **Step 3: 实现 IncrementalAnalyzer**

```python
# python/src/realtime/incremental_analyzer.py
"""
IncrementalAnalyzer — 增量 LLM 分析器

监听新句子，按触发策略（10句 OR 60秒）定期调用 LLM，
输出增量更新的 Summary / Actions / Insights。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Awaitable

from loguru import logger

from ..integrations.llm_client import LLMClient
from ..models.schemas import (
    MeetingSummary,
    TopicSummary,
    ActionItem,
    ActionResult,
    MeetingInsight,
    SentimentType,
    SpeakerStats,
    Priority,
)


# ---- Prompt Templates ----

INCREMENTAL_SUMMARY_PROMPT = """你是一位专业的会议纪要助手。请基于已有的分析结果和新增的转写内容，更新完整的会议纪要。

## 已有分析结果
{previous_summary}

## 新增转写内容（最近 {window_size} 句）
{recent_transcript}

请合并新旧信息，输出更新后的完整会议纪要。已有结论如果在新内容中被推翻，以新内容为准。
已完成的待办不要重复出现。严格按照JSON格式输出：
{{
  "title": "会议主题",
  "date": "会议日期",
  "participants": ["参会人"],
  "topics": [
    {{
      "title": "议题名称",
      "discussion_points": ["要点"],
      "participants": ["发言人"],
      "conclusion": "结论"
    }}
  ],
  "decisions": ["决策"],
  "next_steps": ["下一步"]
}}"""

INCREMENTAL_ACTION_PROMPT = """你是一位专业的任务提取助手。请基于已有的待办和新增的转写内容，更新完整的待办列表。

## 已有待办事项
{previous_actions}

## 新增转写内容（最近 {window_size} 句）
{recent_transcript}

请合并新旧信息，输出更新后的完整待办列表。
- 已完成的不要出现
- 同一任务的后续讨论合并为一条
- 保留仍有效的原待办，标注新的截止时间和负责人
严格按照JSON格式输出：
{{
  "action_items": [
    {{
      "assignee": "负责人",
      "task": "任务描述",
      "deadline": "YYYY-MM-DD 或空",
      "priority": "low/medium/high/urgent",
      "context": "背景说明"
    }}
  ]
}}"""

INCREMENTAL_INSIGHT_PROMPT = """你是一位专业的会议分析师。请基于已有的洞察和新增的转写内容，更新完整的会议洞察。

## 已有洞察
{previous_insights}

## 新增转写内容（最近 {window_size} 句）
{recent_transcript}

## 当前发言统计
{speaker_stats}

请合并新旧信息，输出更新后的完整洞察分析。严格按照JSON格式输出：
{{
  "overall_sentiment": "positive / neutral / negative",
  "sentiment_score": 0.75,
  "efficiency_score": 8.0,
  "keywords": ["关键词"],
  "highlights": ["亮点"],
  "suggestions": ["改进建议"]
}}"""


# ---- Callback types ----

OnSummaryCallback = Callable[[MeetingSummary], Awaitable[None]]
OnActionsCallback = Callable[[ActionResult], Awaitable[None]]
OnInsightsCallback = Callable[[MeetingInsight], Awaitable[None]]


class IncrementalAnalyzer:
    """
    增量分析器。

    触发策略: 混合触发
        - 累计 10 句新句子
        - OR 距上次分析 > 60 秒

    LLM 策略: 滑动窗口 + 上次摘要
        - 取最近 20 句 + 上一次的完整分析结果
        - Summary / Actions / Insights 三者并发调用
    """

    TRIGGER_SENTENCE_COUNT = 10
    TRIGGER_TIME_SECONDS = 60
    SLIDING_WINDOW_SIZE = 20

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        on_summary: OnSummaryCallback | None = None,
        on_actions: OnActionsCallback | None = None,
        on_insights: OnInsightsCallback | None = None,
    ):
        self._llm = llm_client or LLMClient()
        self._on_summary = on_summary
        self._on_actions = on_actions
        self._on_insights = on_insights

        self._pending_count = 0
        self._all_sentences: list[str] = []
        self._last_analysis_time: float = 0.0
        self.previous_results: dict[str, Any] = {}

    # ---- public API ----

    @property
    def pending_count(self) -> int:
        return self._pending_count

    async def on_new_sentences(self, sentences: list[str]) -> None:
        """
        收到新句子时调用。检查触发条件，执行增量分析。

        Args:
            sentences: 新转写的句子文本列表
        """
        self._pending_count += len(sentences)
        self._all_sentences.extend(sentences)

        if self._should_trigger(self._pending_count):
            await self._trigger_analysis()
        else:
            logger.debug(
                f"IncrementalAnalyzer: {self._pending_count} pending, "
                f"waiting for trigger"
            )

    async def force_analyze(self) -> None:
        """强制立即执行一次完整分析（停会时调用）。"""
        self._pending_count = len(self._all_sentences)
        await self._trigger_analysis()

    # ---- internal ----

    def _should_trigger(self, pending: int) -> bool:
        """判断是否应触发分析。"""
        if pending <= 0:
            return False
        if pending >= self.TRIGGER_SENTENCE_COUNT:
            return True
        elapsed = time.time() - self._last_analysis_time
        if self._last_analysis_time > 0 and elapsed >= self.TRIGGER_TIME_SECONDS:
            return True
        return False

    def _get_window_sentences(self, all_sentences: list[str]) -> list[str]:
        """取滑动窗口：最近 N 句。"""
        if len(all_sentences) <= self.SLIDING_WINDOW_SIZE:
            return all_sentences.copy()
        return all_sentences[-self.SLIDING_WINDOW_SIZE:]

    async def _trigger_analysis(self) -> None:
        """触发一次增量分析。"""
        if not self._all_sentences:
            return

        window = self._get_window_sentences(self._all_sentences)
        recent_text = "\n".join(window)

        # 发言统计（基于累积句子，规则计算）
        speaker_stats = self._compute_simple_stats(self._all_sentences)
        stats_text = "\n".join(
            f"- {s}: {cnt} 次发言" for s, cnt in speaker_stats.items()
        )

        logger.info(
            f"IncrementalAnalyzer: running analysis "
            f"(total={len(self._all_sentences)}, window={len(window)})"
        )

        await self._run_analysis(recent_text, window, stats_text)
        self._pending_count = 0
        self._last_analysis_time = time.time()

    async def _run_analysis(
        self,
        recent_text: str,
        window_sentences: list[str],
        speaker_stats_text: str,
    ) -> None:
        """
        并发执行 Summary / Actions / Insights 三个 LLM 调用。
        """
        window_size = len(window_sentences)

        # 准备上下文：上一次分析结果
        prev_summary = self.previous_results.get("summary", {})
        prev_actions = self.previous_results.get("actions", {})
        prev_insights = self.previous_results.get("insights", {})

        async def _analyze_summary():
            try:
                messages = [
                    {"role": "system", "content": INCREMENTAL_SUMMARY_PROMPT},
                    {
                        "role": "user",
                        "content": INCREMENTAL_SUMMARY_PROMPT.replace(
                            "{previous_summary}", str(prev_summary)
                        ).replace(
                            "{recent_transcript}", recent_text
                        ).replace(
                            "{window_size}", str(window_size)
                        ),
                    },
                ]
                # 重新构造正确的 user message
                user_msg = (
                    f"## 已有分析结果\n{prev_summary}\n\n"
                    f"## 新增转写内容（最近 {window_size} 句）\n{recent_text}"
                )
                messages[1] = {"role": "user", "content": user_msg}
                result = await self._llm.chat_json(
                    messages=messages, temperature=0.3, max_tokens=4096
                )
                topics = [
                    TopicSummary(**t) for t in result.get("topics", [])
                ]
                summary = MeetingSummary(
                    title=result.get("title", "会议纪要"),
                    date=result.get("date", ""),
                    participants=result.get("participants", []),
                    topics=topics,
                    decisions=result.get("decisions", []),
                    next_steps=result.get("next_steps", []),
                )
                self.previous_results["summary"] = summary.model_dump()
                if self._on_summary:
                    await self._on_summary(summary)
                return summary
            except Exception as e:
                logger.error(f"IncrementalAnalyzer summary error: {e}")
                return None

        async def _analyze_actions():
            try:
                user_msg = (
                    f"## 已有待办事项\n{prev_actions}\n\n"
                    f"## 新增转写内容（最近 {window_size} 句）\n{recent_text}"
                )
                messages = [
                    {"role": "system", "content": INCREMENTAL_ACTION_PROMPT},
                    {"role": "user", "content": user_msg},
                ]
                result = await self._llm.chat_json(
                    messages=messages, temperature=0.2, max_tokens=2048
                )
                items = []
                for raw in result.get("action_items", []):
                    priority_str = raw.get("priority", "medium").lower()
                    try:
                        priority = Priority(priority_str)
                    except ValueError:
                        priority = Priority.MEDIUM
                    items.append(
                        ActionItem(
                            assignee=raw.get("assignee", "未指定"),
                            task=raw.get("task", ""),
                            deadline=raw.get("deadline", ""),
                            priority=priority,
                            context=raw.get("context", ""),
                            review_status="pending",
                        )
                    )
                actions_result = ActionResult(
                    meeting_id="",
                    action_items=items,
                )
                self.previous_results["actions"] = actions_result.model_dump()
                if self._on_actions:
                    await self._on_actions(actions_result)
                return actions_result
            except Exception as e:
                logger.error(f"IncrementalAnalyzer actions error: {e}")
                return None

        async def _analyze_insights():
            try:
                user_msg = (
                    f"## 已有洞察\n{prev_insights}\n\n"
                    f"## 新增转写内容（最近 {window_size} 句）\n{recent_text}\n\n"
                    f"## 当前发言统计\n{speaker_stats_text}"
                )
                messages = [
                    {"role": "system", "content": INCREMENTAL_INSIGHT_PROMPT},
                    {"role": "user", "content": user_msg},
                ]
                result = await self._llm.chat_json(
                    messages=messages, temperature=0.3, max_tokens=2048
                )
                sentiment_str = result.get("overall_sentiment", "neutral").lower()
                try:
                    sentiment = SentimentType(sentiment_str)
                except ValueError:
                    sentiment = SentimentType.NEUTRAL

                insights = MeetingInsight(
                    meeting_id="",
                    overall_sentiment=sentiment,
                    sentiment_score=result.get("sentiment_score", 0.5),
                    speaker_stats=[],  # speaker_stats 在最终分析时填充
                    efficiency_score=result.get("efficiency_score", 5.0),
                    keywords=result.get("keywords", []),
                    highlights=result.get("highlights", []),
                    suggestions=result.get("suggestions", []),
                )
                self.previous_results["insights"] = insights.model_dump()
                if self._on_insights:
                    await self._on_insights(insights)
                return insights
            except Exception as e:
                logger.error(f"IncrementalAnalyzer insights error: {e}")
                return None

        # 三者并发执行
        results = await asyncio.gather(
            _analyze_summary(),
            _analyze_actions(),
            _analyze_insights(),
            return_exceptions=True,
        )

        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error(f"IncrementalAnalyzer task {i} failed: {r}")

    @staticmethod
    def _compute_simple_stats(sentences: list[str]) -> dict[str, int]:
        """从句子列表做简易说话人计数（规则引擎，不依赖 LLM）。"""
        stats: dict[str, int] = {}
        for sent in sentences:
            if "：" in sent:
                speaker = sent.split("：")[0].strip()
            elif ":" in sent:
                speaker = sent.split(":")[0].strip()
            else:
                speaker = "Unknown"
            stats[speaker] = stats.get(speaker, 0) + 1
        return stats
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd python && python -m pytest src/tests/test_incremental_analyzer.py -v
```

Expected: 7/7 PASS

- [ ] **Step 5: Commit**

```bash
git add python/src/realtime/incremental_analyzer.py python/src/tests/test_incremental_analyzer.py
git commit -m "feat: add IncrementalAnalyzer with sliding-window LLM updates"
```

---

### Task 6: LiveSessionManager — 会话管理器

**Files:**
- Create: `python/src/realtime/session_manager.py`

- [ ] **Step 1: 实现 LiveSessionManager**

```python
# python/src/realtime/session_manager.py
"""
LiveSessionManager — 实时会议会话管理器

协调 AudioBuffer → ChunkTranscriber → IncrementalAnalyzer 三组件流水线。
管理 WebSocket 连接和会话生命周期。
"""

from __future__ import annotations

import asyncio
import json
import uuid
import time
from typing import Any

from fastapi import WebSocket
from loguru import logger

from .audio_buffer import AudioBuffer, AudioChunk
from .chunk_transcriber import ChunkTranscriber
from .incremental_analyzer import IncrementalAnalyzer
from ..integrations.llm_client import LLMClient
from ..models.schemas import (
    TranscriptResult,
    MeetingSummary,
    ActionResult,
    MeetingInsight,
)


class LiveSessionManager:
    """
    管理单次实时会议的生命周期。

    生命周期:
        WebSocket 连接 → start → 音频流 → stop → 最终分析 → 断开

    三个 asyncio.Task:
        1. audio_task:   WebSocket 接收音频 ⇒ AudioBuffer.feed()
        2. transcribe_task: AudioBuffer.process() ⇒ ChunkTranscriber ⇒ push
        3. analyze_task:  定时器 + 句子计数 ⇒ IncrementalAnalyzer ⇒ push
    """

    def __init__(
        self,
        meeting_id: str,
        websocket: WebSocket,
        llm_client: LLMClient | None = None,
    ):
        self.meeting_id = meeting_id
        self.session_id = str(uuid.uuid4())[:8]
        self._ws = websocket
        self._llm = llm_client or LLMClient()

        self._buffer = AudioBuffer()
        self._transcriber: ChunkTranscriber | None = None
        self._analyzer: IncrementalAnalyzer | None = None

        self._running = False
        self._started_at: float = 0.0
        self._tasks: list[asyncio.Task] = []

        # 最终结果存储
        self.final_summary: MeetingSummary | None = None
        self.final_actions: ActionResult | None = None
        self.final_insights: MeetingInsight | None = None
        self.final_transcript: TranscriptResult | None = None

    async def run(self) -> None:
        """
        主入口 — 被 WebSocket 端点调用。

        流程:
        1. 等待 start 消息
        2. 启动转写和分析后台任务
        3. 循环接收消息（音频帧 / stop / ping）
        4. 收到 stop 后：flush → 最终分析 → 发送 completed
        """
        await self._ws.send_json({
            "type": "connected",
            "meeting_id": self.meeting_id,
            "session_id": self.session_id,
        })
        logger.info(f"LiveSession started: {self.meeting_id}/{self.session_id}")

        # 等待 start 消息
        started = await self._wait_for_start()
        if not started:
            return

        self._running = True
        self._started_at = time.time()

        # 创建组件
        self._transcriber = ChunkTranscriber(
            on_sentence=self._on_transcript_sentence
        )
        self._analyzer = IncrementalAnalyzer(
            llm_client=self._llm,
            on_summary=self._on_summary_update,
            on_actions=self._on_actions_update,
            on_insights=self._on_insights_update,
        )

        # 启动后台任务
        self._tasks = [
            asyncio.create_task(self._audio_loop()),
            asyncio.create_task(self._transcribe_loop()),
            asyncio.create_task(self._analyze_timer_loop()),
        ]

        # 主消息循环
        await self._message_loop()

    async def _wait_for_start(self) -> bool:
        """等待客户端发送 start 消息（超时 30 秒）。"""
        try:
            while True:
                raw = await asyncio.wait_for(self._ws.receive(), timeout=30.0)
                if "text" not in raw or not raw["text"]:
                    continue
                msg = json.loads(raw["text"])
                if msg.get("type") == "start":
                    logger.info(f"LiveSession received start: {self.meeting_id}")
                    return True
                elif msg.get("type") == "ping":
                    await self._ws.send_json({"type": "pong"})
        except asyncio.TimeoutError:
            await self._ws.send_json({
                "type": "error",
                "message": "Timeout waiting for start message",
            })
            return False
        except Exception as e:
            logger.error(f"LiveSession start error: {e}")
            return False

    async def _audio_loop(self) -> None:
        """后台任务：持续接收 WebSocket 音频帧并喂入 buffer。"""
        logger.debug("audio_loop started")
        try:
            while self._running:
                raw = await asyncio.wait_for(self._ws.receive(), timeout=1.0)
                if "bytes" in raw and raw["bytes"]:
                    self._buffer.feed(raw["bytes"])
                elif "text" in raw and raw["text"]:
                    msg = json.loads(raw["text"])
                    if msg.get("type") == "ping":
                        await self._ws.send_json({"type": "pong"})
        except asyncio.TimeoutError:
            pass  # normal — no data within 1s
        except Exception as e:
            if self._running:
                logger.error(f"audio_loop error: {e}")
        logger.debug("audio_loop stopped")

    async def _transcribe_loop(self) -> None:
        """后台任务：持续从 buffer 取 chunk → 转写 → 推送。"""
        logger.debug("transcribe_loop started")
        try:
            while self._running:
                chunk = self._buffer.process()
                if chunk is not None and self._transcriber:
                    segments_before = self._transcriber.segment_count
                    await self._transcriber.transcribe_chunk(chunk)
                    segments_after = self._transcriber.segment_count

                    # 将新句子通知 analyzer
                    if self._analyzer and segments_after > segments_before:
                        new_count = segments_after - segments_before
                        new_texts = [
                            self._transcriber._accumulated_segments[i].text
                            for i in range(segments_before, segments_after)
                        ]
                        await self._analyzer.on_new_sentences(new_texts)
                else:
                    await asyncio.sleep(0.05)
        except Exception as e:
            if self._running:
                logger.error(f"transcribe_loop error: {e}")
        logger.debug("transcribe_loop stopped")

    async def _analyze_timer_loop(self) -> None:
        """后台任务：定时检查是否需要触发增量分析。"""
        logger.debug("analyze_timer_loop started")
        try:
            while self._running:
                await asyncio.sleep(10)  # 每 10 秒检查一次
                if not self._analyzer or self._analyzer.pending_count <= 0:
                    continue
                # 首次分析：用 _started_at；后续分析：用 _last_analysis_time
                ref_time = (
                    self._analyzer._last_analysis_time
                    if self._analyzer._last_analysis_time > 0
                    else self._started_at
                )
                elapsed = time.time() - ref_time
                if elapsed >= IncrementalAnalyzer.TRIGGER_TIME_SECONDS:
                    await self._analyzer.force_analyze()
        except Exception as e:
            if self._running:
                logger.error(f"analyze_timer_loop error: {e}")
        logger.debug("analyze_timer_loop stopped")

    async def _message_loop(self) -> None:
        """主消息循环：处理 stop 消息。"""
        try:
            while self._running:
                raw = await asyncio.wait_for(self._ws.receive(), timeout=1.0)
                if "text" in raw and raw["text"]:
                    msg = json.loads(raw["text"])
                    if msg.get("type") == "stop":
                        logger.info(f"LiveSession received stop: {self.meeting_id}")
                        await self._handle_stop()
                        break
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.error(f"message_loop error: {e}")
            await self._handle_stop()

    async def _handle_stop(self) -> None:
        """停止会话：flush buffer → 转写剩余 → 最终分析 → 发送结果。"""
        self._running = False

        # 取消后台任务
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

        # Flush buffer 中剩余音频
        remaining = self._buffer.flush()
        if remaining and self._transcriber:
            await self._transcriber.transcribe_chunk(remaining)

        # 最终分析（全量文本）
        if self._transcriber and self._analyzer and self._transcriber.accumulated_text:
            await self._analyzer.force_analyze()

        # 构建最终 TranscriptResult
        if self._transcriber:
            self.final_transcript = self._transcriber.build_transcript_result(
                self.meeting_id
            )

        # 发送完成消息
        elapsed = time.time() - self._started_at if self._started_at else 0
        await self._ws.send_json({
            "type": "completed",
            "meeting_id": self.meeting_id,
            "session_id": self.session_id,
            "duration_seconds": round(elapsed, 1),
            "segment_count": (
                self._transcriber.segment_count if self._transcriber else 0
            ),
            "status": "completed",
        })
        logger.info(
            f"LiveSession completed: {self.meeting_id}/{self.session_id} "
            f"({elapsed:.1f}s)"
        )

    # ---- WebSocket 推送回调 ----

    async def _on_transcript_sentence(self, segment) -> None:
        """新句子就绪 → 推送 transcript_delta。"""
        try:
            await self._ws.send_json({
                "type": "transcript_delta",
                "data": segment.model_dump(),
            })
        except Exception as e:
            logger.error(f"Failed to send transcript_delta: {e}")

    async def _on_summary_update(self, summary: MeetingSummary) -> None:
        self.final_summary = summary
        try:
            await self._ws.send_json({
                "type": "summary_update",
                "data": summary.model_dump(),
            })
        except Exception as e:
            logger.error(f"Failed to send summary_update: {e}")

    async def _on_actions_update(self, actions: ActionResult) -> None:
        self.final_actions = actions
        try:
            await self._ws.send_json({
                "type": "actions_update",
                "data": actions.model_dump(),
            })
        except Exception as e:
            logger.error(f"Failed to send actions_update: {e}")

    async def _on_insights_update(self, insights: MeetingInsight) -> None:
        self.final_insights = insights
        try:
            await self._ws.send_json({
                "type": "insights_update",
                "data": insights.model_dump(),
            })
        except Exception as e:
            logger.error(f"Failed to send insights_update: {e}")
```

- [ ] **Step 2: 验证模块可导入**

```bash
cd python && python -c "from src.realtime.session_manager import LiveSessionManager; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add python/src/realtime/session_manager.py
git commit -m "feat: add LiveSessionManager for real-time session orchestration"
```

---

### Task 7: WebSocket 端点 — /ws/live/{id}

**Files:**
- Modify: `python/src/websocket/server.py`

- [ ] **Step 1: 添加 /ws/live/{id} 端点**

在 `server.py` 中现有 WebSocket 端点后面（约第 143 行）、`_send_results()` 函数之前，插入新端点：

```python
# ============================================================
# 实时会议 WebSocket 端点 (NEW)
# ============================================================

from ..realtime.session_manager import LiveSessionManager


@app.websocket("/ws/live/{meeting_id}")
async def websocket_live_meeting(websocket: WebSocket, meeting_id: str):
    """
    实时会议 WebSocket 端点 — Level 2 Streaming

    协议:
    - 客户端发送:
        - 二进制 PCM 16kHz 16bit mono 音频帧
        - {"type": "start", "meeting_id": "...", "title": "..."}
        - {"type": "stop"}
        - {"type": "ping"}

    - 服务端返回:
        - {"type": "connected", "meeting_id": "...", "session_id": "..."}
        - {"type": "transcript_delta", "data": TranscriptSegment}
        - {"type": "summary_update", "data": MeetingSummary}
        - {"type": "actions_update", "data": ActionResult}
        - {"type": "insights_update", "data": MeetingInsight}
        - {"type": "completed", "meeting_id": "...", ...}
        - {"type": "error", "message": "..."}
        - {"type": "pong"}
    """
    await websocket.accept()

    session = LiveSessionManager(
        meeting_id=meeting_id,
        websocket=websocket,
    )

    try:
        await session.run()
    except Exception as e:
        logger.error(f"Live session error: {meeting_id} - {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e),
            })
        except Exception:
            pass
```

- [ ] **Step 2: 验证端点可访问（启动服务器检查路由）**

```bash
cd python && timeout 5 python -m src.main 2>&1 || true
```

Expected: 服务启动成功，Swagger docs 中出现 `/ws/live/{meeting_id}` WebSocket 端点

- [ ] **Step 3: Commit**

```bash
git add python/src/websocket/server.py
git commit -m "feat: add /ws/live/{id} WebSocket endpoint for real-time meetings"
```

---

### Task 8: useLiveSession 组合式 API

**Files:**
- Create: `python/frontend/src/composables/useLiveSession.ts`

- [ ] **Step 1: 创建 composables 目录**

```bash
mkdir -p python/frontend/src/composables
```

- [ ] **Step 2: 实现 useLiveSession.ts**

```typescript
// python/frontend/src/composables/useLiveSession.ts
import { ref, onUnmounted, type Ref } from 'vue'
import type {
  TranscriptSegment,
  MeetingSummary,
  ActionResult,
  MeetingInsight,
} from '../shared/types'

export interface LiveSessionState {
  connected: Ref<boolean>
  transcript: Ref<TranscriptSegment[]>
  summary: Ref<MeetingSummary | null>
  actions: Ref<ActionResult | null>
  insights: Ref<MeetingInsight | null>
  elapsedSeconds: Ref<number>
  error: Ref<string | null>
  isRecording: Ref<boolean>
}

export function useLiveSession(meetingId: string): LiveSessionState & {
  start: (title: string) => void
  stop: () => void
} {
  const connected = ref(false)
  const transcript = ref<TranscriptSegment[]>([])
  const summary = ref<MeetingSummary | null>(null)
  const actions = ref<ActionResult | null>(null)
  const insights = ref<MeetingInsight | null>(null)
  const elapsedSeconds = ref(0)
  const error = ref<string | null>(null)
  const isRecording = ref(false)

  let ws: WebSocket | null = null
  let audioContext: AudioContext | null = null
  let processor: ScriptProcessorNode | null = null
  let stream: MediaStream | null = null
  let timer: ReturnType<typeof setInterval> | null = null

  // ---- PCM 转换 ----
  function float32ToPCM16(buffer: Float32Array): ArrayBuffer {
    const len = buffer.length
    const pcm = new Int16Array(len)
    for (let i = 0; i < len; i++) {
      const s = Math.max(-1, Math.min(1, buffer[i]))
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
    }
    return pcm.buffer
  }

  // ---- WebSocket ----
  function connect(): WebSocket {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${location.host}/ws/live/${meetingId}`
    const socket = new WebSocket(url)
    socket.binaryType = 'arraybuffer'

    socket.onopen = () => {
      connected.value = true
    }

    socket.onmessage = (event: MessageEvent) => {
      if (event.data instanceof ArrayBuffer) return // 忽略二进制回显

      try {
        const msg = JSON.parse(event.data)
        switch (msg.type) {
          case 'connected':
            connected.value = true
            break
          case 'transcript_delta':
            transcript.value = [...transcript.value, msg.data as TranscriptSegment]
            break
          case 'summary_update':
            summary.value = msg.data as MeetingSummary
            break
          case 'actions_update':
            actions.value = msg.data as ActionResult
            break
          case 'insights_update':
            insights.value = msg.data as MeetingInsight
            break
          case 'completed':
            isRecording.value = false
            stopTimer()
            break
          case 'error':
            error.value = msg.message
            break
          case 'pong':
            break
        }
      } catch {
        // ignore parse errors
      }
    }

    socket.onclose = () => {
      connected.value = false
      isRecording.value = false
      stopTimer()
    }

    socket.onerror = () => {
      error.value = 'WebSocket 连接失败'
    }

    return socket
  }

  // ---- 麦克风 ----
  async function startMic(): Promise<void> {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
        },
      })

      audioContext = new AudioContext({ sampleRate: 16000 })
      const source = audioContext.createMediaStreamSource(stream)
      processor = audioContext.createScriptProcessor(4096, 1, 1)

      processor.onaudioprocess = (e: AudioProcessingEvent) => {
        if (!ws || ws.readyState !== WebSocket.OPEN || !isRecording.value) return
        const inputData = e.inputBuffer.getChannelData(0)
        const pcm = float32ToPCM16(inputData)
        ws.send(pcm)
      }

      source.connect(processor)
      processor.connect(audioContext.destination)
    } catch (err: any) {
      if (err.name === 'NotAllowedError') {
        error.value = '麦克风权限被拒绝，请在浏览器设置中允许麦克风访问'
      } else {
        error.value = `麦克风初始化失败: ${err.message}`
      }
      throw err
    }
  }

  // ---- 计时器 ----
  function startTimer(): void {
    const startTime = Date.now()
    timer = setInterval(() => {
      elapsedSeconds.value = Math.floor((Date.now() - startTime) / 1000)
    }, 1000)
  }

  function stopTimer(): void {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  // ---- Public API ----
  async function start(title: string): Promise<void> {
    error.value = null
    transcript.value = []
    summary.value = null
    actions.value = null
    insights.value = null

    ws = connect()

    // Wait for connection
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Connection timeout')), 10000)
      ws!.onopen = () => {
        clearTimeout(timeout)
        // Send start message
        ws!.send(JSON.stringify({ type: 'start', meeting_id: meetingId, title }))
        resolve()
      }
      ws!.onerror = () => {
        clearTimeout(timeout)
        reject(new Error('Connection failed'))
      }
    })

    await startMic()
    isRecording.value = true
    startTimer()
  }

  function stop(): void {
    isRecording.value = false
    stopTimer()

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'stop' }))
    }

    // 清理音频资源
    if (processor) {
      processor.disconnect()
      processor = null
    }
    if (audioContext) {
      audioContext.close()
      audioContext = null
    }
    if (stream) {
      stream.getTracks().forEach((t) => t.stop())
      stream = null
    }
  }

  onUnmounted(() => {
    stop()
    if (ws) {
      ws.close()
      ws = null
    }
  })

  return {
    connected,
    transcript,
    summary,
    actions,
    insights,
    elapsedSeconds,
    error,
    isRecording,
    start,
    stop,
  }
}
```

- [ ] **Step 3: 验证 TypeScript 编译**

```bash
cd python/frontend && npx vue-tsc --noEmit src/composables/useLiveSession.ts 2>&1 | head -20
```

Expected: 无类型错误（或仅有未使用变量的 warning）

- [ ] **Step 4: Commit**

```bash
git add python/frontend/src/composables/useLiveSession.ts
git commit -m "feat: add useLiveSession composable (WebSocket + mic capture)"
```

---

### Task 9: LiveMeetingView.vue — 实时仪表盘

**Files:**
- Create: `python/frontend/src/views/LiveMeetingView.vue`

- [ ] **Step 1: 实现 LiveMeetingView.vue**

```vue
<!-- python/frontend/src/views/LiveMeetingView.vue -->
<template>
  <div class="live-container">
    <!-- 顶部状态栏 -->
    <n-card size="small" :bordered="false" style="margin-bottom: 12px">
      <n-space align="center" justify="space-between">
        <n-space align="center">
          <n-tag :type="isRecording ? 'error' : 'default'" round>
            {{ isRecording ? '🔴 会议进行中' : '⏸ 已停止' }}
          </n-tag>
          <n-text depth="2">
            {{ formatTime(elapsedSeconds) }}
          </n-text>
          <n-text v-if="transcript.length" depth="3">
            · {{ transcript.length }} 句 · {{ speakerCount }} 人发言
          </n-text>
        </n-space>
        <n-space v-if="!isRecording && transcript.length">
          <n-button type="primary" size="small" @click="$router.push('/history')">
            查看历史记录
          </n-button>
        </n-space>
      </n-space>
    </n-card>

    <!-- 错误提示 -->
    <n-alert v-if="error" type="error" :title="error" closable @close="error = null"
      style="margin-bottom: 12px" />

    <!-- 主内容：左右分栏 -->
    <n-split direction="horizontal" :default-size="0.55" :min="0.3" :max="0.7"
      style="height: calc(100vh - 240px)">
      <template #1>
        <!-- 左栏：实时转写 -->
        <n-card title="📝 实时转写" size="small" :bordered="false"
          style="height: 100%; overflow: hidden">
          <div class="transcript-stream" ref="transcriptEl">
            <div v-if="!transcript.length && isRecording" class="transcript-waiting">
              <n-text depth="3">等待识别结果...</n-text>
            </div>
            <div v-for="(seg, idx) in transcript" :key="idx"
              class="transcript-line"
              :class="{ 'transcript-new': idx === transcript.length - 1 && isRecording }"
            >
              <n-tag :bordered="false" size="tiny"
                :style="{ background: speakerColor(seg.speaker) }">
                {{ seg.speaker }}
              </n-tag>
              <span class="transcript-time">{{ formatTimestamp(seg.start) }}</span>
              <span class="transcript-text">{{ seg.text }}</span>
            </div>
            <div v-if="isRecording" class="transcript-cursor">▊</div>
          </div>
        </n-card>
      </template>
      <template #2>
        <!-- 右栏：动态洞察 -->
        <n-scrollbar style="height: 100%">
          <n-space vertical size="medium">
            <!-- 实时摘要 -->
            <n-card title="📋 实时摘要" size="small">
              <SummaryPanel :summary="summary || undefined" />
            </n-card>

            <!-- 待办事项（只读模式） -->
            <n-card title="📌 待办事项" size="small">
              <ActionsPanel
                v-if="actions"
                :actions="actions"
                :meeting-id="meetingId"
                :reviewed="true"
              />
              <n-empty v-else description="暂无待办" size="small" />
            </n-card>

            <!-- 洞察 -->
            <n-card title="💡 会议洞察" size="small">
              <InsightsPanel :insights="insights || undefined" />
            </n-card>

            <!-- 上次更新 -->
            <n-text depth="3" style="text-align: center; display: block; font-size: 12px">
              {{ insights ? `✅ 分析进行中` : '⏳ 等待首次分析...' }}
            </n-text>
          </n-space>
        </n-scrollbar>
      </template>
    </n-split>

    <!-- 底部控制栏 -->
    <n-card size="small" :bordered="false" style="margin-top: 12px">
      <n-space justify="center" align="center">
        <n-button
          v-if="!isRecording"
          type="primary"
          size="large"
          @click="startMeeting"
          :loading="connecting"
        >
          🎙 开始会议
        </n-button>
        <n-button
          v-else
          type="error"
          size="large"
          @click="stopMeeting"
        >
          ⏹ 结束会议
        </n-button>
      </n-space>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useLiveSession } from '../composables/useLiveSession'
import SummaryPanel from '../components/SummaryPanel.vue'
import ActionsPanel from '../components/ActionsPanel.vue'
import InsightsPanel from '../components/InsightsPanel.vue'

const route = useRoute()
const router = useRouter()
const meetingId = (route.params.meetingId as string) || `live-${Date.now()}`

const {
  connected,
  transcript,
  summary,
  actions,
  insights,
  elapsedSeconds,
  error,
  isRecording,
  start,
  stop,
} = useLiveSession(meetingId)

const connecting = ref(false)
const transcriptEl = ref<HTMLElement | null>(null)

// ---- computed ----
const speakerNames = computed(() => {
  const names = new Set<string>()
  transcript.value.forEach((s) => names.add(s.speaker))
  return [...names]
})
const speakerCount = computed(() => speakerNames.value.length)

// ---- Speaker color ----
const speakerColors = [
  'rgba(32, 128, 240, 0.15)', 'rgba(24, 160, 88, 0.15)',
  'rgba(240, 160, 32, 0.15)', 'rgba(208, 48, 80, 0.15)',
  'rgba(124, 58, 237, 0.15)',
]
function speakerColor(name: string): string {
  const idx = name.charCodeAt(0) % speakerColors.length
  return speakerColors[idx]
}

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}

function formatTimestamp(s: number): string {
  const min = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${min.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`
}

// ---- 自动滚动 ----
watch(
  () => transcript.value.length,
  async () => {
    await nextTick()
    if (transcriptEl.value) {
      transcriptEl.value.scrollTop = transcriptEl.value.scrollHeight
    }
  }
)

// ---- actions ----
async function startMeeting() {
  connecting.value = true
  try {
    await start('实时会议')
  } catch (e: any) {
    error.value = e.message || '启动失败'
  } finally {
    connecting.value = false
  }
}

function stopMeeting() {
  stop()
}
</script>

<style scoped>
.live-container {
  padding: 12px;
  max-width: 1400px;
  margin: 0 auto;
}

.transcript-stream {
  height: 100%;
  overflow-y: auto;
  padding: 8px;
}

.transcript-line {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 4px 8px;
  margin-bottom: 2px;
  border-radius: 4px;
  font-size: 14px;
  line-height: 1.6;
}

.transcript-new {
  animation: fadeIn 0.3s ease-in;
}

@keyframes fadeIn {
  from { background: rgba(32, 128, 240, 0.08); }
  to   { background: transparent; }
}

.transcript-time {
  color: #999;
  font-size: 11px;
  font-family: monospace;
  min-width: 45px;
}

.transcript-text {
  flex: 1;
}

.transcript-cursor {
  color: #999;
  font-size: 12px;
  animation: blink 1s step-end infinite;
}

@keyframes blink {
  50% { opacity: 0; }
}

.transcript-waiting {
  text-align: center;
  padding: 40px;
}
</style>
```

- [ ] **Step 2: 验证组件编译**

```bash
cd python/frontend && npx vite build 2>&1 | tail -5
```

Expected: 构建成功（无 LiveMeetingView 相关的 ERROR）

- [ ] **Step 3: Commit**

```bash
git add python/frontend/src/views/LiveMeetingView.vue
git commit -m "feat: add LiveMeetingView real-time dashboard page"
```

---

### Task 10: 路由 + 入口按钮

**Files:**
- Modify: `python/frontend/src/main.ts`
- Modify: `python/frontend/src/views/UploadView.vue`

- [ ] **Step 1: 添加路由**

在 `main.ts` 的 routes 数组中新增一行：

```typescript
const routes = [
  { path: '/', redirect: '/upload' },
  { path: '/upload', component: () => import('./views/UploadView.vue') },
  { path: '/report/:id', component: () => import('./views/ReportView.vue') },
  { path: '/history', component: () => import('./views/HistoryView.vue') },
  { path: '/live/:meetingId', component: () => import('./views/LiveMeetingView.vue') },  // NEW
]
```

- [ ] **Step 2: 在 UploadView 添加「实时会议」入口按钮**

在 `UploadView.vue` 的 `<n-card title="上传会议文件">` 中，`<n-space justify="center">` 内增加一个按钮：

```vue
<template>
  <n-space vertical size="large">
    <n-card title="上传会议文件">
      <!-- ... 现有 upload dragger ... -->
      <n-space justify="center" style="margin-top: 12px">
        <n-button @click="router.push('/live/' + generateLiveId())" type="primary">
          🎙 实时会议
        </n-button>
        <n-button @click="runDemoMode" :loading="uploading" type="tertiary">
          或运行演示模式（无需文件）
        </n-button>
      </n-space>
    </n-card>
    <!-- ... rest unchanged ... -->
  </n-space>
</template>

<script setup lang="ts">
// ... existing imports ...

function generateLiveId(): string {
  return `live-${Date.now()}`
}
</script>
```

- [ ] **Step 3: 验证前端构建**

```bash
cd python/frontend && npx vite build 2>&1 | tail -10
```

Expected: 构建成功

- [ ] **Step 4: Commit**

```bash
git add python/frontend/src/main.ts python/frontend/src/views/UploadView.vue
git commit -m "feat: add /live route and entry button in UploadView"
```

---

### Task 11: 集成测试 — 端到端 WebSocket 消息流

**Files:**
- Create: `python/src/tests/test_live_session.py`

- [ ] **Step 1: 写集成测试**

```python
# python/src/tests/test_live_session.py
"""实时会议 WebSocket 集成测试"""

import asyncio
import json
import pytest
from fastapi.testclient import TestClient
from src.websocket.server import app


@pytest.fixture
def client():
    return TestClient(app)


class TestLiveWebSocket:
    """WebSocket /ws/live/{id} 集成测试"""

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self, client):
        """连接 → 收到 connected 消息 → 断开"""
        with client.websocket_connect("/ws/live/test-live-01") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert data["meeting_id"] == "test-live-01"
            assert "session_id" in data

    @pytest.mark.asyncio
    async def test_ping_pong(self, client):
        """发送 ping → 收到 pong"""
        with client.websocket_connect("/ws/live/test-live-02") as ws:
            ws.receive_json()  # consume connected
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    @pytest.mark.asyncio
    async def test_start_stop_flow(self, client):
        """完整流程：start → 收到 completed → 断开"""
        with client.websocket_connect("/ws/live/test-live-03") as ws:
            # 1. connected
            data = ws.receive_json()
            assert data["type"] == "connected"

            # 2. start (without real audio — will use demo mode)
            ws.send_json({"type": "start", "meeting_id": "test-live-03", "title": "测试"})

            # 3. immediately stop
            ws.send_json({"type": "stop"})

            # 4. collect all messages until completed
            received_types = set()
            timeout = 15  # seconds
            start = asyncio.get_event_loop().time()
            while True:
                try:
                    raw = ws.receive()
                    if "text" in raw:
                        msg = json.loads(raw["text"])
                        received_types.add(msg["type"])
                        if msg["type"] == "completed":
                            break
                    if asyncio.get_event_loop().time() - start > timeout:
                        break
                except Exception:
                    break

            assert "completed" in received_types

    @pytest.mark.asyncio
    async def test_realtime_endpoint_exists(self, client):
        """验证 /ws/live/{id} 端点存在（通过路由检查）"""
        # FastAPI TestClient doesn't have direct route listing,
        # but connecting succeeds = endpoint exists
        try:
            with client.websocket_connect("/ws/live/test-live-04") as ws:
                data = ws.receive_json()
                assert data["type"] == "connected"
        except Exception as e:
            pytest.fail(f"WebSocket endpoint not reachable: {e}")
```

- [ ] **Step 2: 运行集成测试**

```bash
cd python && python -m pytest src/tests/test_live_session.py -v -s
```

Expected: 4/4 PASS（或至少 connected 和 ping/pong 通过）

- [ ] **Step 3: Commit**

```bash
git add python/src/tests/test_live_session.py
git commit -m "test: add WebSocket live session integration tests"
```

---

## 验证清单

全部任务完成后，运行：

```bash
# 后端单元测试
cd python && python -m pytest src/tests/test_audio_buffer.py src/tests/test_incremental_analyzer.py -v

# 后端集成测试
cd python && python -m pytest src/tests/test_live_session.py -v

# 前端构建
cd python/frontend && npx vite build

# 手动验证
# 1. python -m src.main
# 2. cd python/frontend && npm run dev
# 3. 访问 http://localhost:5173 → 点击「实时会议」
# 4. 授予麦克风权限，说话，观察转写流和洞察面板
# 5. 点击「结束会议」
```
