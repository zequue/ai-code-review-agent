"""Render de una revisión: Markdown (para humanos y PRs) y resumen de consola."""

from reviewer.models import Finding, Review, ToolResult, severity_rank
from reviewer.verify import CORROBORATION_DISTANCE

CATEGORY_LABEL = {
    "security": "seguridad",
    "auth": "autenticación",
    "money": "dinero",
    "business-logic": "regla de negocio",
    "bug": "bug",
    "style": "estilo",
    "test": "tests",
}
SOURCE_LABEL = {
    "ruff": "ruff",
    "bandit": "bandit",
    "rules": "regla propia",
    "pytest": "pytest",
    "llm": "LLM",
}


# --- fusión de hallazgos repetidos (herramienta + LLM sobre lo mismo) ---


def _corroborates(llm: Finding, static: Finding) -> bool:
    return (
        llm.source == "llm"
        and static.source != "llm"
        and llm.file == static.file
        and static.line is not None
        and abs(llm.line - static.line) <= CORROBORATION_DISTANCE
        and (llm.verification or "").startswith("corroborado")
    )


def merge(findings: list[Finding]) -> list[tuple[Finding, Finding | None]]:
    """Pares (hallazgo, hallazgo del LLM que lo corrobora). El LLM fusionado no se repite."""
    llm_findings = [f for f in findings if f.source == "llm"]
    used: set[int] = set()
    pairs: list[tuple[Finding, Finding | None]] = []
    for f in findings:
        if f.source == "llm":
            continue
        match = next(
            (m for m in llm_findings if id(m) not in used and _corroborates(m, f)), None
        )
        if match is not None:
            used.add(id(match))
        pairs.append((f, match))
    pairs.extend((f, None) for f in llm_findings if id(f) not in used)
    pairs.sort(key=lambda pair: -severity_rank(_severity(*pair)))  # estable: respeta el resto
    return pairs


def _severity(f: Finding, extra: Finding | None) -> str:
    """Severidad del par fusionado: la mayor de las dos opiniones."""
    if extra is not None and severity_rank(extra.severity) > severity_rank(f.severity):
        return extra.severity
    return f.severity


def _sources(f: Finding, extra: Finding | None) -> str:
    label = SOURCE_LABEL.get(f.source, f.source)
    if f.rule and f.source != "pytest":
        label += f" `{f.rule}`"
    if f.source == "llm":
        label += " (verificado)" if f.verified else " (sin verificar)"
    if extra is not None:
        label += " + LLM"
    return label


def _location(f: Finding) -> str:
    return f"{f.file}:{f.line}" if f.line else f.file


# --- Markdown ---


def _finding_md(f: Finding, extra: Finding | None) -> str:
    category = CATEGORY_LABEL.get(f.category, f.category)
    lines = [
        f"**`{_location(f)}`** · {_severity(f, extra).upper()} · {category} · "
        f"{_sources(f, extra)}",
        "",
        f.message,
    ]
    suggestion = f.suggestion or (extra.suggestion if extra else None)
    if suggestion:
        lines += ["", f"> **Sugerencia:** {suggestion}"]
    return "\n".join(lines)


def _tool(review: Review, name: str) -> ToolResult | None:
    return next((r for r in review.results if r.tool == name), None)


def _metrics_md(review: Review) -> list[str]:
    rows = ["| Etapa | Tiempo | Estado | Hallazgos |", "|---|---|---|---|"]
    for r in review.results:
        state = "ok" if r.ok else f"error: {r.error}"
        rows.append(f"| {r.tool} | {r.duration_s:.1f} s | {state} | {len(r.findings)} |")
    out = ["### Métricas", "", *rows, ""]

    llm = _tool(review, "llm")
    if llm and llm.stats:
        s = llm.stats
        local = s["provider"] == "ollama"
        cost = "0 (modelo local)" if local else "según tarifa del proveedor"
        where = "local, el código no sale de la máquina" if local else s["provider"]
        out += [
            f"- Modelo: `{s['model']}` ({where})",
            f"- Carga del modelo: {s.get('load_s', 0)} s · revisión: {s.get('review_s', 0)} s",
            f"- Tokens: {s['tokens_in']} de entrada / {s['tokens_out']} de salida · costo: {cost}",
            f"- Secretos borrados antes de enviar al modelo: {s['redactions']}",
        ]
    verifier = _tool(review, "verifier")
    if verifier and verifier.stats:
        s = verifier.stats
        out.append(
            f"- Verificador: {s['confirmed']} confirmados, {s['corroborated']} corroborados por "
            f"herramientas, {len(s['rejected'])} descartados"
        )
    return out


def _duration(review: Review) -> str:
    llm = _tool(review, "llm")
    load = (llm.stats or {}).get("load_s", 0) if llm else 0
    if load >= 10:  # arranque en frío: se aclara para no confundirlo con el tiempo de revisión
        return f"{review.duration_s:.0f} s (incluye {load:.0f} s de carga del modelo)"
    return f"{review.duration_s:.0f} s"


def render_markdown(review: Review) -> str:
    v = review.verdict
    title = "✅ Aprobado" if v.approved else "❌ Cambios requeridos"
    out = [
        f"## {title}",
        "",
        f"Revisión de `{review.target}` · {len(review.files)} archivos · {_duration(review)}",
        "",
    ]
    out += [f"> ⚠️ {w}" for w in v.warnings]
    if v.warnings:
        out.append("")

    if v.reasons:
        out += ["### Por qué", "", *[f"- {r}" for r in v.reasons], ""]

    blocking = merge(v.blocking)
    if blocking:
        out += [f"### Bloqueantes ({len(blocking)})", ""]
        for f, extra in blocking:
            out += [_finding_md(f, extra), ""]

    comments = merge(v.comments)
    if comments:
        out += [f"### Comentarios, no bloquean ({len(comments)})", ""]
        for f, extra in comments:
            out += [_finding_md(f, extra), ""]

    if not blocking and not comments:
        out += ["No se encontraron problemas en las líneas cambiadas.", ""]

    verifier = _tool(review, "verifier")
    rejected = verifier.stats.get("rejected", []) if verifier and verifier.stats else []
    if rejected:
        out += [
            f"<details><summary>Descartados por el verificador ({len(rejected)})</summary>",
            "",
        ]
        for r in rejected:
            out += [
                f"- `{r['file']}:{r['line']}` {r['message']}",
                f"  - Motivo: {r['verification']}",
            ]
        out += ["", "</details>", ""]

    out += _metrics_md(review)
    return "\n".join(out) + "\n"


# --- consola ---


def render_console(review: Review) -> str:
    v = review.verdict
    out = [
        "",
        f"VEREDICTO: {v.decision}   ({review.target}, {_duration(review)})",
    ]
    out += [f"  ! {w}" for w in v.warnings]
    out += [f"  - {r}" for r in v.reasons]
    for title, findings in (("BLOQUEANTES", v.blocking), ("COMENTARIOS", v.comments)):
        pairs = merge(findings)
        if not pairs:
            continue
        out += ["", f"{title} ({len(pairs)})"]
        for f, extra in pairs:
            severity = _severity(f, extra).upper()
            out.append(f"  {severity:8} {_location(f):22} [{_sources(f, extra)}]")
            out.append(f"           {f.message}")
            suggestion = f.suggestion or (extra.suggestion if extra else None)
            if suggestion:
                out.append(f"           -> {suggestion}")
    stages = ", ".join(f"{r.tool} {r.duration_s:.1f}s" for r in review.results)
    out += ["", f"Etapas: {stages}"]
    return "\n".join(out)
