"""
Transcription Agent（转写Agent）
- 接收音频数据，使用 WhisperX 进行语音转文字
- 使用 pyannote-audio 进行说话人识别（Speaker Diarization）
- 输出带说话人标签和时间戳的转写文本
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np
from loguru import logger

from ..models.schemas import (
    MeetingStatus,
    TranscriptResult,
    TranscriptSegment,
)


class TranscriptionConfig:
    """转写配置"""

    def __init__(
        self,
        model_size: str = "large-v2",
        device: str = "cpu",
        compute_type: str = "float32",
        language: str = "zh",
        hf_token: str = "",
        batch_size: int = 16,
        vad_method: str = "silero",
    ):
        self.model_size = os.getenv("WHISPER_MODEL_SIZE", model_size)
        self.device = os.getenv("WHISPER_DEVICE", device)
        self.compute_type = compute_type
        self.language = os.getenv("WHISPER_LANGUAGE", language)
        self.hf_token = hf_token or os.getenv("HF_TOKEN", "")
        self.batch_size = batch_size
        self.vad_method = os.getenv("WHISPER_VAD_METHOD", vad_method)


class TranscriptionAgent:
    """
    转写Agent - Pipeline的第一个节点

    架构说明:
    1. 接收音频字节数据（来自 WebSocket 或文件上传）
    2. 使用 WhisperX 进行批量转写（比原版 Whisper 快 70x）
    3. wav2vec2 强制对齐获取精确时间戳
    4. pyannote-audio 进行说话人识别
    5. 合并结果，输出 TranscriptResult

    面试考点:
    - 为什么用 WhisperX 而不是原版 Whisper？（速度 + 时间戳精度）
    - VAD 预处理有什么作用？（降低幻觉，过滤静音段）
    - 说话人识别的原理？（speaker embedding + 聚类）
    """

    def __init__(self, config: TranscriptionConfig | None = None):
        self.config = config or TranscriptionConfig()
        self._model = None
        self._align_model = None     # None=未尝试, False=尝试失败, tuple=(model, metadata)
        self._diarize_pipeline = None
        self._initialized = False

        # 首次成功标记（全链路诊断用）
        self._first_whisper_transcribe = True
        self._first_align = True

    def _lazy_init(self):
        """
        懒加载模型 —— 避免在导入时就加载大模型。
        生产中模型应在服务启动时预热。

        如果模型加载失败（网络/SSL/未安装等），会保持 _model=None，
        后续 _transcribe() 检查到 _model 为 None 时自动降级为 demo 模式。
        """
        if self._initialized:
            return

        try:
            import whisperx

            logger.info(
                f"Loading WhisperX model: {self.config.model_size} "
                f"on {self.config.device}, vad={self.config.vad_method}"
            )
            self._model = whisperx.load_model(
                self.config.model_size,
                self.config.device,
                compute_type=self.config.compute_type,
                vad_method=self.config.vad_method,
                vad_options={
                    "vad_onset": 0.3,   # 更低→更敏感，默认0.5
                    "vad_offset": 0.2,  # 更低→更少填充静音
                },
            )
            self._initialized = True
            logger.info("WhisperX model loaded successfully")
        except ImportError:
            logger.warning(
                "WhisperX not installed, "
                "falling back to demo transcription. "
                "Install with: pip install whisperx"
            )
            self._initialized = True
        except Exception as e:
            logger.warning(
                f"WhisperX model load failed ({type(e).__name__}: {e}), "
                f"falling back to demo transcription"
            )
            self._initialized = True

    async def process(self, state: dict) -> dict:
        """
        LangGraph 节点函数 —— 执行语音转写

        Args:
            state: MeetingState 字典，包含 audio_data 字段

        Returns:
            更新后的 state，包含 transcript 和 transcript_text
        """
        meeting_id = state.get("meeting_id", "unknown")
        logger.info(f"[TranscriptionAgent] Processing meeting: {meeting_id}")

        state["status"] = MeetingStatus.TRANSCRIBING

        audio_data = state.get("audio_data", b"")
        if not audio_data:
            logger.warning("No audio data provided, using demo transcript")
            state["transcript"] = self._generate_demo_transcript(meeting_id)
            state["transcript_text"] = self._format_transcript_text(
                state["transcript"]
            )
            return state

        try:
            self._lazy_init()
            transcript = await self._transcribe(audio_data, meeting_id)
            logger.info(
                f"[TranscriptionAgent] Transcription complete: "
                f"{len(transcript.segments)} segments"
            )
            return {
                "status": MeetingStatus.TRANSCRIBING,
                "transcript": transcript,
                "transcript_text": self._format_transcript_text(transcript),
            }
        except Exception as e:
            logger.error(f"[TranscriptionAgent] Error: {e}")
            demo_transcript = self._generate_demo_transcript(meeting_id)
            return {
                "errors": [f"TranscriptionAgent: {str(e)}"],
                "status": MeetingStatus.TRANSCRIBING,
                "transcript": demo_transcript,
                "transcript_text": self._format_transcript_text(demo_transcript),
            }

    async def _transcribe(
        self, audio_data: bytes, meeting_id: str
    ) -> TranscriptResult:
        """执行实际的语音转写流程（PCM → numpy，无需 ffmpeg）。"""
        if self._model is None:
            return self._generate_demo_transcript(meeting_id)

        import whisperx

        # PCM16 bytes → float32 numpy，避免 ffmpeg 依赖
        audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

        # Step 1: WhisperX 转写
        result = self._model.transcribe(
            audio_np,
            batch_size=self.config.batch_size,
            language=self.config.language,
        )

        # Step 2: 时间戳对齐（可选，失败不阻断转写，不重试）
        if self._align_model is None:
            try:
                model_a, metadata = whisperx.load_align_model(
                    language_code=self.config.language,
                    device=self.config.device,
                )
                self._align_model = (model_a, metadata)
            except Exception as e:
                logger.warning(f"Align model load failed ({e}), skipping alignment for session")
                self._align_model = False  # 标记失败，不再重试

        if self._align_model and self._align_model is not False:
            try:
                aligned = whisperx.align(
                    result["segments"],
                    self._align_model[0],
                    self._align_model[1],
                    audio_np,
                    self.config.device,
                )
            except Exception as e:
                logger.warning(f"Alignment failed ({e}), using raw timestamps")
                aligned = result
        else:
            aligned = result

        # Step 3: 说话人识别（可选，失败不阻断转写）
        if self._diarize_pipeline is None and self.config.hf_token:
            try:
                self._diarize_pipeline = whisperx.DiarizationPipeline(
                    use_auth_token=self.config.hf_token,
                    device=self.config.device,
                )
            except Exception as e:
                logger.warning(f"Diarization pipeline load failed ({e}), skipping speaker recognition")
                self._diarize_pipeline = False

        if self._diarize_pipeline and self._diarize_pipeline is not False:
            diarize_result = self._diarize_pipeline(audio_np)
            final = whisperx.assign_word_speakers(diarize_result, aligned)
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
            meeting_id=meeting_id,
            segments=segments,
            language=self.config.language,
            duration_seconds=duration,
            full_text=full_text,
        )

    async def transcribe_bytes(
        self, audio_data: bytes, language: str | None = None
    ) -> TranscriptResult:
        """
        对原始音频字节执行转写（独立于 LangGraph state）。

        供 ChunkTranscriber 调用，避免依赖 state 字典。
        PCM 字节直接转 numpy，无需 ffmpeg 或临时文件。
        """
        lang = language or self.config.language
        if self._model is None:
            self._lazy_init()

        if self._model is None:
            return self._generate_demo_chunk_transcript(audio_data, lang)

        import whisperx

        # PCM16 bytes → float32 numpy (16kHz, mono)，直接传 WhisperX，无需 ffmpeg
        audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

        result = self._model.transcribe(
            audio_np,
            batch_size=self.config.batch_size,
            language=lang,
        )

        if self._first_whisper_transcribe:
            seg_count = len(result.get("segments", []))
            logger.info(
                f"[⑩ WhisperX.transcribe] 首次转写完成 | "
                f"segments={seg_count}, "
                f"audio_len={len(audio_np)} samples ({len(audio_np)/16000:.1f}s)"
            )
            self._first_whisper_transcribe = False

        # 诊断：转写结果为空时输出音频统计，帮助定位问题
        if len(result.get("segments", [])) == 0:
            logger.warning(
                f"WhisperX returned 0 segments: "
                f"audio_dur={len(audio_np)/16000:.1f}s, "
                f"amp_range=[{audio_np.min():.4f}, {audio_np.max():.4f}], "
                f"rms={np.sqrt(np.mean(audio_np**2)):.4f}, "
                f"vad={self.config.vad_method}"
            )

        # Step 2: 时间戳对齐（可选，失败不阻断转写，不重试）
        if self._align_model is None:
            try:
                model_a, metadata = whisperx.load_align_model(
                    language_code=lang,
                    device=self.config.device,
                )
                self._align_model = (model_a, metadata)
            except Exception as e:
                logger.warning(f"Align model load failed ({e}), skipping alignment for session")
                self._align_model = False  # 标记失败，不再重试

        if self._align_model and self._align_model is not False:
            try:
                aligned = whisperx.align(
                    result["segments"],
                    self._align_model[0],
                    self._align_model[1],
                    audio_np,
                    self.config.device,
                )
                if self._first_align:
                    logger.info(
                        f"[⑪ whisperx.align] 首次时间戳对齐成功 | "
                        f"aligned_segments={len(aligned.get('segments', []))}"
                    )
                    self._first_align = False
            except Exception as e:
                logger.warning(f"Alignment failed ({e}), using raw timestamps")
                aligned = result
        else:
            aligned = result

        if self._diarize_pipeline is None and self.config.hf_token:
            try:
                self._diarize_pipeline = whisperx.DiarizationPipeline(
                    use_auth_token=self.config.hf_token,
                    device=self.config.device,
                )
            except Exception as e:
                logger.warning(f"Diarization pipeline load failed ({e}), skipping speaker recognition")
                self._diarize_pipeline = False

        if self._diarize_pipeline and self._diarize_pipeline is not False:
            diarize_result = self._diarize_pipeline(audio_np)
            final = whisperx.assign_word_speakers(diarize_result, aligned)
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

    @staticmethod
    def _generate_demo_chunk_transcript(
        audio_data: bytes, language: str
    ) -> TranscriptResult:
        """
        为 chunk 生成模拟转写 —— 模型未加载时的降级。
        用音频长度推算 demo 的句子数。
        """
        estimated_duration = len(audio_data) / 32000.0

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
                    start=round(offset, 2),
                    end=round(offset + seg_duration, 2),
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

    @staticmethod
    def _generate_demo_transcript(meeting_id: str) -> TranscriptResult:
        """生成演示转写结果（无音频时使用）"""
        demo_segments = [
            TranscriptSegment(
                speaker="张总",
                text="好的，我们开始今天的Q3预算评审会议。首先请李明汇报一下目前的预算执行情况。",
                start=0.0, end=8.5, confidence=0.96,
            ),
            TranscriptSegment(
                speaker="李明",
                text="好的张总。截至目前，Q2预算执行率为87%，其中研发投入占比最大，达到42%。",
                start=9.0, end=16.2, confidence=0.95,
            ),
            TranscriptSegment(
                speaker="李明",
                text="Q3我们计划将预算上调15%，主要增加在AI基础设施和人才招聘方面。",
                start=16.5, end=23.1, confidence=0.94,
            ),
            TranscriptSegment(
                speaker="王芳",
                text="关于人才招聘，我建议我们重点招聘3名高级算法工程师，预算大概在每人年薪80万左右。",
                start=23.5, end=31.0, confidence=0.93,
            ),
            TranscriptSegment(
                speaker="张总",
                text="可以。李明你来负责整理Q3的详细预算方案，下周五之前提交给我审批。",
                start=31.5, end=38.2, confidence=0.97,
            ),
            TranscriptSegment(
                speaker="张总",
                text="王芳负责拟定招聘JD，本周三前完成。另外，赵伟跟进一下服务器采购的事情。",
                start=38.5, end=46.0, confidence=0.95,
            ),
            TranscriptSegment(
                speaker="赵伟",
                text="收到，我这边已经在对比几家供应商了，预计下周一可以给出采购方案。",
                start=46.5, end=52.8, confidence=0.94,
            ),
            TranscriptSegment(
                speaker="张总",
                text="好的，那今天的会议就到这里。各位辛苦了，请大家按时完成各自的任务。",
                start=53.0, end=59.5, confidence=0.96,
            ),
        ]

        full_text = "\n".join(
            f"[{s.speaker}] {s.text}" for s in demo_segments
        )

        return TranscriptResult(
            meeting_id=meeting_id,
            segments=demo_segments,
            language="zh",
            duration_seconds=59.5,
            full_text=full_text,
        )

    @staticmethod
    def _format_transcript_text(transcript: TranscriptResult) -> str:
        """将转写结果格式化为纯文本（供后续Agent使用）"""
        lines = []
        for seg in transcript.segments:
            ts = f"[{seg.start:.1f}s-{seg.end:.1f}s]"
            lines.append(f"{ts} {seg.speaker}: {seg.text}")
        return "\n".join(lines)
