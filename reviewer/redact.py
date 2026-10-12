"""Borrado de secretos antes de mandar código a un modelo.

Es una red de seguridad, no una garantía: si el proveedor es externo, el código igual sale de
la máquina. Por eso el default es un modelo local.
"""

import re

PLACEHOLDER = "[REDACTED]"

PATTERNS = [
    # bloques de clave privada completos
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),  # tokens de GitHub
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),  # claves estilo OpenAI / Anthropic
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"),  # Slack
    re.compile(r"(?i)\b[a-z]+://[^\s:/@]+:[^\s@/]+@"),  # credenciales en URLs (user:pass@host)
]

# variable_con_nombre_sensible = "valor literal"  →  se conserva el nombre, se borra el valor
ASSIGNMENT = re.compile(
    r"""(?ix)
    (\b[\w.\-]*(?:secret|password|passwd|pwd|token|api[_\-]?key|private[_\-]?key)[\w\-]*
     ["']?\s*[:=]\s*)
    (["'])(?!\2)([^"'\n]{6,})\2
    """
)


def redact(text: str) -> tuple[str, int]:
    """Devuelve el texto sin secretos y cuántos reemplazos se hicieron."""
    count = 0
    for pattern in PATTERNS:
        text, n = pattern.subn(PLACEHOLDER, text)
        count += n
    text, n = ASSIGNMENT.subn(lambda m: f"{m.group(1)}{m.group(2)}{PLACEHOLDER}{m.group(2)}", text)
    return text, count + n
