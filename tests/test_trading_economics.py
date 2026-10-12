from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.sources.base import SourceFetchError
from app.sources.trading_economics import TradingEconomicsAdapter

FIXTURE_HTML = (
    Path(__file__).parent / "fixtures" / "trading_economics_sample.html"
).read_text()
NO_TABLE_HTML = "<html><body><p>no calendar here</p></body></html>"

NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)


class StubResponse:
    def __init__(self, text: str = "", status_code: int = 200):
        self.text = text
        self.status_code = status_code


class StubAsyncClient:
    def __init__(self, response: StubResponse):
        self._response = response
        self.calls = 0

    async def get(self, url, headers=None):
        self.calls += 1
        return self._response


async def test_parses_fixture_into_expected_items():
    client = StubAsyncClient(StubResponse(FIXTURE_HTML))
    adapter = TradingEconomicsAdapter(http_client=client, now=NOW)

    items = await adapter.fetch()

    assert len(items) == 2  # the 2026-11-30 row is outside the +/-7-day window
    for item in items:
        assert item.ticker is None
        assert item.indicator_name

    by_name = {item.indicator_name: item for item in items}
    assert "Inflation Rate YoY" in by_name
    assert by_name["Inflation Rate YoY"].indicator_value == "5.3%"  # actual empty -> falls back to forecast
    assert by_name["Interest Rate"].indicator_value == "5.5%"  # actual present


async def test_filters_to_near_term_window():
    client = StubAsyncClient(StubResponse(FIXTURE_HTML))
    adapter = TradingEconomicsAdapter(http_client=client, now=NOW)

    items = await adapter.fetch()

    assert "GDP Growth Rate" not in {item.indicator_name for item in items}


async def test_retention_guarantee():
    client = StubAsyncClient(StubResponse(FIXTURE_HTML))
    adapter = TradingEconomicsAdapter(http_client=client, now=NOW)

    items = await adapter.fetch()
    for item in items:
        assert len(item.snippet) <= 283
        assert item.indicator_value is None or len(item.indicator_value) <= 64


async def test_fetch_raises_on_missing_table():
    client = StubAsyncClient(StubResponse(NO_TABLE_HTML))
    adapter = TradingEconomicsAdapter(http_client=client, now=NOW)

    with pytest.raises(SourceFetchError):
        await adapter.fetch()
