from dataclasses import asdict, dataclass, field

SEVERITIES = ("low", "medium", "high", "critical")
CATEGORIES = ("security", "bug", "money", "auth", "business-logic", "style", "test")


def severity_rank(severity: str) -> int:
    return SEVERITIES.index(severity)


@dataclass
class Finding:
    source: str  # "ruff" | "bandit" | "pytest" | "llm"
    file: str  # ruta relativa al repo, con "/"
    line: int | None  # línea en el archivo nuevo; None = nivel archivo
    severity: str
    category: str
    message: str
    rule: str | None = None  # p. ej. "B608", "F401", nombre del test
    suggestion: str | None = None
    confidence: float | None = None  # solo LLM, 0..1 (informativo: un 7B casi siempre dice 1.0)
    verified: bool | None = None  # solo LLM: None = no se verificó
    verification: str | None = None  # razonamiento del verificador o "corroborado por bandit"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Finding":
        return cls(**data)


@dataclass
class ToolResult:
    tool: str
    ok: bool  # False si la herramienta no pudo correr
    duration_s: float
    findings: list[Finding] = field(default_factory=list)
    error: str | None = None
    omitted: int = 0  # hallazgos descartados: preexistentes o (LLM) fuera de las líneas del diff
    stats: dict = field(default_factory=dict)  # métricas extra: tokens, archivos, etc.

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ToolResult":
        findings = [Finding.from_dict(f) for f in data.get("findings", [])]
        return cls(**{**data, "findings": findings})


@dataclass
class Verdict:
    decision: str  # "APPROVE" | "REQUEST_CHANGES"
    reasons: list[str]  # qué regla del gate disparó la decisión (vacío si aprueba)
    blocking: list[Finding] = field(default_factory=list)
    comments: list[Finding] = field(default_factory=list)  # no bloqueantes
    warnings: list[str] = field(default_factory=list)  # p. ej. revisión parcial sin LLM

    @property
    def approved(self) -> bool:
        return self.decision == "APPROVE"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Verdict":
        return cls(
            **{
                **data,
                "blocking": [Finding.from_dict(f) for f in data.get("blocking", [])],
                "comments": [Finding.from_dict(f) for f in data.get("comments", [])],
            }
        )


@dataclass
class Review:
    """Resultado completo de una corrida. Se guarda como JSON para `--replay`."""

    target: str  # p. ej. "main...feature/buggy" o "main + cambio.patch"
    files: list[str]
    results: list[ToolResult]
    verdict: Verdict
    duration_s: float
    created_at: str
    # líneas agregadas por archivo: GitHub solo acepta comentarios en líneas del diff
    changed_lines: dict[str, list[int]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Review":
        return cls(
            **{
                **data,
                "results": [ToolResult.from_dict(r) for r in data["results"]],
                "verdict": Verdict.from_dict(data["verdict"]),
            }
        )
