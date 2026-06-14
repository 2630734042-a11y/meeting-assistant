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
        assert c2.offset_ms >= 2000  # first chunk is ~2s speech
