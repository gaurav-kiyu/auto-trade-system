"""Regression contract for the canonical MFA provisioning route.

This test protects the previously observed route/helper signature regression.
It is intentionally static: it does not require a running server or credentials.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

from core.auth.mfa import get_mfa_provisioning_uri


ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "core" / "auth" / "routes.py"


def _find_mfa_setup_function(tree: ast.AST) -> ast.FunctionDef | ast.AsyncFunctionDef:
    candidates = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name.lower()
            if "mfa" in name and ("setup" in name or "enable" in name or "provision" in name):
                candidates.append(node)

    # Prefer the function containing the provisioning helper call.
    for node in candidates:
        if any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "get_mfa_provisioning_uri"
            for child in ast.walk(node)
        ):
            return node

    raise AssertionError("Could not locate the MFA setup function containing get_mfa_provisioning_uri().")


def _find_provisioning_calls(node: ast.AST) -> list[ast.Call]:
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == "get_mfa_provisioning_uri"
    ]


def test_mfa_helper_signature_is_secret_username_only():
    signature = inspect.signature(get_mfa_provisioning_uri)
    assert list(signature.parameters) == ["secret", "username"], (
        "MFA helper signature changed unexpectedly; update the route contract "
        "and this test together."
    )


def test_mfa_setup_route_matches_helper_contract():
    source = ROUTES.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(ROUTES))
    setup = _find_mfa_setup_function(tree)
    calls = _find_provisioning_calls(setup)

    assert len(calls) == 1, (
        "MFA setup route must contain exactly one "
        "get_mfa_provisioning_uri() call."
    )

    call = calls[0]
    keyword_names = [kw.arg for kw in call.keywords]

    assert not call.args, (
        "MFA setup route must call get_mfa_provisioning_uri() with named "
        "arguments so the contract is explicit."
    )
    assert keyword_names == ["secret", "username"], (
        "MFA setup route has an incompatible get_mfa_provisioning_uri() "
        f"argument contract: {keyword_names!r}. Expected ['secret', 'username']."
    )

    assert "issuer" not in keyword_names, (
        "Unsupported issuer= argument was reintroduced into the MFA "
        "provisioning helper call."
    )
