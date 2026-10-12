"""Agente verificador: segunda opinión escéptica sobre cada hallazgo del revisor LLM.

Medido sobre los casos de prueba, el revisor de 7B tiene buena cobertura pero muchos falsos
positivos, y su `confidence` no sirve para separarlos (casi siempre declara 1.0). El verificador
mira un solo hallazgo por vez contra el código y decide si es real.
"""

import json
import time
from pathlib import Path

from reviewer.diff import FileDiff
from reviewer.llm import LLMConfig, call_model, render_file
from reviewer.models import Finding, ToolResult, severity_rank
from reviewer.redact import redact

CORROBORATION_DISTANCE = 1  # líneas de diferencia para considerar que es el mismo hallazgo
MIN_SEVERITY_TO_VERIFY = "medium"  # los `low` quedan como comentario no verificado

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string", "maxLength": 500},
        "verdict": {"type": "string", "enum": ["confirmed", "rejected"]},
    },
    "required": ["reasoning", "verdict"],
}

SYSTEM_PROMPT = """\
You are a skeptical senior engineer double-checking a code review comment written by a junior \
reviewer, who often reports problems that do not exist.

You receive the file and ONE review comment about a specific line. Decide whether the comment \
describes a real, concrete problem in that code.
- Read the code carefully. Check whether the code already handles what the comment says is missing.
- Reject comments that are speculative, generic advice, about style, or that describe something \
the code does not actually do.
- Confirm only if you can point to the exact code that causes the problem.
Answer with a short reasoning (English) and the verdict. When in doubt, reject.
"""


def corroborating_tool(finding: Finding, static_findings: list[Finding]) -> str | None:
    """Herramienta determinística que ya reportó lo mismo (mismo archivo, línea cercana)."""
    for s in static_findings:
        if (
            s.source in ("bandit", "rules")
            and s.file == finding.file
            and s.line is not None
            and abs(s.line - finding.line) <= CORROBORATION_DISTANCE
        ):
            return s.rule or s.source
    return None


def build_user_prompt(path: str, listing: str, finding: Finding) -> str:
    return (
        f"File: {path}\n{listing}\n\n"
        f"Review comment on line {finding.line} ({finding.category}):\n{finding.message}\n"
    )


def verify_findings(
    workdir: Path,
    diffs: list[FileDiff],
    llm_result: ToolResult,
    static_findings: list[Finding],
    cfg: LLMConfig | None = None,
) -> ToolResult:
    """Marca los hallazgos del LLM como verificados y saca los rechazados de `llm_result`."""
    cfg = cfg or LLMConfig.from_env()
    start = time.perf_counter()
    by_path = {d.path: d for d in diffs}
    listings: dict[str, str] = {}
    kept: list[Finding] = []
    stats = {"calls": 0, "corroborated": 0, "confirmed": 0, "rejected": [], "errors": []}

    for finding in llm_result.findings:
        tool = corroborating_tool(finding, static_findings)
        if tool:
            finding.verified, finding.verification = True, f"corroborado por {tool}"
            stats["corroborated"] += 1
            kept.append(finding)
            continue
        if severity_rank(finding.severity) < severity_rank(MIN_SEVERITY_TO_VERIFY):
            kept.append(finding)  # queda como comentario, sin verificar
            continue

        if finding.file not in listings:
            content, _ = redact((workdir / finding.file).read_text(encoding="utf-8"))
            listings[finding.file] = render_file(content, by_path[finding.file].added_lines)
        user = build_user_prompt(finding.file, listings[finding.file], finding)
        try:
            raw, _, _ = call_model(cfg, SYSTEM_PROMPT, user, VERDICT_SCHEMA)
            answer = json.loads(raw)
            confirmed = answer["verdict"] == "confirmed"
            reasoning = str(answer.get("reasoning", "")).strip()
        except Exception as exc:  # si no se pudo verificar, queda como no verificado
            stats["errors"].append(f"{finding.file}:{finding.line}: {exc}")
            kept.append(finding)
            continue
        stats["calls"] += 1
        finding.verified, finding.verification = confirmed, reasoning
        if confirmed:
            stats["confirmed"] += 1
            kept.append(finding)
        else:
            stats["rejected"].append(finding.to_dict())

    llm_result.findings = kept
    ok = not stats["errors"] or stats["calls"] > 0
    error = "; ".join(stats["errors"]) or None
    return ToolResult("verifier", ok, time.perf_counter() - start, [], error, 0, stats)
