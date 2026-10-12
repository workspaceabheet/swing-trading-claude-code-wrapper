"""Real Sonnet session implementation backed by the Claude Agent SDK.

This module implements the CompilationSession protocol with a real ClaudeSDKClient.
The module is designed as an ephemeral per-call session: connection and disconnection
happen entirely within the run_compilation call, not held across calls.

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

from app.agent.sessions import ScoredCandidate, CompilationResult
from app.agent.prompts import build_compilation_prompt
from app.agent.compilation_parsing import parse_compilation_result
from app.config import resolve_sonnet_model

log = logging.getLogger(__name__)

EXCHANGE_TIMEOUT_SECONDS = 180.0  # Same default as Haiku

SYSTEM_PROMPT = (
    "You write polished investor-facing rationale and cross-candidate "
    "ranking commentary for a stock swing-trade tool. You NEVER compute, "
    "state, or imply a numeric score or a red/yellow/green tier for any "
    "candidate -- those are fixed by application code before you are "
    "called and are given to you only as read-only context. Your output "
    "schema has no field for a score or tier; do not invent one."
)


async def _collect_text(client: Any) -> str:
    """Drains client.receive_response() for the query just sent, through the
    terminating ResultMessage. Returns every top-level TextBlock's text
    concatenated. Raises Exception on an error result (e.g. a rate limit).

    Same pattern as haiku_session.py's collect_text.
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
        raise Exception(f"agent returned an error result: {detail}")
    text = "".join(parts).strip() or ((result.result or "").strip() if result else "")
    if not text:
        raise Exception("agent returned an empty response")
    return text


async def _collect_text_and_cost(client: Any) -> tuple[str, float]:
    """Like _collect_text, but also returns the exchange's ResultMessage.total_cost_usd.

    Returns:
        Tuple of (text, cost_usd) where cost_usd is the SDK-reported total_cost_usd,
        or 0.0 if the SDK returns None (e.g. cache-only/free exchange).

    Raises:
        Exception on an error result, timeout, or empty response.
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
        raise Exception(f"agent returned an error result: {detail}")
    text = "".join(parts).strip() or ((result.result or "").strip() if result else "")
    if not text:
        raise Exception("agent returned an empty response")
    cost = (result.total_cost_usd if result else None) or 0.0
    return text, cost


class SonnetCompilationSession:
    """Real CompilationSession implementation backed by ClaudeSDKClient.

    One ephemeral ClaudeSDKClient per call: connect() just before
    run_compilation, disconnect() in a finally block right after. Never
    held across calls, never constructed until the Haiku session for this
    run has already fully disconnected (enforced by the orchestrator).

    Tracks per-call costs from ResultMessage.total_cost_usd and exposes them via
    get_accumulated_costs().
    """

    def __init__(self, client_factory=None):
        """Initialize a SonnetCompilationSession.

        Args:
            client_factory: Optional callable that returns ClaudeSDKClient instances.
                Defaults to the standard ClaudeSDKClient constructor.
                Used for testing with mock clients.
        """
        self._client_factory = client_factory or ClaudeSDKClient
        self._compilation_cost_usd: float = 0.0

    async def run_compilation(
        self, candidates: list[ScoredCandidate]
    ) -> CompilationResult:
        """Run the compilation stage to polish rationale and ranking commentary.

        Args:
            candidates: list[ScoredCandidate] already in final rank order.

        Returns:
            CompilationResult with polished text for each candidate.

        Raises:
            Exception: On timeout, error result, or empty response.
            ValueError: On malformed JSON response or missing tickers.
        """
        client = self._client_factory(
            options=ClaudeAgentOptions(
                system_prompt=SYSTEM_PROMPT,
                tools=[],  # no web tools — reasons only over given candidate data
                setting_sources=[],  # keep user's CLAUDE.md/hooks out of this session
                model=resolve_sonnet_model(),
                thinking={"type": "disabled"},
            )
        )
        await client.connect()

        try:
            prompt = build_compilation_prompt(candidates)
            log.info(
                "Sonnet compilation call: model=%s tools=[] candidates=%d",
                resolve_sonnet_model(),
                len(candidates),
            )
            async with asyncio.timeout(EXCHANGE_TIMEOUT_SECONDS):
                await client.query(prompt)
                text, cost = await _collect_text_and_cost(client)
                self._compilation_cost_usd = cost
        except TimeoutError as exc:
            raise Exception(
                f"compilation timed out after {EXCHANGE_TIMEOUT_SECONDS:.0f}s"
            ) from exc
        except Exception as e:
            log.error("Sonnet compilation call failed: %s", e, exc_info=True)
            raise Exception(f"compilation call failed: {e}") from e
        finally:
            try:
                await client.disconnect()
            except Exception:
                log.warning("error disconnecting compilation client", exc_info=True)

        try:
            expected_tickers = [c.ticker for c in candidates]
            return parse_compilation_result(text, expected_tickers)
        except ValueError as e:
            raise ValueError(f"failed to parse compilation response: {e}") from e

    def get_accumulated_costs(self) -> dict[str, float]:
        """Return accumulated costs from all calls made by this session.

        Returns:
            dict with key 'compilation' where:
              - 'compilation': total cost of the compilation call (0.0 if not called)
        """
        return {
            'compilation': self._compilation_cost_usd,
        }
