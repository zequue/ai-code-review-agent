"""Revisor LLM: un pedido por archivo, salida JSON validada contra el diff.

Dos backends con la misma salida:
- "ollama" (default): API nativa. Permite forzar el esquema JSON, fijar el tamaño de contexto
  (si el prompt no entra, Ollama recorta el principio sin avisar) y mantener el modelo cargado.
- "openai": cualquier endpoint compatible con OpenAI (proveedores en la nube, vLLM, etc.).
"""

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from reviewer.diff import FileDiff
from reviewer.models import SEVERITIES, Finding, ToolResult
from reviewer.redact import redact

LLM_CATEGORIES = ["security", "auth", "money", "business-logic", "bug"]
CONTEXT_RADIUS = 40  # líneas de contexto alrededor de cada cambio en archivos grandes
MAX_FULL_FILE_LINES = 300
WARMUP_TIMEOUT_S = 600  # la carga en frío desde un disco lento puede tardar minutos
MAX_SCHEMA_CHARS = 3000
CREATE_TABLE = re.compile(r"CREATE TABLE[^;]*?\);", re.I | re.S)
DEFAULT_GUIDELINES = Path(__file__).with_name("guidelines.md")
NEARBY_LINES = 3  # misma categoría a esta distancia = el mismo problema repetido


class TruncatedResponse(RuntimeError):
    pass


FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        # Razonar antes de listar hallazgos: medido, sube mucho la cobertura de un modelo de 7B.
        "analysis": {"type": "string", "maxLength": 700},
        "findings": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer"},
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "category": {"type": "string", "enum": LLM_CATEGORIES},
                    # Los topes de largo cortan los loops de repetición de modelos chicos.
                    "message": {"type": "string", "maxLength": 300},
                    "suggestion": {"type": "string", "maxLength": 400},
                    "confidence": {"type": "number"},
                },
                "required": ["line", "severity", "category", "message", "suggestion", "confidence"],
            },
        }
    },
    "required": ["analysis", "findings"],
}

SYSTEM_PROMPT = """\
You are a senior software engineer reviewing a pull request for an e-commerce backend written in \
Python (Flask + SQLite).

You receive ONE file from the change. Lines marked with "+" were added or modified by the pull \
request; the other lines are context. Review ONLY the "+" lines, using the context to understand \
them.

Look for problems that a linter cannot find:
- security: injection (SQL, shell), secrets in code, unsafe deserialization.
- auth: sensitive or administrative endpoints without authentication or authorization.
- money: currency amounts handled with float, rounding or truncation errors, totals that can go \
negative.
- business-logic: rules that can be abused, e.g. coupons or discounts that can be reused, stock \
not validated, operations that are not idempotent.
- bug: incorrect behaviour, unhandled errors, race conditions.

You also receive the database schema of the project, as context to understand how the code uses \
the data (for example, a status column the code should check or update).

First write a short "analysis" (English, at most 5 sentences): for each changed function, say \
what it does and whether it breaks any of the team rules. Then list the findings.

Rules:
- Do NOT comment on style, formatting, naming, docstrings, type hints or missing tests.
- Do NOT repeat issues listed under "Already reported by static tools".
- Every finding must use a line number marked with "+" in the listing.
- Do not use double quotes inside "message" or "suggestion"; use `backticks` for code.
- If the added code is correct, return an empty "findings" list. It is a valid, common answer.
- severity: critical = exploitable security flaw or direct money loss; high = real bug likely to \
affect users; medium = risky but limited impact; low = minor.
- confidence: from 0.0 to 1.0, how sure you are that this is a real problem.
- Write "message" (what is wrong and why it matters) and "suggestion" (concrete fix) in Spanish, \
one or two sentences each.
"""


@dataclass
class LLMConfig:
    provider: str = "ollama"
    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5-coder:7b"
    api_key: str = "ollama"
    timeout_s: int = 180
    num_ctx: int = 8192
    keep_alive: str = "30m"
    max_tokens: int = 1024  # tope de salida: con JSON forzado, el modelo a veces entra en loop
    guidelines: Path | None = DEFAULT_GUIDELINES  # None = sin guía del equipo

    @classmethod
    def from_env(cls) -> "LLMConfig":
        provider = os.environ.get("LLM_PROVIDER", "ollama").lower()
        default_url = "http://localhost:11434" if provider == "ollama" else ""
        guidelines = os.environ.get("LLM_GUIDELINES", str(DEFAULT_GUIDELINES))
        return cls(
            guidelines=None if guidelines.lower() in ("", "none") else Path(guidelines),
            provider=provider,
            base_url=os.environ.get("LLM_BASE_URL", default_url).rstrip("/"),
            model=os.environ.get("LLM_MODEL", cls.model),
            api_key=os.environ.get("LLM_API_KEY", cls.api_key),
            timeout_s=int(os.environ.get("LLM_TIMEOUT_S", cls.timeout_s)),
            num_ctx=int(os.environ.get("LLM_NUM_CTX", cls.num_ctx)),
            keep_alive=os.environ.get("LLM_KEEP_ALIVE", cls.keep_alive),
            max_tokens=int(os.environ.get("LLM_MAX_TOKENS", cls.max_tokens)),
        )


