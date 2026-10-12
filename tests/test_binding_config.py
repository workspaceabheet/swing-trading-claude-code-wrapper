"""Hardening test: app binding configuration.

Verifies that the app binds only to 127.0.0.1 (never 0.0.0.0) and that no
auth/token-mint layer code exists (decided out of scope per spec §5/§11).
"""
import ast
import pathlib

import pytest


def test_main_module_source_never_references_0_0_0_0():
    """Assert app/main.py source never contains 0.0.0.0 as an actual bind host.

    Comments disclaiming 0.0.0.0 (e.g., "Never bind 0.0.0.0") are allowed;
    the check is that the actual uvicorn.run() call uses 127.0.0.1.
    """
    source = pathlib.Path("app/main.py").read_text()
    # The actual uvicorn.run() call must use 127.0.0.1, not 0.0.0.0
    # We check this more precisely in the AST-based test below.
    # This test just ensures no actual binding happens to 0.0.0.0 in code.
    # Comments that say "Never bind 0.0.0.0" are acceptable documentation.

    # Check that there's no line like: host="0.0.0.0" or host='0.0.0.0'
    for line in source.split("\n"):
        stripped = line.strip()
        # Skip comment-only lines
        if stripped.startswith("#"):
            continue
        # Check for actual binding to 0.0.0.0 (not in comments)
        if "host" in line and "0.0.0.0" in line and "#" in line:
            # If 0.0.0.0 appears after # (in a comment), it's OK
            before_comment = line.split("#")[0]
            if "0.0.0.0" in before_comment:
                pytest.fail(
                    f"Found 0.0.0.0 in code (not just comment): {line}; "
                    "bind only to 127.0.0.1 per spec HC6"
                )
        elif "host" in line and "0.0.0.0" in line:
            # No comment marker, so this is actual code referencing 0.0.0.0
            pytest.fail(
                f"Found 0.0.0.0 in code (not in comment): {line}; "
                "bind only to 127.0.0.1 per spec HC6"
            )


def test_uvicorn_run_call_uses_127_0_0_1():
    """Assert the uvicorn.run() call in app/main.py explicitly uses host='127.0.0.1'."""
    tree = ast.parse(pathlib.Path("app/main.py").read_text())
    found_call = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", getattr(func, "id", None))
            if name == "run":
                found_call = True
                # Check for host= keyword argument
                kwargs = {kw.arg: kw.value for kw in node.keywords}
                host_node = kwargs.get("host")
                assert host_node is not None, (
                    "uvicorn.run() call has no explicit host= kwarg; "
                    "must explicitly specify host='127.0.0.1' per spec HC6"
                )
                assert isinstance(host_node, ast.Constant) and host_node.value == "127.0.0.1", (
                    f"uvicorn.run() host must be exactly '127.0.0.1', not {host_node}"
                )
    assert found_call, "no uvicorn.run()-style call found in app/main.py"


def test_no_token_mint_or_origin_pinning_code_exists():
    """Assert no auth-layer code (token-mint, Origin-pinning) exists anywhere.

    Per spec §5/§11 (decided, out of scope for v1): no local-auth layer,
    no token-mint-on-start, no Origin/Host check. 127.0.0.1-only binding
    is the sole access-control measure.
    """
    py_files = list(pathlib.Path("app").rglob("*.py"))
    forbidden = [
        "mint_token",
        "x-app-token",
        "origin_check",
        "verify_request",
        "verify_origin",
        "token_mint",
        "auth_token",
    ]
    for path in py_files:
        low = path.read_text().lower()
        for frag in forbidden:
            assert frag not in low, (
                f"{path}: unexpected auth-layer code '{frag}' found; "
                "per spec §5/§11, no auth layer is in scope for v1 "
                "(127.0.0.1-only binding is the sole access control)"
            )
