"""Etapa determinística: ruff, bandit y pytest, normalizados a Findings."""

import json
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from reviewer.diff import FileDiff
from reviewer.models import Finding, ToolResult
from reviewer.rules import run_rules

TOOL_TIMEOUT_S = 120

BANDIT_SEVERITY = {"LOW": "low", "MEDIUM": "medium", "HIGH": "high"}


def _rel(path: str, workdir: Path) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(workdir.resolve())
        except ValueError:
            pass
    return p.as_posix().removeprefix("./")


def _run(args: list[str], workdir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=workdir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TOOL_TIMEOUT_S,
    )


# --- parsers (funciones puras, testeables sin correr las herramientas) ---


def parse_ruff(output: str, workdir: Path) -> list[Finding]:
    findings = []
    for item in json.loads(output or "[]"):
        code = item.get("code") or "ruff"
        is_pyflakes = code.startswith("F")  # nombres indefinidos, imports sin usar, etc.
        fix = item.get("fix") or {}
        findings.append(
            Finding(
                source="ruff",
                file=_rel(item["filename"], workdir),
                line=item["location"]["row"],
                severity="medium" if is_pyflakes else "low",
                category="bug" if is_pyflakes else "style",
                message=item["message"],
                rule=code,
                suggestion=fix.get("message"),
            )
        )
    return findings


def parse_bandit(output: str, workdir: Path) -> list[Finding]:
    findings = []
    for item in json.loads(output or "{}").get("results", []):
        cwe = (item.get("issue_cwe") or {}).get("id")
        message = item["issue_text"] + (f" (CWE-{cwe})" if cwe else "")
        findings.append(
            Finding(
                source="bandit",
                file=_rel(item["filename"], workdir),
                line=item["line_number"],
                severity=BANDIT_SEVERITY.get(item["issue_severity"], "low"),
                category="security",
                message=message,
                rule=item["test_id"],
            )
        )
    return findings


def parse_junit(xml_text: str) -> list[Finding]:
    findings = []
    root = ET.fromstring(xml_text)
    for case in root.iter("testcase"):
        problem = case.find("failure")
        if problem is None:
            problem = case.find("error")
        if problem is None:
            continue
        module = case.get("classname", "")
        file = case.get("file") or module.replace(".", "/") + ".py"
        detail = (problem.get("message") or "").strip().splitlines()
        findings.append(
            Finding(
                source="pytest",
                file=Path(file).as_posix(),
                line=int(case.get("line")) + 1 if case.get("line") else None,
                severity="high",
                category="test",
                message=f"Falla el test {case.get('name')}: {detail[0] if detail else 'error'}",
                rule=f"{module}::{case.get('name')}",
            )
        )
    return findings


# --- ejecución ---


def run_ruff(workdir: Path, files: list[str]) -> ToolResult:
    start = time.perf_counter()
    if not files:
        return ToolResult("ruff", True, 0.0)
    try:
        proc = _run(["ruff", "check", "--output-format", "json", "--no-cache", *files], workdir)
        findings = parse_ruff(proc.stdout, workdir)
    except Exception as exc:  # la herramienta no corrió: se reporta, no se oculta
        return ToolResult("ruff", False, time.perf_counter() - start, error=str(exc))
    return ToolResult("ruff", True, time.perf_counter() - start, findings)


def run_bandit(workdir: Path, files: list[str]) -> ToolResult:
    start = time.perf_counter()
    if not files:
        return ToolResult("bandit", True, 0.0)
    try:
        proc = _run(["bandit", "-q", "-f", "json", *files], workdir)
        findings = parse_bandit(proc.stdout, workdir)
    except Exception as exc:
        return ToolResult("bandit", False, time.perf_counter() - start, error=str(exc))
    return ToolResult("bandit", True, time.perf_counter() - start, findings)


def run_pytest(workdir: Path) -> ToolResult:
    start = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "junit.xml"
        try:
            proc = _run(
                [
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "-o",
                    "junit_family=xunit1",  # incluye archivo y línea de cada test
                    f"--junitxml={report}",
                ],
                workdir,
            )
        except Exception as exc:
            return ToolResult("pytest", False, time.perf_counter() - start, error=str(exc))
        duration = time.perf_counter() - start
        if proc.returncode == 5:  # no se encontraron tests
            return ToolResult("pytest", True, duration)
        if not report.exists():
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-5:]
            return ToolResult("pytest", False, duration, error="\n".join(tail))
        return ToolResult("pytest", True, duration, parse_junit(report.read_text("utf-8")))


def keep_changed_lines(result: ToolResult, diffs: list[FileDiff]) -> ToolResult:
    """Deja solo los hallazgos en líneas agregadas por el cambio."""
    added = {d.path: d.added_lines for d in diffs}
    kept = [f for f in result.findings if f.line in added.get(f.file, {})]
    result.omitted = len(result.findings) - len(kept)
    result.findings = kept
    return result


def run_static_analysis(workdir: Path, diffs: list[FileDiff]) -> list[ToolResult]:
    changed_py = [d.path for d in diffs if d.is_python and not d.is_deleted]
    # bandit no corre sobre tests: los `assert` de pytest son ruido (B101)
    source_py = [d.path for d in diffs if d.is_python and not d.is_deleted and not d.is_test]

    return [
        keep_changed_lines(run_ruff(workdir, changed_py), diffs),
        keep_changed_lines(run_bandit(workdir, source_py), diffs),
        keep_changed_lines(run_rules(workdir, diffs), diffs),
        run_pytest(workdir),  # los tests son globales: si algo se rompe, se rompe el cambio
    ]
