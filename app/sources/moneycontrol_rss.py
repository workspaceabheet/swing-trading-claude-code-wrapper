from __future__ import annotations

import calendar
import logging
from datetime import datetime, timezone

import feedparser
import httpx

from app.sources.base import NormalizedItem, SourceFetchError, make_snippet

log = logging.getLogger(__name__)

# Moneycontrol publishes several topic feeds under moneycontrol.com/rss/*.xml;
# business.xml is the broadest company-news feed and the reasonable default
# for "news/earnings/deals". Kept as a module-level constant so it can be
# swapped if the exact feed path changes without a code review.
MONEYCONTROL_RSS_URL = "https://www.moneycontrol.com/rss/business.xml"

REQUEST_TIMEOUT = 8.0  # seconds; mirrors sibling-precedent constant name/value

# Empirically (checked against the live feed while building this adapter), a
# User-Agent that mimics a full desktop browser (a long Chrome/Safari UA
# string) gets a 403 from Moneycontrol -- likely bot-detection flagging a
# browser-shaped UA that arrives without the rest of a real browser's
# headers/cookies as more suspicious than an honest, plainly-non-browser UA.
# A short, identifying, non-browser-mimicking UA is both more truthful and
# (as tested) actually gets through.
_HEADERS = {"User-Agent": "swingtrade-local/0.1 (personal RSS reader; non-commercial)"}


def _parse_published_at(entry) -> datetime:
    """Converts feedparser's `published_parsed` (a UTC-normalized
    time.struct_time) into a tz-aware UTC datetime. Falls back to "now" (with
    a warning) if the feed omits a usable date -- one malformed entry's date
    must never fail the whole fetch."""
    struct = getattr(entry, "published_parsed", None) or getattr(
        entry, "updated_parsed", None
    )
    if struct is None:
        log.warning("moneycontrol_rss: entry missing a parsable date, using now()")
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(calendar.timegm(struct), tz=timezone.utc)


class MoneycontrolRSSAdapter:
    name = "moneycontrol_rss"

    def __init__(
        self,
        url: str = MONEYCONTROL_RSS_URL,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.url = url
        self.http_client = http_client

    async def fetch(self) -> list[NormalizedItem]:
        raw_bytes = await self._fetch_raw()
        feed = feedparser.parse(raw_bytes)

        # feedparser sets `bozo` (truthy) when the document couldn't be parsed
        # as well-formed XML/Atom/RSS; `bozo_exception` carries the cause. A
        # bozo feed with zero entries is a genuine parse failure, not "no new
        # items" -- but some feeds set bozo for a minor non-fatal quirk while
        # still yielding entries, so only raise when there's nothing to show.
        if feed.bozo and not feed.entries:
            raise SourceFetchError(
                f"moneycontrol_rss: failed to parse feed: {feed.get('bozo_exception')!r}"
            )

        items: list[NormalizedItem] = []
        for entry in feed.entries:
            headline = getattr(entry, "title", "").strip()
            url = getattr(entry, "link", "")
            if not headline or not url:
                continue
            items.append(
                NormalizedItem(
                    source=self.name,
                    headline=headline,
                    url=url,
                    published_at=_parse_published_at(entry),
                    snippet=make_snippet(
                        entry.get("summary") or entry.get("description") or ""
                    ),
                    ticker=None,
                )
            )
        return items

    async def _fetch_raw(self) -> bytes:
        if self.http_client is not None:
            response = await self._get(self.http_client)
        else:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await self._get(client)
        return response.content

    async def _get(self, client: httpx.AsyncClient) -> httpx.Response:
        try:
            response = await client.get(self.url, headers=_HEADERS)
        except httpx.HTTPError as exc:
            raise SourceFetchError(f"moneycontrol_rss: request failed: {exc!r}") from exc
        if response.status_code >= 400:
            raise SourceFetchError(
                f"moneycontrol_rss: HTTP {response.status_code} from {self.url}"
            )
        return response
