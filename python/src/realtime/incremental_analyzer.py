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


INCREMENTAL_SUMMARY_PROMPT = """你是一位专业的会议纪要助手。请基于已有的分析结果和新增的转写内容，更新完整的会议纪要。

## 已有分析结果
{previous_summary}

## 新增转写内容（最近 {window_size} 句）
{recent_transcript}

请合并新旧信息，输出更新后的完整会议纪要。已有结论如果在新内容中被推翻，以新内容为准。
已完成的待办不要重复出现。严格按照JSON格式输出。"""

INCREMENTAL_ACTION_PROMPT = """你是一位专业的任务提取助手。请基于已有的待办和新增的转写内容，更新完整的待办列表。

## 已有待办事项
{previous_actions}

## 新增转写内容（最近 {window_size} 句）
{recent_transcript}

请合并新旧信息，输出更新后的完整待办列表。
- 已完成的不要出现
- 同一任务的后续讨论合并为一条
- 保留仍有效的原待办，标注新的截止时间和负责人
严格按照JSON格式输出。"""

INCREMENTAL_INSIGHT_PROMPT = """你是一位专业的会议分析师。请基于已有的洞察和新增的转写内容，更新完整的会议洞察。

## 已有洞察
{previous_insights}

## 新增转写内容（最近 {window_size} 句）
{recent_transcript}

## 当前发言统计
{speaker_stats}

请合并新旧信息，输出更新后的完整洞察分析。严格按照JSON格式输出。"""


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

    @property
    def pending_count(self) -> int:
        return self._pending_count

    async def on_new_sentences(self, sentences: list[str]) -> None:
        """收到新句子时调用。"""
        self._pending_count += len(sentences)
        self._all_sentences.extend(sentences)

        if self._should_trigger(self._pending_count):
            await self._trigger_analysis()

    async def force_analyze(self) -> None:
        """强制立即执行一次完整分析。"""
        self._pending_count = len(self._all_sentences)
        await self._trigger_analysis()

    def _should_trigger(self, pending: int) -> bool:
        if pending <= 0:
            return False
        if pending >= self.TRIGGER_SENTENCE_COUNT:
            return True
        elapsed = time.time() - self._last_analysis_time
        if self._last_analysis_time > 0 and elapsed >= self.TRIGGER_TIME_SECONDS:
            return True
        return False

    def _get_window_sentences(self, all_sentences: list[str]) -> list[str]:
        if len(all_sentences) <= self.SLIDING_WINDOW_SIZE:
            return all_sentences.copy()
        return all_sentences[-self.SLIDING_WINDOW_SIZE:]

    async def _trigger_analysis(self) -> None:
        if not self._all_sentences:
            return

        window = self._get_window_sentences(self._all_sentences)
        recent_text = "\n".join(window)

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
        window_size = len(window_sentences)
        prev_summary = self.previous_results.get("summary", {})
        prev_actions = self.previous_results.get("actions", {})
        prev_insights = self.previous_results.get("insights", {})

        async def _analyze_summary():
            try:
                user_msg = (
                    f"## 已有分析结果\n{prev_summary}\n\n"
                    f"## 新增转写内容（最近 {window_size} 句）\n{recent_text}"
                )
                messages = [
                    {"role": "system", "content": INCREMENTAL_SUMMARY_PROMPT},
                    {"role": "user", "content": user_msg},
                ]
                result = await self._llm.chat_json(
                    messages=messages, temperature=0.3, max_tokens=4096
                )
                topics = [TopicSummary(**t) for t in result.get("topics", [])]
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
                actions_result = ActionResult(meeting_id="", action_items=items)
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
                    speaker_stats=[],
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
        """从句子列表做简易说话人计数。"""
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
