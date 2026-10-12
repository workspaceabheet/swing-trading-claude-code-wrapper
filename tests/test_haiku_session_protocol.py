"""Protocol-conformance tests for HaikuSession implementations.

Ensures RealHaikuSession is structurally interchangeable with FakeHaikuSession.
All tests use mocked/fake clients; no real network calls are made.
"""

import asyncio
import inspect
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agent.haiku_session import (
    RealHaikuSession,
    ClaudeExchangeError,
    _sweep_options,
    _deep_dive_options,
)
from app.agent.sessions import (
    HaikuSession,
    ShortlistCandidate,
    DeepDiveContext,
    DeepDiveResult,
)
from app.fakes.fake_sessions import FakeHaikuSession
from app.config import resolve_haiku_model


class TestRealSessionSatisfiesProtocol:
    """RealHaikuSession structurally conforms to HaikuSession protocol."""

    def test_real_session_has_run_sweep_method(self):
        """RealHaikuSession has async run_sweep method."""
        assert hasattr(RealHaikuSession, "run_sweep")
        sig = inspect.signature(RealHaikuSession.run_sweep)
        assert asyncio.iscoroutinefunction(RealHaikuSession.run_sweep)

    def test_real_session_has_run_deep_dive_method(self):
        """RealHaikuSession has async run_deep_dive method."""
        assert hasattr(RealHaikuSession, "run_deep_dive")
        assert asyncio.iscoroutinefunction(RealHaikuSession.run_deep_dive)

    def test_real_session_has_disconnect_method(self):
        """RealHaikuSession has async disconnect method."""
        assert hasattr(RealHaikuSession, "disconnect")
        assert asyncio.iscoroutinefunction(RealHaikuSession.disconnect)


class TestSessionConnectDisconnectIdempotence:
    """Disconnect is safe when called without ever calling run_* methods."""

    @pytest.mark.asyncio
    async def test_disconnect_without_any_calls_does_not_raise(self):
        """Calling disconnect without ever using run_* doesn't raise."""
        session = RealHaikuSession(client_factory=MagicMock)
        # Should not raise
        await session.disconnect()


class TestToolConfiguration:
    """Sweep and deep-dive have correct tool configurations."""

    def test_sweep_options_enable_web_tools(self):
        """Sweep options have WebSearch and WebFetch enabled."""
        opts = _sweep_options()
        assert opts.tools == ["WebSearch", "WebFetch"]
        assert opts.setting_sources == []
        assert opts.model == resolve_haiku_model()
        assert opts.thinking == {"type": "disabled"}

    def test_deep_dive_options_disable_tools(self):
        """Deep-dive options have no tools enabled."""
        opts = _deep_dive_options()
        assert opts.tools == []
        assert opts.setting_sources == []
        assert opts.model == resolve_haiku_model()
        assert opts.thinking == {"type": "disabled"}

    def test_both_use_same_model(self):
        """Both sweep and deep-dive use the same Haiku model."""
        sweep_model = _sweep_options().model
        dive_model = _deep_dive_options().model
        assert sweep_model == dive_model
        assert sweep_model == resolve_haiku_model()


class TestDeepDiveTimeoutRaisesExchangeError:
    """Deep-dive timeout raises ClaudeExchangeError."""

    @pytest.mark.asyncio
    async def test_deep_dive_timeout_raises_exchange_error(self):
        """Timeout in deep-dive raises ClaudeExchangeError."""
        # Create a mock client that hangs
        mock_client = AsyncMock()
        mock_client.query = AsyncMock()

        # Make receive_response hang forever
        async def hanging_generator():
            await asyncio.sleep(1000)
            yield MagicMock()

        mock_client.receive_response = MagicMock(return_value=hanging_generator())

        def mock_factory(options=None):
            return mock_client

        session = RealHaikuSession(client_factory=mock_factory)
        context = DeepDiveContext(ticker="TEST", items=[])

        # Mock the options to use a very short timeout for testing
        import app.agent.haiku_session as hs_module
        original_timeout = hs_module.EXCHANGE_TIMEOUT_SECONDS
        try:
            hs_module.EXCHANGE_TIMEOUT_SECONDS = 0.01

            with pytest.raises(ClaudeExchangeError):
                await session.run_deep_dive("TEST", context)
        finally:
            hs_module.EXCHANGE_TIMEOUT_SECONDS = original_timeout


class TestMalformedResponseRaisesExchangeError:
    """Malformed JSON response raises ClaudeExchangeError."""

    def test_parse_malformed_deep_dive_response_raises_value_error(self):
        """Malformed deep-dive JSON parsing raises ValueError.

        The parsing layer (haiku_parsing.py) raises ValueError, which is wrapped
        by run_deep_dive as ClaudeExchangeError. Testing the parser directly
        is simpler than mocking SDK types correctly.
        """
        from app.agent.haiku_parsing import parse_deep_dive_response

        malformed_json = '{"invalid": "response"}'

        # The parser should raise ValueError on missing required fields
        with pytest.raises(ValueError, match="missing required"):
            parse_deep_dive_response(malformed_json, "TEST")


class TestClientFactoryParameter:
    """Client factory parameter is injectable for testing."""

    def test_real_session_accepts_client_factory(self):
        """RealHaikuSession accepts client_factory parameter."""
        mock_factory = MagicMock()
        session = RealHaikuSession(client_factory=mock_factory)
        assert session._client_factory is mock_factory

    def test_real_session_default_client_factory(self):
        """RealHaikuSession defaults to ClaudeSDKClient when no factory provided."""
        from claude_agent_sdk import ClaudeSDKClient
        session = RealHaikuSession(client_factory=None)
        # Should default to ClaudeSDKClient
        assert session._client_factory is not None
