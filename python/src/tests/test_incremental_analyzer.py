"""IncrementalAnalyzer 增量分析器测试"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.realtime.incremental_analyzer import IncrementalAnalyzer


class TestIncrementalAnalyzer:
    """IncrementalAnalyzer 单元测试（不调用真实 LLM）"""

    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.chat_json = AsyncMock(return_value={
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
            "action_items": [{
                "assignee": "李明",
                "task": "整理预算方案",
                "deadline": "2026-06-20",
                "priority": "high",
                "context": "Q3预算评审",
            }],
            "overall_sentiment": "positive",
            "sentiment_score": 0.75,
            "efficiency_score": 8.0,
            "keywords": ["预算", "Q3"],
            "highlights": ["通过了预算方案"],
            "suggestions": ["提高效率"],
        })
        return llm

    @pytest.fixture
    def analyzer(self, mock_llm):
        return IncrementalAnalyzer(llm_client=mock_llm)

    def test_initial_state(self, analyzer):
        assert analyzer.pending_count == 0
        assert analyzer.previous_results == {}

    def test_trigger_on_sentence_count(self, analyzer):
        assert analyzer._should_trigger(10) is True
        assert analyzer._should_trigger(15) is True

    def test_no_trigger_below_threshold(self, analyzer):
        import time
        analyzer._last_analysis_time = time.time()  # just now
        assert analyzer._should_trigger(5) is False

    def test_trigger_on_time_elapsed(self, analyzer):
        import time
        analyzer._last_analysis_time = time.time() - 61  # 61 seconds ago
        assert analyzer._should_trigger(1) is True

    def test_sliding_window_truncation(self, analyzer):
        all_sentences = [f"句子{i}" for i in range(30)]
        window = analyzer._get_window_sentences(all_sentences)
        assert len(window) == 20
        assert window[0] == "句子10"
        assert window[-1] == "句子29"

    def test_sliding_window_short(self, analyzer):
        all_sentences = [f"句子{i}" for i in range(5)]
        window = analyzer._get_window_sentences(all_sentences)
        assert len(window) == 5

    @pytest.mark.asyncio
    async def test_run_analysis_updates_previous_results(self, analyzer, mock_llm):
        await analyzer._run_analysis(
            recent_text="张总：我们讨论一下预算。\n李明：建议上调15%。",
            window_sentences=["张总：我们讨论一下预算。", "李明：建议上调15%。"],
            speaker_stats_text="- 张总: 占比50%\n- 李明: 占比50%",
        )
        assert mock_llm.chat_json.call_count == 3
        assert "summary" in analyzer.previous_results
        assert "actions" in analyzer.previous_results
        assert "insights" in analyzer.previous_results

    @pytest.mark.asyncio
    async def test_on_new_sentences_triggers_analysis(self, analyzer):
        sentences = [f"句子{i}" for i in range(10)]
        await analyzer.on_new_sentences(sentences)
        assert analyzer.pending_count == 0  # triggered and reset
        assert len(analyzer._all_sentences) == 10
