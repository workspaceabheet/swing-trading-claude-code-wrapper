from __future__ import annotations

import asyncio
import logging

from app.sources.base import NormalizedItem, SourceAdapter
from app.sources.moneycontrol_rss import MoneycontrolRSSAdapter
from app.sources.nse_bhavcopy import NSEBhavcopyAdapter
from app.sources.screener_in import ScreenerInAdapter
from app.sources.trading_economics import TradingEconomicsAdapter

log = logging.getLogger(__name__)


class SourcingAggregator:
    """Calls every configured SourceAdapter concurrently and merges results,
    isolating failures per adapter so one source going down never takes
    down sourcing for the others. Directly mirrors the sibling project's
    RealSourcingPort._query_companies pattern (asyncio.gather with
    return_exceptions=True, failures recorded by adapter name, run
    continues with the partial result)."""

    def __init__(self, adapters: list[SourceAdapter] | None = None):
        # NOTE: `adapters if adapters is not None else [...]`, NOT
        # `adapters or [...]` -- an empty list (deliberately "no adapters
        # configured", used by tests) is falsy and would otherwise silently
        # fall back to the real default four, which is not what the caller
        # asked for.
        self.adapters = (
            adapters
            if adapters is not None
            else [
                MoneycontrolRSSAdapter(),
                NSEBhavcopyAdapter(),
                ScreenerInAdapter(),
                TradingEconomicsAdapter(),
            ]
        )

    async def fetch_all(self) -> tuple[list[NormalizedItem], list[str]]:
        results = await asyncio.gather(
            *(adapter.fetch() for adapter in self.adapters),
            return_exceptions=True,
        )
        items: list[NormalizedItem] = []
        failed: list[str] = []
        for adapter, result in zip(self.adapters, results, strict=True):
            if isinstance(result, BaseException):
                log.warning("sourcing: %s failed: %r", adapter.name, result)
                failed.append(adapter.name)
            else:
                items.extend(result)
        return items, sorted(failed)
