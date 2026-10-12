"""CLI del revisor de código.

Uso:
    python review.py --base main --head feature/buggy
    python review.py --base main --patch cambio.patch
"""

import argparse
import sys
import time
from pathlib import Path

from reviewer.diff import parse_diff
from reviewer.static import run_static_analysis
from reviewer.workspace import checkout, diff_between


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Revisión automática de un cambio de código.")
    parser.add_argument("--repo", default=".", help="repositorio git a revisar")
    parser.add_argument("--base", default="main", help="rama o commit base")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--head", help="rama o commit con el cambio")
    source.add_argument("--patch", type=Path, help="archivo .patch a aplicar sobre --base")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = Path(args.repo).resolve()
    started = time.perf_counter()

    if args.patch:
        diff_text = args.patch.read_text(encoding="utf-8")
        ref, patch = args.base, args.patch
    else:
        diff_text = diff_between(repo, args.base, args.head)
        ref, patch = args.head, None

    diffs = parse_diff(diff_text)
    if not diffs:
        print("El diff está vacío: no hay nada que revisar.")
        return 0

    print(f"Archivos cambiados: {len(diffs)}")
    with checkout(repo, ref, patch) as workdir:
        results = run_static_analysis(workdir, diffs)

    for result in results:
        status = "ok" if result.ok else f"ERROR: {result.error}"
        extra = f", {result.omitted} preexistentes omitidos" if result.omitted else ""
        print(f"\n[{result.tool}] {status} ({result.duration_s:.1f}s{extra})")
        for f in result.findings:
            location = f"{f.file}:{f.line}" if f.line else f.file
            print(f"  {f.severity.upper():8} {location}  [{f.rule}] {f.message}")

    print(f"\nTiempo total: {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
