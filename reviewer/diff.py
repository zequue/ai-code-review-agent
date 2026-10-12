"""Parseo de unified diffs (salida de `git diff`)."""

import re
from dataclasses import dataclass, field

HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass
class FileDiff:
    path: str  # ruta en la versión nueva
    is_new: bool = False
    is_deleted: bool = False
    added_lines: dict[int, str] = field(default_factory=dict)  # n° de línea nueva -> texto
    text: str = ""  # el diff crudo de este archivo

    @property
    def is_python(self) -> bool:
        return self.path.endswith(".py")

    @property
    def is_test(self) -> bool:
        name = self.path.rsplit("/", 1)[-1]
        return "/tests/" in f"/{self.path}" or name.startswith("test_")


def parse_diff(diff_text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    current: FileDiff | None = None
    new_line = 0
    lines: list[str] = []

    def close():
        if current is not None:
            current.text = "\n".join(lines)
            files.append(current)

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            close()
            # "diff --git a/x b/x": el path definitivo sale de la línea "+++"
            current = FileDiff(path=raw.split(" b/", 1)[-1])
            lines = [raw]
            continue
        if current is None:
            continue
        lines.append(raw)

        if raw.startswith("new file mode"):
            current.is_new = True
        elif raw.startswith("deleted file mode"):
            current.is_deleted = True
        elif raw.startswith("+++ "):
            target = raw[4:]
            if target != "/dev/null":
                current.path = target[2:] if target.startswith("b/") else target
        elif raw.startswith("--- "):
            pass
        elif raw.startswith("@@"):
            match = HUNK_HEADER.match(raw)
            if match:
                new_line = int(match.group(1))
        elif raw.startswith("+"):
            current.added_lines[new_line] = raw[1:]
            new_line += 1
        elif raw.startswith("-") or raw.startswith("\\"):
            pass  # línea borrada o "\ No newline at end of file": no avanza la línea nueva
        else:
            new_line += 1  # línea de contexto

    close()
    return files
