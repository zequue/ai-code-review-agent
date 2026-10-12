"""Obtención del diff y de una copia aislada del código a revisar.

Las herramientas corren sobre un `git worktree` temporal, así el revisor nunca toca el
working tree de quien lo ejecuta.
"""

import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path


class WorkspaceError(RuntimeError):
    pass


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise WorkspaceError(f"git {' '.join(args)} falló: {result.stderr.strip()}")
    return result.stdout


def diff_between(repo: Path, base: str, head: str) -> str:
    # "base...head" compara contra el ancestro común: solo lo que introduce la rama.
    return git(repo, "diff", "--no-color", "--unified=3", f"{base}...{head}")


@contextmanager
def checkout(repo: Path, ref: str, patch: Path | None = None):
    """Worktree temporal en `ref`, opcionalmente con un .patch aplicado."""
    tmp = Path(tempfile.mkdtemp(prefix="review-"))
    workdir = tmp / "src"
    git(repo, "worktree", "add", "--detach", str(workdir), ref)
    try:
        if patch is not None:
            git(workdir, "apply", str(patch.resolve()))
        yield workdir
    finally:
        try:
            git(repo, "worktree", "remove", "--force", str(workdir))
        except WorkspaceError:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
