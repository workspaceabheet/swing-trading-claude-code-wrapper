"""Tests for Haiku sweep and deep-dive response parsing."""

import pytest
from app.agent.haiku_parsing import (
    parse_sweep_response,
    parse_deep_dive_response,
)
from app.agent.sessions import ShortlistCandidate


class TestParseSweepResponse:
    """Tests for parse_sweep_response."""

    def test_parses_valid_sweep_response(self):
        """Valid sweep response is parsed correctly."""
        raw = """{
            "shortlist": [
                {"ticker": "RELIANCE", "reason": "Refining margins up"},
                {"ticker": "INFY", "reason": "Large deal win"}
            ]
        }"""
        result = parse_sweep_response(raw)
        assert len(result) == 2
        assert result[0].ticker == "RELIANCE"
        assert result[0].reason == "Refining margins up"
        assert result[1].ticker == "INFY"

    def test_empty_shortlist_is_valid(self):
        """Empty shortlist is valid and returns empty list."""
        raw = '{"shortlist": []}'
        result = parse_sweep_response(raw)
        assert result == []

    def test_missing_shortlist_key_raises_error(self):
        """Missing 'shortlist' key raises ValueError."""
        raw = '{"invalid_key": []}'
        with pytest.raises(ValueError, match="shortlist"):
            parse_sweep_response(raw)

    def test_non_dict_shortlist_raises_error(self):
        """Non-list shortlist value raises ValueError."""
        raw = '{"shortlist": "not a list"}'
        with pytest.raises(ValueError, match="must be a list"):
            parse_sweep_response(raw)

    def test_missing_ticker_raises_error(self):
        """Missing ticker in candidate raises ValueError."""
        raw = '{"shortlist": [{"reason": "test"}]}'
        with pytest.raises(ValueError, match="ticker"):
            parse_sweep_response(raw)

    def test_missing_reason_raises_error(self):
        """Missing reason in candidate raises ValueError."""
        raw = '{"shortlist": [{"ticker": "TEST"}]}'
        with pytest.raises(ValueError, match="reason"):
            parse_sweep_response(raw)

    def test_empty_ticker_raises_error(self):
        """Empty ticker string raises ValueError."""
        raw = '{"shortlist": [{"ticker": "", "reason": "test"}]}'
        with pytest.raises(ValueError, match="non-empty string"):
            parse_sweep_response(raw)

    def test_malformed_json_raises_error(self):
        """Malformed JSON raises ValueError."""
        raw = '{"shortlist": [}'
        with pytest.raises(ValueError, match="Malformed JSON"):
            parse_sweep_response(raw)


