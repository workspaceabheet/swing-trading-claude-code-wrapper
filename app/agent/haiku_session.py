"""Real Haiku session implementation backed by the Claude Agent SDK.

This module implements the HaikuSession protocol with a real ClaudeSDKClient.
The module is designed as an ephemeral per-run session: connection and disconnection
happen at the run boundaries, not per individual call (those calls are internal).

Architecture note: The SDK's ClaudeAgentOptions is connect-time-only. The sweep call
needs tools enabled (WebSearch, WebFetch), while deep-dive calls need tools disabled
(pure reasoning). The Haiku stage uses:
  1. sweep_client: connected once, queried once, disconnected immediately after
  2. one fresh deep_dive client PER call: connected, queried once, disconnected
     immediately after -- this keeps concurrent deep-dive calls isolated from each
     other (a single ClaudeSDKClient is one conversational stream; overlapping
     query()/receive_response() calls on a shared client would interleave/corrupt).

This is transparent to the caller: RealHaikuSession presents a single logical session
(one connect/disconnect boundary at the run level for the sweep client), but internally
manages per-call ephemeral clients for deep-dive.

Verified against claude-agent-sdk==0.2.163.
"""

import asyncio
import logging
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

from app.agent.sessions import (
    HaikuSession,
    ShortlistCandidate,
    DeepDiveContext,
    DeepDiveResult,
)
from app.agent.prompts import build_sweep_prompt, build_deep_dive_prompt
from app.agent.haiku_parsing import parse_sweep_response, parse_deep_dive_response
from app.config import resolve_haiku_model

log = logging.getLogger(__name__)

EXCHANGE_TIMEOUT_SECONDS = 180.0  # Same default as job-finder


class ClaudeExchangeError(Exception):
    """One LLM exchange failed (error result, timeout, or empty reply)."""


async def collect_text(client: Any) -> str:
    """Drains client.receive_response() for the query just sent, through the
    terminating ResultMessage. Returns every top-level TextBlock's text
    concatenated (falling back to ResultMessage.result). Raises
    ClaudeExchangeError on an error result (e.g. a rate limit).

    Ported from job-finder's claude_session.py.
    """
    parts: list[str] = []
    result: ResultMessage | None = None
    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            if message.parent_tool_use_id is None:
                parts.extend(
                    b.text for b in message.content if isinstance(b, TextBlock)
                )
        elif isinstance(message, ResultMessage):
            result = message
    if result is not None and result.is_error:
        detail = result.result or result.subtype or "unknown error"
        raise ClaudeExchangeError(f"agent returned an error result: {detail}")
    text = "".join(parts).strip() or ((result.result or "").strip() if result else "")
    if not text:
        raise ClaudeExchangeError("agent returned an empty response")
    return text


async def collect_text_and_cost(client: Any) -> tuple[str, float]:
    """Like collect_text, but also returns the exchange's ResultMessage.total_cost_usd.

    Returns:
        Tuple of (text, cost_usd) where cost_usd is the SDK-reported total_cost_usd,
        or 0.0 if the SDK returns None (e.g. cache-only/free exchange).

    Raises:
        ClaudeExchangeError on an error result, timeout, or empty response.
    """
    parts: list[str] = []
    result: ResultMessage | None = None
    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            if message.parent_tool_use_id is None:
                parts.extend(
                    b.text for b in message.content if isinstance(b, TextBlock)
                )
        elif isinstance(message, ResultMessage):
            result = message
    if result is not None and result.is_error:
        detail = result.result or result.subtype or "unknown error"
        raise ClaudeExchangeError(f"agent returned an error result: {detail}")
    text = "".join(parts).strip() or ((result.result or "").strip() if result else "")
    if not text:
        raise ClaudeExchangeError("agent returned an empty response")
    cost = (result.total_cost_usd if result else None) or 0.0
    return text, cost


def _sweep_options() -> ClaudeAgentOptions:
    """ClaudeAgentOptions for the sweep call with web search/fetch enabled."""
    return ClaudeAgentOptions(
        system_prompt=(
            "You are screening Indian equity (NSE/BSE) market data to shortlist "
            "swing-trade candidates worth deeper analysis."
        ),
        tools=["WebSearch", "WebFetch"],
        setting_sources=[],
        model=resolve_haiku_model(),
        thinking={"type": "disabled"},
    )


def _deep_dive_options() -> ClaudeAgentOptions:
    """ClaudeAgentOptions for the deep-dive calls with tools disabled."""
    return ClaudeAgentOptions(
        system_prompt=(
            "You are producing a per-stock deep-dive for one shortlisted "
            "swing-trade candidate, scoring independent sub-criteria with written "
            "reasoning. You never produce a final score or tier — only sub-scores."
        ),
        tools=[],
        setting_sources=[],
        model=resolve_haiku_model(),
        thinking={"type": "disabled"},
    )


