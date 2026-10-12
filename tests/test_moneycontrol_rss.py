from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.sources.base import SNIPPET_MAX_CHARS, SourceFetchError
from app.sources.moneycontrol_rss import MoneycontrolRSSAdapter

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "moneycontrol_sample.xml"

EMPTY_FEED_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Empty feed</title>
  <link>https://www.moneycontrol.com/rss/business.xml</link>
  <description>No items right now</description>
</channel>
</rss>
"""


class StubResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code


class StubAsyncClient:
    """Minimal httpx.AsyncClient stand-in: records calls, returns a canned
    response or raises a canned exception, so the adapter unit tests never
    touch the network."""

    def __init__(self, *, response: StubResponse | None = None, raise_exc: Exception | None = None):
        self._response = response
        self._raise_exc = raise_exc
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append(url)
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._response


@pytest.mark.asyncio
async def test_parses_fixture_into_expected_items():
    client = StubAsyncClient(response=StubResponse(FIXTURE_PATH.read_bytes()))
    adapter = MoneycontrolRSSAdapter(http_client=client)

    items = await adapter.fetch()

    assert len(items) == 4
    for item in items:
        assert item.source == "moneycontrol_rss"
        assert item.headline
        assert item.url.startswith("https://")
        assert isinstance(item.published_at, datetime)
        assert item.published_at.tzinfo is not None
        assert item.ticker is None

    first = items[0]
    assert first.headline == "Reliance Industries shares surge on Q2 earnings beat"
    assert first.published_at == datetime(2025, 10, 6, 3, 45, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_long_description_item_produces_bounded_snippet():
    client = StubAsyncClient(response=StubResponse(FIXTURE_PATH.read_bytes()))
    adapter = MoneycontrolRSSAdapter(http_client=client)

    items = await adapter.fetch()
    infosys_item = next(i for i in items if i.headline.startswith("Infosys"))

    assert len(infosys_item.snippet) <= SNIPPET_MAX_CHARS + 3
    long_original = (
        "Infosys raised its revenue growth guidance for the fiscal year "
        "citing strong deal wins and continued momentum in digital "
        "transformation engagements across its largest client verticals"
    )
    assert long_original not in infosys_item.snippet or len(infosys_item.snippet) <= SNIPPET_MAX_CHARS + 3


@pytest.mark.asyncio
async def test_fetch_raises_on_http_error():
    client = StubAsyncClient(response=StubResponse(b"", status_code=500))
    adapter = MoneycontrolRSSAdapter(http_client=client)

    with pytest.raises(SourceFetchError):
        await adapter.fetch()


@pytest.mark.asyncio
async def test_fetch_raises_on_timeout():
    client = StubAsyncClient(raise_exc=httpx.ConnectTimeout("timed out"))
    adapter = MoneycontrolRSSAdapter(http_client=client)

    with pytest.raises(SourceFetchError):
        await adapter.fetch()


@pytest.mark.asyncio
async def test_fetch_returns_empty_list_on_zero_entries():
    client = StubAsyncClient(response=StubResponse(EMPTY_FEED_XML))
    adapter = MoneycontrolRSSAdapter(http_client=client)

    items = await adapter.fetch()

    assert items == []