class TestParseDeepDiveResponse:
    """Tests for parse_deep_dive_response."""

    def test_parses_valid_deep_dive_response(self):
        """Valid deep-dive response is parsed correctly."""
        raw = """{
            "catalyst_subscore": 32,
            "catalyst_reasoning": "Q2 refining margins up",
            "sector_momentum_subscore": 28,
            "sector_momentum_reasoning": "Energy peers up 8%",
            "macro_subscore": 20,
            "macro_reasoning": "No adverse macro prints",
            "promotional_chatter_flag": false,
            "promotional_reasoning": "Clean price action",
            "catalyst_mentioned_date": "2026-10-10",
            "expected_move_pct": 6.0,
            "hold_days": 7,
            "citations": [
                {
                    "source": "moneycontrol_rss",
                    "url": "https://example.com/article",
                    "headline": "Refining margins improve",
                    "published_at": "2026-10-10"
                }
            ]
        }"""
        result = parse_deep_dive_response(raw, "RELIANCE")
        assert result.ticker == "RELIANCE"
        assert result.catalyst_subscore == 32
        assert result.catalyst_reasoning == "Q2 refining margins up"
        assert result.sector_momentum_subscore == 28
        assert result.macro_subscore == 20
        assert result.promotional_chatter_flag is False
        assert len(result.citations) == 1
        assert result.citations[0].source == "moneycontrol_rss"

    def test_catalyst_subscore_out_of_range_raises_error(self):
        """catalyst_subscore outside [0, 40] raises ValueError."""
        for bad_score in [-1, 41, 100]:
            raw = f"""{{
                "catalyst_subscore": {bad_score},
                "catalyst_reasoning": "test",
                "sector_momentum_subscore": 20,
                "sector_momentum_reasoning": "test",
                "macro_subscore": 15,
                "macro_reasoning": "test",
                "promotional_chatter_flag": false,
                "promotional_reasoning": "test",
                "catalyst_mentioned_date": "2026-10-10",
                "expected_move_pct": 6.0,
                "hold_days": 7,
                "citations": [{{"source": "test", "url": "http://test", "headline": "test", "published_at": "2026-10-10"}}]
            }}"""
            with pytest.raises(ValueError, match="catalyst_subscore.*out of range"):
                parse_deep_dive_response(raw, "TEST")

    def test_sector_momentum_subscore_out_of_range_raises_error(self):
        """sector_momentum_subscore outside [0, 35] raises ValueError."""
        raw = """{
            "catalyst_subscore": 20,
            "catalyst_reasoning": "test",
            "sector_momentum_subscore": 36,
            "sector_momentum_reasoning": "test",
            "macro_subscore": 15,
            "macro_reasoning": "test",
            "promotional_chatter_flag": false,
            "promotional_reasoning": "test",
            "catalyst_mentioned_date": "2026-10-10",
            "expected_move_pct": 6.0,
            "hold_days": 7,
            "citations": [{"source": "test", "url": "http://test", "headline": "test", "published_at": "2026-10-10"}]
        }"""
        with pytest.raises(ValueError, match="sector_momentum_subscore.*out of range"):
            parse_deep_dive_response(raw, "TEST")

    def test_macro_subscore_invalid_value_raises_error(self):
        """macro_subscore not in {15, 20, 25} raises ValueError."""
        for bad_score in [0, 5, 6, 10, 12, 22, 30, 100]:
            raw = f"""{{
                "catalyst_subscore": 20,
                "catalyst_reasoning": "test",
                "sector_momentum_subscore": 20,
                "sector_momentum_reasoning": "test",
                "macro_subscore": {bad_score},
                "macro_reasoning": "test",
                "promotional_chatter_flag": false,
                "promotional_reasoning": "test",
                "catalyst_mentioned_date": "2026-10-10",
                "expected_move_pct": 6.0,
                "hold_days": 7,
                "citations": [{{"source": "test", "url": "http://test", "headline": "test", "published_at": "2026-10-10"}}]
            }}"""
            with pytest.raises(ValueError, match="macro_subscore.*must be one of"):
                parse_deep_dive_response(raw, "TEST")

    def test_macro_subscore_valid_values_accepted(self):
        """macro_subscore with valid values {15, 20, 25} is accepted."""
        for valid_score in [15, 20, 25]:
            raw = f"""{{
                "catalyst_subscore": 20,
                "catalyst_reasoning": "test",
                "sector_momentum_subscore": 20,
                "sector_momentum_reasoning": "test",
                "macro_subscore": {valid_score},
                "macro_reasoning": "test",
                "promotional_chatter_flag": false,
                "promotional_reasoning": "test",
                "catalyst_mentioned_date": "2026-10-10",
                "expected_move_pct": 6.0,
                "hold_days": 7,
                "citations": [{{"source": "test", "url": "http://test", "headline": "test", "published_at": "2026-10-10"}}]
            }}"""
            result = parse_deep_dive_response(raw, "TEST")
            assert result.macro_subscore == valid_score

    def test_missing_required_field_raises_error(self):
        """Missing any required field raises ValueError."""
        import json
        required_fields = [
            "catalyst_subscore",
            "catalyst_reasoning",
            "sector_momentum_subscore",
            "sector_momentum_reasoning",
            "macro_subscore",
            "macro_reasoning",
            "promotional_chatter_flag",
            "promotional_reasoning",
            "catalyst_mentioned_date",
            "expected_move_pct",
            "hold_days",
            "citations",
        ]
        base_dict = {
            "catalyst_subscore": 20,
            "catalyst_reasoning": "test",
            "sector_momentum_subscore": 20,
            "sector_momentum_reasoning": "test",
            "macro_subscore": 15,
            "macro_reasoning": "test",
            "promotional_chatter_flag": False,
            "promotional_reasoning": "test",
            "catalyst_mentioned_date": "2026-10-10",
            "expected_move_pct": 6.0,
            "hold_days": 7,
            "citations": [{"source": "test", "url": "http://test", "headline": "test", "published_at": "2026-10-10"}]
        }

        for field in required_fields:
            raw_dict = dict(base_dict)  # Make a copy
            del raw_dict[field]
            raw = json.dumps(raw_dict)
            with pytest.raises(ValueError, match="missing required"):
                parse_deep_dive_response(raw, "TEST")

    def test_empty_citations_raises_error(self):
        """Empty citations list raises ValueError."""
        raw = """{
            "catalyst_subscore": 20,
            "catalyst_reasoning": "test",
            "sector_momentum_subscore": 20,
            "sector_momentum_reasoning": "test",
            "macro_subscore": 15,
            "macro_reasoning": "test",
            "promotional_chatter_flag": false,
            "promotional_reasoning": "test",
            "catalyst_mentioned_date": "2026-10-10",
            "expected_move_pct": 6.0,
            "hold_days": 7,
            "citations": []
        }"""
        with pytest.raises(ValueError, match="at least one citation"):
            parse_deep_dive_response(raw, "TEST")

    def test_invalid_promotional_chatter_flag_type_raises_error(self):
        """promotional_chatter_flag must be bool."""
        raw = """{
            "catalyst_subscore": 20,
            "catalyst_reasoning": "test",
            "sector_momentum_subscore": 20,
            "sector_momentum_reasoning": "test",
            "macro_subscore": 15,
            "macro_reasoning": "test",
            "promotional_chatter_flag": "not a bool",
            "promotional_reasoning": "test",
            "catalyst_mentioned_date": "2026-10-10",
            "expected_move_pct": 6.0,
            "hold_days": 7,
            "citations": [{"source": "test", "url": "http://test", "headline": "test", "published_at": "2026-10-10"}]
        }"""
        with pytest.raises(TypeError, match="promotional_chatter_flag must be bool"):
            parse_deep_dive_response(raw, "TEST")

    def _base_payload(self, **overrides):
        payload = {
            "catalyst_subscore": 20,
            "catalyst_reasoning": "test",
            "sector_momentum_subscore": 20,
            "sector_momentum_reasoning": "test",
            "macro_subscore": 15,
            "macro_reasoning": "test",
            "promotional_chatter_flag": False,
            "promotional_reasoning": "test",
            "catalyst_mentioned_date": "2026-10-10",
            "expected_move_pct": 6.0,
            "hold_days": 7,
            "citations": [{"source": "test", "url": "http://test", "headline": "test", "published_at": "2026-10-10"}],
        }
        payload.update(overrides)
        return payload

    def test_expected_move_pct_in_range_accepted(self):
        """expected_move_pct within [-20, 30] is accepted and stored as a float."""
        import json
        for valid_move in [-20, -5.5, 0, 12.25, 30]:
            raw = json.dumps(self._base_payload(expected_move_pct=valid_move))
            result = parse_deep_dive_response(raw, "TEST")
            assert result.expected_move_pct == float(valid_move)

    def test_expected_move_pct_out_of_range_raises_error(self):
        """expected_move_pct outside [-20, 30] raises ValueError."""
        import json
        for bad_move in [-20.1, 30.1, -100, 1000]:
            raw = json.dumps(self._base_payload(expected_move_pct=bad_move))
            with pytest.raises(ValueError, match="expected_move_pct.*out of range"):
                parse_deep_dive_response(raw, "TEST")

    def test_expected_move_pct_wrong_type_raises_error(self):
        """expected_move_pct must be numeric, not a string or bool."""
        import json
        for bad_value in ["six percent", True, None]:
            raw = json.dumps(self._base_payload(expected_move_pct=bad_value))
            with pytest.raises(TypeError, match="expected_move_pct must be a number"):
                parse_deep_dive_response(raw, "TEST")

    def test_hold_days_in_range_accepted(self):
        """hold_days within [3, 14] is accepted."""
        import json
        for valid_days in [3, 7, 14]:
            raw = json.dumps(self._base_payload(hold_days=valid_days))
            result = parse_deep_dive_response(raw, "TEST")
            assert result.hold_days == valid_days

    def test_hold_days_out_of_range_raises_error(self):
        """hold_days outside [3, 14] raises ValueError."""
        import json
        for bad_days in [0, 1, 2, 15, 30, -5]:
            raw = json.dumps(self._base_payload(hold_days=bad_days))
            with pytest.raises(ValueError, match="hold_days.*out of range"):
                parse_deep_dive_response(raw, "TEST")

    def test_hold_days_wrong_type_raises_error(self):
        """hold_days must be an int, not a float, string, or bool."""
        import json
        for bad_value in [7.5, "seven", True]:
            raw = json.dumps(self._base_payload(hold_days=bad_value))
            with pytest.raises(TypeError, match="hold_days must be int"):
                parse_deep_dive_response(raw, "TEST")
