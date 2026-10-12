"""Hardening test: no brokerage SDK or order-placement code.

Verifies that no brokerage SDK imports, integration, or order-placement
code paths exist anywhere in the codebase. Per spec §4 (FR10) and §7 (HC7),
the system never places, modifies, or cancels any brokerage order and has
no brokerage credentials or order-placement integration.
"""
import ast
import pathlib


BROKERAGE_NAME_FRAGMENTS = [
    "kite",
    "zerodha",
    "kiteconnect",
    "upstox",
    "angelone",
    "angel_one",
    "icicidirect",
    "icici_direct",
    "fyers",
    "aliceblue",
    "alice_blue",
    "5paisa",
    "dhan",
    "shoonya",
    "smartapi",
]

ORDER_ENDPOINT_FRAGMENTS = [
    "/orders",
    "placeorder",
    "place_order",
    "orders/regular",
    "orders/place",  # Kite Connect's actual order-placement path shape
    "modifyorder",
    "modify_order",
    "cancelorder",
    "cancel_order",
]

PROJECT_SRC = pathlib.Path("app")


def _all_py_files():
    return list(PROJECT_SRC.rglob("*.py"))


def test_no_brokerage_sdk_imports():
    """Assert no brokerage SDK is imported anywhere in app code."""
    for path in _all_py_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                else:
                    names = [node.module or ""]
                for n in names:
                    if n:
                        low = n.lower()
                        for frag in BROKERAGE_NAME_FRAGMENTS:
                            assert frag not in low, (
                                f"{path}: forbidden brokerage-related import '{n}'; "
                                f"per spec §4 FR10 / §7 HC7, no brokerage SDK allowed"
                            )


def test_no_brokerage_substring_anywhere_in_source():
    """Assert no brokerage-related substring anywhere in source code.

    Broader than AST-level import checks: catches string-literal URLs,
    comments referencing a brokerage API, dynamic imports, etc.
    """
    for path in _all_py_files():
        text = path.read_text().lower()
        for frag in BROKERAGE_NAME_FRAGMENTS:
            assert frag not in text, (
                f"{path}: forbidden brokerage reference '{frag}'; "
                f"per spec §4 FR10 / §7 HC7, no brokerage SDK or integration allowed"
            )


def test_no_order_placement_endpoint_strings():
    """Assert no order-placement endpoint patterns exist in source code."""
    for path in _all_py_files():
        text = path.read_text().lower()
        for frag in ORDER_ENDPOINT_FRAGMENTS:
            assert frag not in text, (
                f"{path}: possible order-placement endpoint reference '{frag}'; "
                f"per spec §4 FR10, no code path capable of placing/modifying/cancelling orders"
            )


def test_pyproject_has_no_brokerage_dependency():
    """Assert pyproject.toml has no brokerage-related dependencies."""
    pyproject = pathlib.Path("pyproject.toml").read_text().lower()
    for frag in BROKERAGE_NAME_FRAGMENTS:
        assert frag not in pyproject, (
            f"pyproject.toml declares a forbidden dependency containing '{frag}'; "
            f"per spec §7 HC7, no brokerage SDK allowed"
        )
