"""Regression guard: every mutating enterprise admin API must declare a granular permission.

This is intentionally source-level and complements authenticated browser/API tests.
"""
from pathlib import Path
import ast

ADMIN = Path("core/enterprise_dashboard/routes/admin.py")


def _mutating_routes(tree):
    out=[]
    for n in tree.body:
        if not isinstance(n, ast.FunctionDef) and not isinstance(n, ast.AsyncFunctionDef):
            continue
        # route decorators are inside register_admin_routes function, so walk nested defs
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        methods=[]
        for d in n.decorator_list:
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in {"post","put","delete","patch"}:
                methods.append(d.func.attr.upper())
        if methods:
            out.append((n.name, methods, n))
    return out


def _has_permission_dependency(node):
    for d in list(node.args.defaults) + list(node.args.kw_defaults):
        if d is None:
            continue
        for child in ast.walk(d):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == "require_permission":
                return True
    return False


def test_all_mutating_admin_routes_declare_granular_permission():
    tree=ast.parse(ADMIN.read_text(encoding="utf-8"))
    missing=[]
    for name, methods, node in _mutating_routes(tree):
        if not _has_permission_dependency(node):
            missing.append(f"{methods} {name}")
    assert not missing, "Mutating routes without granular permission: " + ", ".join(missing)
