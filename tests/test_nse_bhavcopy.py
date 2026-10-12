from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app.sources.base import SourceFetchError
from app.sources.nse_bhavcopy import IST, NSEBhavcopyAdapter

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "bhavcopy_sample.csv"
TEST_WATCHLIST = ["RELIANCE", "TCS", "INFY"]


class StubResponse:
    def __init__(self, text: str = "", status_code: int = 200):
        self.text = text
        self.status_code = status_code


class StubAsyncClient:
    """Returns responses by URL in order they're requested: a dict of
    {url: StubResponse}; any URL not in the map 404s."""

    def __init__(self, responses: dict[str, StubResponse]):
        self._responses = responses
        self.calls: list[str] = []

    async def get(self, url, headers=None):
        self.calls.append(url)
        return self._responses.get(url, StubResponse("not found", status_code=404))


def _today_url(adapter: NSEBhavcopyAdapter, offset: int = 0) -> str:
    from app.sources.nse_bhavcopy import BHAVCOPY_URL_TEMPLATE

    date = adapter._today - timedelta(days=offset)
    return BHAVCOPY_URL_TEMPLATE.format(date=date.strftime("%d%m%Y"))


async def test_parses_fixture_csv_into_expected_items():
    today = datetime(2025, 10, 10, tzinfo=IST)
    adapter = NSEBhavcopyAdapter(watchlist=TEST_WATCHLIST, today=today)
    url = _today_url(adapter)
    client = StubAsyncClient({url: StubResponse(FIXTURE_PATH.read_text())})
    adapter.http_client = client

    items = await adapter.fetch()

    assert len(items) == 3
    by_ticker = {item.ticker: item for item in items}
    assert set(by_ticker) == {"RELIANCE", "TCS", "INFY"}

    reliance = by_ticker["RELIANCE"]
    assert reliance.close == 1381.70
    assert reliance.prev_close == 1377.80
    assert reliance.volume == 6373084
    assert reliance.source == "nse_bhavcopy"


async def test_retention_guarantee():
    today = datetime(2025, 10, 10, tzinfo=IST)
    adapter = NSEBhavcopyAdapter(watchlist=TEST_WATCHLIST, today=today)
    url = _today_url(adapter)
    client = StubAsyncClient({url: StubResponse(FIXTURE_PATH.read_text())})
    adapter.http_client = client

    items = await adapter.fetch()
    for item in items:
        assert len(item.snippet) <= 283
        assert "DELIV_PER" not in item.snippet  # never the raw CSV row text


async def test_fetch_raises_on_missing_file():
    today = datetime(2025, 10, 10, tzinfo=IST)
    adapter = NSEBhavcopyAdapter(watchlist=TEST_WATCHLIST, today=today)
    client = StubAsyncClient({})  # every URL 404s
    adapter.http_client = client

    with pytest.raises(SourceFetchError):
        await adapter.fetch()


async def test_date_fallback_walks_backward():
    today = datetime(2025, 10, 10, tzinfo=IST)
    adapter = NSEBhavcopyAdapter(watchlist=TEST_WATCHLIST, today=today)
    today_url = _today_url(adapter, offset=0)
    yesterday_url = _today_url(adapter, offset=1)
    client = StubAsyncClient(
        {
            today_url: StubResponse("not found", status_code=404),
            yesterday_url: StubResponse(FIXTURE_PATH.read_text()),
        }
    )
    adapter.http_client = client

    items = await adapter.fetch()

    assert len(items) == 3
    assert client.calls == [today_url, yesterday_url]
