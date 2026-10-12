"""CLI del revisor de código.

Uso:
    python review.py --base main --head feature/buggy
    python review.py --base main --patch cambio.patch
    python review.py --warmup
"""

import argparse
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from reviewer.diff import parse_diff
from reviewer.llm import LLMConfig, run_llm_review, warmup
from reviewer.static import run_static_analysis
from reviewer.verify import verify_findings
from reviewer.workspace import checkout, diff_between


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Revisión automática de un cambio de código.")
    parser.add_argument("--repo", default=".", help="repositorio git a revisar")
    parser.add_argument("--base", default="main", help="rama o commit base")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--head", help="rama o commit con el cambio")
    source.add_argument("--patch", type=Path, help="archivo .patch a aplicar sobre --base")
    source.add_argument(
        "--warmup", action="store_true", help="solo carga el modelo en memoria y sale"
    )
    parser.add_argument("--no-llm", action="store_true", help="solo la etapa determinística")
    return parser.parse_args(argv)


def print_result(result) -> None:
    status = "ok" if result.ok else f"ERROR: {result.error}"
    extra = f", {result.omitted} descartados" if result.omitted else ""
    print(f"\n[{result.tool}] {status} ({result.duration_s:.1f}s{extra})")
    for f in result.findings:
        location = f"{f.file}:{f.line}" if f.line else f.file
        if f.source == "llm":
            check = {True: "verificado", None: "sin verificar"}[f.verified]
            tag = f"[{f.category}, {check}]"
        else:
            tag = f"[{f.rule}]"
        print(f"  {f.severity.upper():8} {location}  {tag} {f.message}")
        if f.suggestion and f.source in ("llm", "rules"):
            print(f"           → {f.suggestion}")
    if result.tool == "verifier":
        s = result.stats
        print(
            f"  {s['calls']} llamadas, {s['confirmed']} confirmados, "
            f"{s['corroborated']} corroborados por herramientas, {len(s['rejected'])} rechazados"
        )
        for r in s["rejected"]:
            print(f"    RECHAZADO {r['file']}:{r['line']} {r['message'][:90]}")
            print(f"              motivo: {r['verification'][:150]}")
    elif result.stats:
        s = result.stats
        print(
            f"  modelo {s['model']} ({s['provider']}), carga {s.get('load_s', 0)}s, "
            f"revisión {s.get('review_s', 0)}s, tokens {s['tokens_in']} in / "
            f"{s['tokens_out']} out, secretos borrados: {s['redactions']}"
        )
        for f in s["files"]:
            print(f"    {f['path']}: {f['seconds']}s, {f['findings']} hallazgos")
        if result.ok:  # si falló todo, el error ya se mostró arriba
            for err in s["errors"]:
                print(f"    ERROR {err}")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    cfg = LLMConfig.from_env()

    if args.warmup:
        print(f"Cargando {cfg.model} ({cfg.provider})...")
        print(f"Listo en {warmup(cfg):.1f}s")
        return 0

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
        if not args.no_llm:
            static_findings = [f for r in results for f in r.findings]
            llm_result = run_llm_review(workdir, diffs, static_findings, cfg)
            verifier_result = verify_findings(workdir, diffs, llm_result, static_findings, cfg)
            results += [llm_result, verifier_result]

    for result in results:
        print_result(result)

    print(f"\nTiempo total: {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