# --- armado del prompt ---


def render_file(content: str, added_lines: dict[int, str]) -> str:
    """Archivo numerado, con "+" en las líneas del cambio. Recorta archivos grandes."""
    lines = content.splitlines()
    if len(lines) <= MAX_FULL_FILE_LINES:
        visible = set(range(1, len(lines) + 1))
    else:
        visible = {
            n
            for changed in added_lines
            for n in range(changed - CONTEXT_RADIUS, changed + CONTEXT_RADIUS + 1)
            if 1 <= n <= len(lines)
        }
    out, previous = [], 0
    for n in sorted(visible):
        if n != previous + 1:
            out.append("      ...")
        mark = "+" if n in added_lines else " "
        out.append(f"{n:5d} {mark}| {lines[n - 1]}")
        previous = n
    return "\n".join(out)


def build_system_prompt(cfg: LLMConfig) -> str:
    if cfg.guidelines is None:
        return SYSTEM_PROMPT
    return f"{SYSTEM_PROMPT}\n{cfg.guidelines.read_text(encoding='utf-8')}"


def extract_db_schema(workdir: Path) -> str:
    """`CREATE TABLE` del proyecto: el contexto mínimo para entender reglas sobre los datos.

    Se probó mandar todo lo agregado en los otros archivos del PR: con un modelo de 7B, el
    contexto extra hace que mezcle problemas de un archivo con otro. El esquema es chico y dirigido.
    """
    tables: list[str] = []
    for path in sorted(workdir.rglob("*.py")):
        if ".venv" in path.parts or "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        tables.extend(m.group(0).strip() for m in CREATE_TABLE.finditer(text))
    schema = "\n\n".join(dict.fromkeys(tables))  # sin duplicados, en orden
    if len(schema) > MAX_SCHEMA_CHARS:
        schema = schema[:MAX_SCHEMA_CHARS] + "\n... (truncated)"
    return schema or "(none)"


def build_user_prompt(
    path: str, listing: str, static_findings: list[Finding], schema: str = "(none)"
) -> str:
    reported = "\n".join(
        f"- line {f.line}: [{f.rule}] {f.message}" for f in static_findings
    ) or "- (none)"
    return (
        f"Database schema of the project (context only):\n{schema}\n\n"
        f"Already reported by static tools for this file:\n{reported}\n\n"
        f"File under review: {path}\n"
        f"Listing (line number, '+' if changed, code):\n{listing}\n"
    )


# --- llamadas al modelo ---


def _call_ollama(cfg: LLMConfig, system: str, user: str, schema: dict) -> tuple[str, int, int]:
    resp = requests.post(
        f"{cfg.base_url}/api/chat",
        json={
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": schema,
            "stream": False,
            "keep_alive": cfg.keep_alive,
            "options": {
                "temperature": 0,
                "seed": 42,
                "num_ctx": cfg.num_ctx,
                "num_predict": cfg.max_tokens,
                "repeat_penalty": 1.15,
            },
        },
        timeout=cfg.timeout_s,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("done_reason") == "length":
        raise TruncatedResponse(f"la respuesta superó {cfg.max_tokens} tokens")
    return data["message"]["content"], data.get("prompt_eval_count", 0), data.get("eval_count", 0)


def _call_openai(cfg: LLMConfig, system: str, user: str, schema: dict) -> tuple[str, int, int]:
    from openai import OpenAI

    client = OpenAI(base_url=cfg.base_url or None, api_key=cfg.api_key, timeout=cfg.timeout_s)
    resp = client.chat.completions.create(
        model=cfg.model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "review", "schema": schema},
        },
        temperature=0,
        seed=42,
        max_tokens=cfg.max_tokens,
    )
    if resp.choices[0].finish_reason == "length":
        raise TruncatedResponse(f"la respuesta superó {cfg.max_tokens} tokens")
    usage = resp.usage
    return (
        resp.choices[0].message.content or "",
        usage.prompt_tokens if usage else 0,
        usage.completion_tokens if usage else 0,
    )


def call_model(
    cfg: LLMConfig, system: str, user: str, schema: dict = FINDINGS_SCHEMA
) -> tuple[str, int, int]:
    if cfg.provider == "ollama":
        return _call_ollama(cfg, system, user, schema)
    if cfg.provider == "openai":
        return _call_openai(cfg, system, user, schema)
    raise ValueError(f"LLM_PROVIDER desconocido: {cfg.provider}")


