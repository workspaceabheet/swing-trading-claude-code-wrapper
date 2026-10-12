import datetime as dt

from app.sources.aggregator import SourcingAggregator
from app.sources.base import NormalizedItem, SourceFetchError


class StubAdapter:
    def __init__(self, name, items=None, exc: Exception | None = None):
        self.name = name
        self._items = items or []
        self._exc = exc

    async def fetch(self):
        if self._exc is not None:
            raise self._exc
        return self._items


def _item(source, n=0):
    return NormalizedItem(
        source=source,
        headline=f"{source} headline {n}",
        url=f"https://example.com/{source}/{n}",
        published_at=dt.datetime.now(dt.timezone.utc),
        snippet=f"snippet {n}",
    )


async def test_merges_results_from_all_succeeding_adapters():
    adapters = [
        StubAdapter("a", items=[_item("a", 1)]),
        StubAdapter("b", items=[_item("b", 1), _item("b", 2)]),
        StubAdapter("c", items=[_item("c", 1)]),
        StubAdapter("d", items=[_item("d", 1)]),
    ]
    aggregator = SourcingAggregator(adapters=adapters)

    items, failed = await aggregator.fetch_all()

    assert len(items) == 5
    assert failed == []
    assert {item.source for item in items} == {"a", "b", "c", "d"}


async def test_one_adapter_failure_isolated():
    adapters = [
        StubAdapter("a", items=[_item("a", 1)]),
        StubAdapter("b", items=[_item("b", 1)]),
        StubAdapter("broken", exc=SourceFetchError("down")),
        StubAdapter("d", items=[_item("d", 1)]),
    ]
    aggregator = SourcingAggregator(adapters=adapters)

    items, failed = await aggregator.fetch_all()

    assert len(items) == 3
    assert {item.source for item in items} == {"a", "b", "d"}
    assert failed == ["broken"]


async def test_all_adapters_fail_returns_empty_not_exception():
    adapters = [
        StubAdapter("a", exc=SourceFetchError("down a")),
        StubAdapter("b", exc=SourceFetchError("down b")),
        StubAdapter("c", exc=SourceFetchError("down c")),
        StubAdapter("d", exc=SourceFetchError("down d")),
    ]
    aggregator = SourcingAggregator(adapters=adapters)

    items, failed = await aggregator.fetch_all()

    assert items == []
    assert failed == ["a", "b", "c", "d"]
