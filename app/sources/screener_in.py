from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone

import httpx
from selectolax.lexbor import LexborHTMLParser

from app.sources.base import NormalizedItem, SourceFetchError, make_snippet
from app.sources.watchlist import WATCHLIST_TICKERS

log = logging.getLogger(__name__)

SCREENER_URL_TEMPLATE = "https://www.screener.in/company/{symbol}/"

REQUEST_TIMEOUT = 8.0

# Per the research doc's explicit guidance for Screener.in specifically:
# sequential (no concurrency across its own tickers), randomized 2-5s delay
# between requests, realistic user-agent. Deliberately DIFFERENT from
# Moneycontrol's finding in Slice 1 (where a browser-mimicking UA got
# 403'd) -- confirmed live while building this adapter that Screener.in
# serves a normal 200 to this same browser-style UA, so no special-casing
# was needed here.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    )
}

DELAY_MIN_SECONDS = 2.0
DELAY_MAX_SECONDS = 5.0


def _parse_number(raw: str | None) -> float | None:
    if not raw:
        return None
    cleaned = raw.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


class ScreenerInAdapter:
    name = "screener_in"

    def __init__(
        self,
        watchlist: list[str] | None = None,
        http_client: httpx.AsyncClient | None = None,
        delay_seconds: tuple[float, float] | None = (DELAY_MIN_SECONDS, DELAY_MAX_SECONDS),
    ):
        self.watchlist = watchlist if watchlist is not None else WATCHLIST_TICKERS
        self.http_client = http_client
        # delay_seconds=(0, 0) (or None) lets tests disable the real delay.
        self.delay_seconds = delay_seconds

    async def fetch(self) -> list[NormalizedItem]:
        items: list[NormalizedItem] = []
        failures = 0

        for i, symbol in enumerate(self.watchlist):
            if i > 0 and self.delay_seconds:
                await asyncio.sleep(random.uniform(*self.delay_seconds))
            try:
                item = await self._fetch_one(symbol)
            except Exception as exc:  # noqa: BLE001 -- per-ticker isolation, by design
                log.warning("screener_in: %s failed: %r", symbol, exc)
                failures += 1
                continue
            if item is not None:
                items.append(item)

        if failures == len(self.watchlist) and self.watchlist:
            raise SourceFetchError(
                f"screener_in: all {len(self.watchlist)} tickers failed"
            )
        return items

    async def _fetch_one(self, symbol: str) -> NormalizedItem | None:
        url = SCREENER_URL_TEMPLATE.format(symbol=symbol)
        html = await self._get(url)

        tree = LexborHTMLParser(html)
        ratios = tree.css_first("#top-ratios")
        if ratios is None:
            raise SourceFetchError(f"screener_in: ratios table missing for {symbol}")

        pe_ratio: float | None = None
        market_cap_cr: float | None = None
        for li in ratios.css("li"):
            name_node = li.css_first(".name")
            value_node = li.css_first(".value .number")
            if name_node is None or value_node is None:
                continue
            label = name_node.text(strip=True)
            number = _parse_number(value_node.text(strip=True))
            if label == "Stock P/E":
                pe_ratio = number
            elif label == "Market Cap":
                market_cap_cr = number

        return NormalizedItem(
            source=self.name,
            headline=f"{symbol} fundamentals",
            url=url,
            published_at=datetime.now(timezone.utc),
            snippet=make_snippet(f"P/E {pe_ratio}, market cap Rs {market_cap_cr} cr"),
            ticker=symbol,
            pe_ratio=pe_ratio,
            market_cap_cr=market_cap_cr,
        )

    async def _get(self, url: str) -> str:
        if self.http_client is not None:
            response = await self._do_get(self.http_client, url)
        else:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await self._do_get(client, url)
        return response.text

    async def _do_get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        try:
            response = await client.get(url, headers=_HEADERS)
        except httpx.HTTPError as exc:
            raise SourceFetchError(f"screener_in: request failed: {exc!r}") from exc
        if response.status_code >= 400:
            raise SourceFetchError(f"screener_in: HTTP {response.status_code} from {url}")
        return response