def warmup(cfg: LLMConfig) -> float:
    """Carga el modelo en memoria para que la revisión no pague el arranque en frío.

    Usa las mismas opciones que la revisión: si `num_ctx` difiere, Ollama descarta el modelo
    cargado y lo vuelve a cargar. Si ya está cargado, vuelve en milisegundos.
    """
    start = time.perf_counter()
    if cfg.provider == "ollama":
        resp = requests.post(
            f"{cfg.base_url}/api/generate",
            json={
                "model": cfg.model,
                "keep_alive": cfg.keep_alive,
                "options": {"num_ctx": cfg.num_ctx},
            },
            timeout=WARMUP_TIMEOUT_S,
        )
        resp.raise_for_status()
    return time.perf_counter() - start


# --- validación de la respuesta ---


def parse_findings(raw: str, diff: FileDiff) -> tuple[list[Finding], int]:
    """Convierte la respuesta en Findings. Descarta lo que no apunte a una línea del cambio."""
    text = raw.strip()
    if text.startswith("```"):  # algunos modelos envuelven el JSON igual
        text = text.strip("`").removeprefix("json").strip()
    items = json.loads(text).get("findings", [])

    findings: list[Finding] = []
    dropped = 0

    def repeated(line: int, category: str) -> bool:
        return any(
            f.category == category and abs(f.line - line) <= NEARBY_LINES for f in findings
        )

    for item in items:
        try:
            line = int(item["line"])
            severity = str(item["severity"]).lower()
            category = str(item["category"]).lower()
            message = str(item["message"]).strip()
        except (KeyError, TypeError, ValueError):
            dropped += 1
            continue
        if (
            line not in diff.added_lines
            or severity not in SEVERITIES
            or category not in LLM_CATEGORIES
            or not message
            or repeated(line, category)
        ):
            dropped += 1
            continue
        try:
            confidence = min(max(float(item.get("confidence", 0.5)), 0.0), 1.0)
        except (TypeError, ValueError):
            confidence = 0.5
        findings.append(
            Finding(
                source="llm",
                file=diff.path,
                line=line,
                severity=severity,
                category=category,
                message=message,
                suggestion=(str(item.get("suggestion") or "").strip() or None),
                confidence=confidence,
            )
        )
    return findings, dropped


# --- etapa completa ---


def files_to_review(diffs: list[FileDiff]) -> list[FileDiff]:
    # Los tests no se mandan al modelo: menos tiempo y tokens, y casi no aportan hallazgos útiles.
    return [
        d for d in diffs if d.is_python and not d.is_deleted and not d.is_test and d.added_lines
    ]


def run_llm_review(
    workdir: Path,
    diffs: list[FileDiff],
    static_findings: list[Finding],
    cfg: LLMConfig | None = None,
) -> ToolResult:
    cfg = cfg or LLMConfig.from_env()
    start = time.perf_counter()
    findings: list[Finding] = []
    stats = {
        "provider": cfg.provider,
        "model": cfg.model,
        "files": [],
        "tokens_in": 0,
        "tokens_out": 0,
        "redactions": 0,
        "guidelines": cfg.guidelines.name if cfg.guidelines else None,
        "errors": [],
    }
    dropped_total = 0
    targets = files_to_review(diffs)
    system = build_system_prompt(cfg)
    schema, schema_redactions = redact(extract_db_schema(workdir))
    stats["redactions"] += schema_redactions

    if targets:
        # La carga del modelo se mide aparte: es un costo de arranque, no de la revisión.
        try:
            stats["load_s"] = round(warmup(cfg), 1)
        except Exception as exc:
            elapsed = time.perf_counter() - start
            return ToolResult("llm", False, elapsed, error=str(exc), stats=stats)
    review_start = time.perf_counter()

    for diff in targets:
        file_start = time.perf_counter()
        content = (workdir / diff.path).read_text(encoding="utf-8")
        content, redactions = redact(content)
        listing = render_file(content, diff.added_lines)
        already = [f for f in static_findings if f.file == diff.path]
        user = build_user_prompt(diff.path, listing, already, schema)
        try:
            raw, tokens_in, tokens_out = call_model(cfg, system, user)
            file_findings, dropped = parse_findings(raw, diff)
        except Exception as exc:  # un archivo que falla no frena al resto
            stats["errors"].append(f"{diff.path}: {exc}")
            continue
        findings.extend(file_findings)
        dropped_total += dropped
        stats["tokens_in"] += tokens_in
        stats["tokens_out"] += tokens_out
        stats["redactions"] += redactions
        stats["files"].append(
            {
                "path": diff.path,
                "seconds": round(time.perf_counter() - file_start, 1),
                "findings": len(file_findings),
                "dropped": dropped,
            }
        )

    stats["review_s"] = round(time.perf_counter() - review_start, 1)
    ok = not targets or len(stats["errors"]) < len(targets)
    error = "; ".join(stats["errors"]) or None
    return ToolResult(
        "llm", ok, time.perf_counter() - start, findings, error, dropped_total, stats
    )
