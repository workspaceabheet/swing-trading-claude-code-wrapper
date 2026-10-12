from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import httpx
from selectolax.lexbor import LexborHTMLParser

from app.sources.base import NormalizedItem, SourceFetchError, make_snippet

log = logging.getLogger(__name__)

TRADING_ECONOMICS_URL = "https://tradingeconomics.com/india/calendar"

REQUEST_TIMEOUT = 8.0

# Only near-term items are relevant to a days-to-two-weeks swing horizon.
WINDOW_DAYS = 7

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

# DEVIATION FROM THE DETAILED PLAN'S IMPLICIT ASSUMPTION: a generic/default
# httpx User-Agent (and no UA at all) gets a 403 from tradingeconomics.com;
# a realistic desktop-browser UA gets 200 -- confirmed live while building
# this adapter. This is the opposite finding from Slice 1's Moneycontrol
# adapter (which needed to AVOID a browser-mimicking UA) -- each site's bot
# heuristics differ, so the UA choice is adapter-local, not a shared policy.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    )
}


def _extract_date(tr) -> datetime | None:
    first_td = tr.css_first("td")
    if first_td is None:
        return None
    cls = first_td.attributes.get("class") or ""
    match = _DATE_RE.search(cls)
    if not match:
        return None
    y, m, d = (int(x) for x in match.group(1).split("-"))
    return datetime(y, m, d, tzinfo=timezone.utc)


def _text_or_none(node) -> str | None:
    if node is None:
        return None
    text = node.text(strip=True)
    return text or None


class TradingEconomicsAdapter:
    name = "trading_economics"

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        now: datetime | None = None,
    ):
        self.http_client = http_client
        self._now = now or datetime.now(timezone.utc)

    async def fetch(self) -> list[NormalizedItem]:
        html = await self._fetch_html()

        tree = LexborHTMLParser(html)
        table = tree.css_first("table#calendar")
        if table is None:
            raise SourceFetchError("trading_economics: calendar table missing from page")

        rows = table.css("tr[data-event]")
        window_start = self._now - timedelta(days=WINDOW_DAYS)
        window_end = self._now + timedelta(days=WINDOW_DAYS)

        items: list[NormalizedItem] = []
        for tr in rows:
            event_date = _extract_date(tr)
            if event_date is None or not (window_start <= event_date <= window_end):
                continue

            name_node = tr.css_first("a.calendar-event")
            indicator_name = _text_or_none(name_node)
            if not indicator_name:
                continue

            actual = _text_or_none(tr.css_first("#actual"))
            forecast = _text_or_none(tr.css_first("#forecast"))
            previous = _text_or_none(tr.css_first("#previous"))

            # "Actual" value once published, else forecast as the best
            # available near-term estimate -- per plan §4.
            indicator_value = actual or forecast

            items.append(
                NormalizedItem(
                    source=self.name,
                    headline=indicator_name,
                    url=TRADING_ECONOMICS_URL,
                    published_at=event_date,
                    snippet=make_snippet(
                        f"Actual {actual or 'n/a'}, forecast {forecast or 'n/a'}, "
                        f"previous {previous or 'n/a'}"
                    ),
                    ticker=None,
                    indicator_name=indicator_name,
                    indicator_value=indicator_value,
                )
            )
        return items

    async def _fetch_html(self) -> str:
        if self.http_client is not None:
            response = await self._do_get(self.http_client)
        else:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await self._do_get(client)
        return response.text

    async def _do_get(self, client: httpx.AsyncClient) -> httpx.Response:
        try:
            response = await client.get(TRADING_ECONOMICS_URL, headers=_HEADERS)
        except httpx.HTTPError as exc:
            raise SourceFetchError(f"trading_economics: request failed: {exc!r}") from exc
        if response.status_code >= 400:
            raise SourceFetchError(
                f"trading_economics: HTTP {response.status_code} from {TRADING_ECONOMICS_URL}"
            )
        return response
