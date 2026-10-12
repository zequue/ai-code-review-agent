"""Política de veredicto. El LLM aconseja; esta función decide.

Reglas explícitas, en código y testeadas: el mismo input da siempre el mismo veredicto, y el
reporte dice qué regla lo disparó.
"""

from reviewer.models import Finding, ToolResult, Verdict, severity_rank

DETERMINISTIC_TOOLS = ("ruff", "bandit", "rules", "pytest")


def _at_least(finding: Finding, severity: str) -> bool:
    return severity_rank(finding.severity) >= severity_rank(severity)


def is_blocking(f: Finding) -> str | None:
    """Devuelve la regla del gate que hace bloqueante a este hallazgo, o None."""
    if f.source == "pytest":
        return "tests: hay tests que fallan"
    if f.source == "bandit" and _at_least(f, "medium"):
        return "seguridad: bandit reportó un problema de severidad medium o mayor"
    if f.source == "rules" and _at_least(f, "high"):
        return "reglas del equipo: violación de severidad high o mayor"
    if f.source == "llm" and f.verified and _at_least(f, "high"):
        return "revisión LLM: hallazgo high o mayor confirmado"
    return None


def _display_order(f: Finding) -> tuple:
    return (-severity_rank(f.severity), f.file, f.line or 0)


def decide(results: list[ToolResult]) -> Verdict:
    reasons: list[str] = []
    warnings: list[str] = []
    blocking: list[Finding] = []
    comments: list[Finding] = []

    for result in results:
        if result.ok:
            continue
        if result.tool in DETERMINISTIC_TOOLS:
            # fail-closed: si no se pudo verificar, no se puede aprobar
            reasons.append(f"herramienta caída: {result.tool} no pudo correr")
        elif result.tool == "llm":
            # fail-open: el LLM es un asesor; si no está, decide la parte determinística
            warnings.append("Revisión parcial: el revisor LLM no estuvo disponible.")
        elif result.tool == "verifier":
            warnings.append("El verificador falló: los hallazgos del LLM no bloquean.")

    for result in results:
        for finding in result.findings:
            rule = is_blocking(finding)
            if rule:
                blocking.append(finding)
                if rule not in reasons:
                    reasons.append(rule)
            else:
                comments.append(finding)

    blocking.sort(key=_display_order)
    comments.sort(key=_display_order)
    decision = "REQUEST_CHANGES" if reasons else "APPROVE"
    return Verdict(decision, reasons, blocking, comments, warnings)
