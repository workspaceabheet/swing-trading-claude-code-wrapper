from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.sources.base import NormalizedItem, SourceFetchError, make_snippet
from app.sources.watchlist import WATCHLIST_TICKERS

log = logging.getLogger(__name__)

# DEVIATION FROM THE DETAILED PLAN (verified against the live site while
# building this adapter): the plan assumed NSE still serves a zipped
# cm{DD}{MON}{YYYY}bhav.csv.zip file under nsearchives.nseindia.com/content/
# historical/EQUITIES/... -- that path now 404s. NSE has since moved to a
# plain (unzipped) CSV named sec_bhavdata_full_{DDMMYYYY}.csv under
# nsearchives.nseindia.com/products/content/, confirmed with a live fetch.
# No zipfile/io.BytesIO unzip step is needed as a result -- the response
# body is already CSV text. The column layout also differs slightly from
# the plan's assumed names (space-prefixed headers like " SERIES",
# " CLOSE_PRICE", " TTL_TRD_QNTY", " PREV_CLOSE" -- NSE's real export has a
# leading space after each comma); handled below by stripping both header
# and value whitespace rather than assuming exact column names.
BHAVCOPY_URL_TEMPLATE = (
    "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date}.csv"
)

REQUEST_TIMEOUT = 8.0

IST = timezone(timedelta(hours=5, minutes=30))

# How many calendar days to walk backward looking for the most recent
# published file (handles weekends/holidays when "today's" file doesn't
# exist yet).
MAX_LOOKBACK_DAYS = 5

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    )
}


def _strip_row(row: dict) -> dict:
    return {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}


class NSEBhavcopyAdapter:
    name = "nse_bhavcopy"

    def __init__(
        self,
        watchlist: list[str] | None = None,
        http_client: httpx.AsyncClient | None = None,
        today: datetime | None = None,
    ):
        self.watchlist = set(watchlist if watchlist is not None else WATCHLIST_TICKERS)
        self.http_client = http_client
        self._today = today or datetime.now(IST)

    async def fetch(self) -> list[NormalizedItem]:
        csv_text, file_url, trade_date = await self._fetch_csv_with_fallback()

        reader = csv.DictReader(io.StringIO(csv_text))
        rows_by_symbol = {}
        for raw_row in reader:
            row = _strip_row(raw_row)
            symbol = row.get("SYMBOL", "")
            if symbol in self.watchlist and row.get("SERIES") == "EQ":
                rows_by_symbol[symbol] = row

        items: list[NormalizedItem] = []
        for symbol in self.watchlist:
            row = rows_by_symbol.get(symbol)
            if row is None:
                continue  # not in today's file (delisted, series mismatch, etc.) -- skip, don't fail the run
            try:
                close = float(row["CLOSE_PRICE"])
                prev_close = float(row["PREV_CLOSE"])
                volume = int(float(row["TTL_TRD_QNTY"]))
            except (KeyError, ValueError) as exc:
                log.warning("nse_bhavcopy: malformed row for %s: %r", symbol, exc)
                continue
            items.append(
                NormalizedItem(
                    source=self.name,
                    headline=f"{symbol} EOD — close {close}",
                    url=file_url,
                    published_at=trade_date,
                    snippet=make_snippet(
                        f"Close {close}, prev close {prev_close}, volume {volume}"
                    ),
                    ticker=symbol,
                    close=close,
                    prev_close=prev_close,
                    volume=volume,
                )
            )
        return items

    async def _fetch_csv_with_fallback(self) -> tuple[str, str, datetime]:
        last_exc: Exception | None = None
        for offset in range(MAX_LOOKBACK_DAYS + 1):
            candidate = self._today - timedelta(days=offset)
            date_str = candidate.strftime("%d%m%Y")
            url = BHAVCOPY_URL_TEMPLATE.format(date=date_str)
            try:
                text = await self._get(url)
            except SourceFetchError as exc:
                last_exc = exc
                continue
            trade_date = datetime(candidate.year, candidate.month, candidate.day, tzinfo=timezone.utc)
            return text, url, trade_date
        raise SourceFetchError(
            f"nse_bhavcopy: no bhavcopy file found in the last {MAX_LOOKBACK_DAYS} days: {last_exc!r}"
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
            raise SourceFetchError(f"nse_bhavcopy: request failed: {exc!r}") from exc
        if response.status_code >= 400:
            raise SourceFetchError(f"nse_bhavcopy: HTTP {response.status_code} from {url}")
        return response
