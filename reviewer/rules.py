"""Reglas propias, determinísticas, sobre el AST de Python.

Existen porque, medido sobre los casos de prueba, el modelo local no detectó en ninguna variante
de prompt un endpoint de admin sin autenticación. Es un patrón estructural: el código lo ve con
certeza, gratis y en milisegundos.
"""

import ast
import re
import time
from pathlib import Path

from reviewer.diff import FileDiff
from reviewer.models import Finding, ToolResult

ROUTE_DECORATORS = {"route", "get", "post", "put", "patch", "delete"}
ADMIN_PATH = re.compile(r"(^|/)admin(/|$)")
AUTH_NAME = re.compile(r"auth|login|admin|token|permission|role", re.I)


def _name(node: ast.expr) -> str:
    """Nombre de un decorador o de una función llamada: `x`, `obj.x` o `x(...)` → "x"."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _route_path(decorator: ast.expr) -> str | None:
    if (
        isinstance(decorator, ast.Call)
        and _name(decorator) in ROUTE_DECORATORS
        and decorator.args
        and isinstance(decorator.args[0], ast.Constant)
        and isinstance(decorator.args[0].value, str)
    ):
        return decorator.args[0].value
    return None


def _has_auth_check(func: ast.FunctionDef) -> bool:
    for decorator in func.decorator_list:
        if _route_path(decorator) is None and AUTH_NAME.search(_name(decorator)):
            return True
    calls = (n for n in ast.walk(func) if isinstance(n, ast.Call))
    return any(AUTH_NAME.search(_name(call)) for call in calls)


def check_admin_routes(source: str, path: str) -> list[Finding]:
    findings = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            route = _route_path(decorator)
            if route and ADMIN_PATH.search(route) and not _has_auth_check(node):
                findings.append(
                    Finding(
                        source="rules",
                        file=path,
                        line=decorator.lineno,
                        severity="critical",
                        category="auth",
                        message=f"El endpoint de administración `{route}` no verifica "
                        "autenticación: cualquiera puede llamarlo.",
                        rule="ADMIN-NO-AUTH",
                        suggestion="Agregar un decorador o chequeo de credenciales "
                        "(p. ej. `@require_admin`) antes de ejecutar la operación.",
                    )
                )
    return findings


def run_rules(workdir: Path, diffs: list[FileDiff]) -> ToolResult:
    start = time.perf_counter()
    findings: list[Finding] = []
    for diff in diffs:
        if not diff.is_python or diff.is_deleted or diff.is_test:
            continue
        try:
            source = (workdir / diff.path).read_text(encoding="utf-8")
            findings.extend(check_admin_routes(source, diff.path))
        except SyntaxError as exc:
            return ToolResult("rules", False, time.perf_counter() - start, error=str(exc))
    return ToolResult("rules", True, time.perf_counter() - start, findings)
