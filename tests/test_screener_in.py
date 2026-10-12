from pathlib import Path

import pytest

from app.sources.base import SourceFetchError
from app.sources.screener_in import SCREENER_URL_TEMPLATE, ScreenerInAdapter

FIXTURE_HTML = (Path(__file__).parent / "fixtures" / "screener_sample.html").read_text()
NO_RATIOS_HTML = "<html><body><p>no ratios here</p></body></html>"


class StubResponse:
    def __init__(self, text: str = "", status_code: int = 200):
        self.text = text
        self.status_code = status_code


class StubAsyncClient:
    def __init__(self, responses: dict[str, StubResponse]):
        self._responses = responses
        self.calls: list[str] = []

    async def get(self, url, headers=None):
        self.calls.append(url)
        return self._responses.get(url, StubResponse("not found", status_code=404))


async def test_parses_fixture_html_into_expected_item():
    url = SCREENER_URL_TEMPLATE.format(symbol="RELIANCE")
    client = StubAsyncClient({url: StubResponse(FIXTURE_HTML)})
    adapter = ScreenerInAdapter(
        watchlist=["RELIANCE"], http_client=client, delay_seconds=None
    )

    items = await adapter.fetch()

    assert len(items) == 1
    item = items[0]
    assert item.ticker == "RELIANCE"
    assert item.pe_ratio == 40.4
    assert item.market_cap_cr == 1583713.0
    assert item.source == "screener_in"


async def test_one_ticker_failure_does_not_block_others():
    url_a = SCREENER_URL_TEMPLATE.format(symbol="RELIANCE")
    url_b = SCREENER_URL_TEMPLATE.format(symbol="TCS")
    url_c = SCREENER_URL_TEMPLATE.format(symbol="BADTICKER")
    client = StubAsyncClient(
        {
            url_a: StubResponse(FIXTURE_HTML),
            url_b: StubResponse(FIXTURE_HTML),
            url_c: StubResponse("not found", status_code=404),
        }
    )
    adapter = ScreenerInAdapter(
        watchlist=["RELIANCE", "TCS", "BADTICKER"],
        http_client=client,
        delay_seconds=None,
    )

    items = await adapter.fetch()

    assert len(items) == 2
    assert {item.ticker for item in items} == {"RELIANCE", "TCS"}


async def test_retention_guarantee():
    url = SCREENER_URL_TEMPLATE.format(symbol="RELIANCE")
    client = StubAsyncClient({url: StubResponse(FIXTURE_HTML)})
    adapter = ScreenerInAdapter(
        watchlist=["RELIANCE"], http_client=client, delay_seconds=None
    )

    items = await adapter.fetch()
    assert len(items[0].snippet) <= 283
    assert "<" not in items[0].snippet


async def test_total_failure_raises():
    url = SCREENER_URL_TEMPLATE.format(symbol="RELIANCE")
    client = StubAsyncClient({url: StubResponse("not found", status_code=404)})
    adapter = ScreenerInAdapter(
        watchlist=["RELIANCE"], http_client=client, delay_seconds=None
    )

    with pytest.raises(SourceFetchError):
        await adapter.fetch()
