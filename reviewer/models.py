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
    confidence: float | None = None  # solo LLM, 0..1

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
    omitted: int = 0  # hallazgos preexistentes, fuera de las líneas del diff

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ToolResult":
        findings = [Finding.from_dict(f) for f in data.get("findings", [])]
        return cls(**{**data, "findings": findings})