class RealHaikuSession:
    """Real HaikuSession implementation backed by ClaudeSDKClient(s).

    Manages two kinds of clients with different tool configurations:
      - sweep_client: tools on, connected/disconnected around the one sweep call
      - deep-dive clients: tools off, one fresh ClaudeSDKClient per run_deep_dive
        call, connected and disconnected entirely within that call. This makes
        concurrent run_deep_dive calls (e.g. via asyncio.gather) safe, since each
        call owns its own client/stream instead of sharing one.

    Tracks per-call costs from ResultMessage.total_cost_usd and exposes them via
    get_accumulated_costs().
    """

    def __init__(self, client_factory = None):
        """Initialize a RealHaikuSession.

        Args:
            client_factory: Optional callable that returns ClaudeSDKClient instances.
                Defaults to the standard ClaudeSDKClient constructor.
                Used for testing with mock clients.
        """
        self._client_factory = client_factory or ClaudeSDKClient
        self._sweep_client: Any | None = None
        self._sweep_cost_usd: float = 0.0
        self._deep_dive_costs_usd: list[float] = []

    async def run_sweep(self, items: list) -> list[ShortlistCandidate]:
        """Run the sweep stage to shortlist candidates.

        Args:
            items: list[NormalizedItem] from the sourcing stage.

        Returns:
            list[ShortlistCandidate] shortlisted for deep-dive.

        Raises:
            ClaudeExchangeError: On timeout, error result, or empty response.
            ValueError: On malformed JSON response.
        """
        if self._sweep_client is None:
            self._sweep_client = self._client_factory(options=_sweep_options())
            await self._sweep_client.connect()

        try:
            prompt = build_sweep_prompt(items)
            log.info(
                "Haiku sweep call: model=%s tools=%s",
                resolve_haiku_model(),
                ["WebSearch", "WebFetch"],
            )
            async with asyncio.timeout(EXCHANGE_TIMEOUT_SECONDS):
                await self._sweep_client.query(prompt)
                text, cost = await collect_text_and_cost(self._sweep_client)
                self._sweep_cost_usd = cost
        except TimeoutError as exc:
            raise ClaudeExchangeError(
                f"no response within {EXCHANGE_TIMEOUT_SECONDS:.0f}s"
            ) from exc
        except ClaudeExchangeError:
            raise
        except Exception as e:
            raise ClaudeExchangeError(f"sweep call failed: {e}") from e
        finally:
            # Disconnect sweep client immediately after its one call
            if self._sweep_client is not None:
                try:
                    await self._sweep_client.disconnect()
                except Exception:
                    log.warning("error disconnecting sweep client", exc_info=True)
                self._sweep_client = None

        try:
            return parse_sweep_response(text)
        except (ValueError, KeyError, TypeError) as e:
            raise ClaudeExchangeError(f"failed to parse sweep response: {e}") from e

    async def run_deep_dive(
        self, ticker: str, context: DeepDiveContext
    ) -> DeepDiveResult:
        """Run a deep-dive analysis for one ticker.

        Args:
            ticker: The stock ticker.
            context: DeepDiveContext with pre-fetched items for this ticker.

        Returns:
            DeepDiveResult with sub-scores and analysis.

        Raises:
            ClaudeExchangeError: On timeout, error result, or empty response.
            ValueError: On malformed JSON response.
        """
        client = self._client_factory(options=_deep_dive_options())
        await client.connect()

        try:
            prompt = build_deep_dive_prompt(ticker, context)
            log.debug("Haiku deep-dive call for %s: model=%s tools=[]", ticker, resolve_haiku_model())
            async with asyncio.timeout(EXCHANGE_TIMEOUT_SECONDS):
                await client.query(prompt)
                text, cost = await collect_text_and_cost(client)
                self._deep_dive_costs_usd.append(cost)
        except TimeoutError as exc:
            raise ClaudeExchangeError(
                f"deep-dive for {ticker} timed out after {EXCHANGE_TIMEOUT_SECONDS:.0f}s"
            ) from exc
        except ClaudeExchangeError:
            raise
        except Exception as e:
            raise ClaudeExchangeError(f"deep-dive for {ticker} failed: {e}") from e
        finally:
            try:
                await client.disconnect()
            except Exception:
                log.warning("error disconnecting deep-dive client for %s", ticker, exc_info=True)

        try:
            return parse_deep_dive_response(text, ticker)
        except (ValueError, KeyError, TypeError) as e:
            raise ClaudeExchangeError(
                f"failed to parse deep-dive response for {ticker}: {e}"
            ) from e

    async def disconnect(self) -> None:
        """No-op teardown hook, kept for orchestrator/protocol compatibility.

        Historically this tore down a shared deep-dive client. Deep-dive calls
        now each own an ephemeral client that is connected and disconnected
        entirely within run_deep_dive, so there is nothing left to tear down
        here. The sweep client is likewise already disconnected immediately
        after its one call. Safe to call multiple times or at any point.
        """
        return None

    def get_accumulated_costs(self) -> dict[str, float]:
        """Return accumulated costs from all calls made by this session.

        Returns:
            dict with keys 'sweep' and 'deep_dive' where:
              - 'sweep': total cost of the sweep call (0.0 if not called)
              - 'deep_dive': sum of all deep-dive call costs (0.0 if none called)
        """
        return {
            'sweep': self._sweep_cost_usd,
            'deep_dive': sum(self._deep_dive_costs_usd),
        }
