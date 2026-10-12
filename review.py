"""CLI del revisor de código.

Uso:
    python review.py --head feature/buggy                 # revisa la rama contra main
    python review.py --patch cambio.patch                 # revisa un .patch sobre main
    python review.py --head feature/buggy --markdown r.md --out r.json
    python review.py --warmup                             # carga el modelo y sale
    python review.py --replay runs/buggy.json             # repite una revisión guardada

Código de salida: 0 = APPROVE, 1 = REQUEST_CHANGES, 2 = error de uso o de entorno.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from reviewer.diff import parse_diff
from reviewer.gate import decide
from reviewer.llm import LLMConfig, run_llm_review, warmup
from reviewer.models import Review
from reviewer.report import render_console, render_markdown
from reviewer.static import run_static_analysis
from reviewer.verify import verify_findings
from reviewer.workspace import WorkspaceError, checkout, diff_between

EXIT_APPROVE, EXIT_CHANGES, EXIT_ERROR = 0, 1, 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Revisión automática de un cambio de código.")
    parser.add_argument("--repo", default=".", help="repositorio git a revisar")
    parser.add_argument("--base", default="main", help="rama o commit base (default: main)")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--head", help="rama o commit con el cambio")
    source.add_argument("--patch", type=Path, help="archivo .patch a aplicar sobre --base")
    source.add_argument(
        "--warmup", action="store_true", help="solo carga el modelo en memoria y sale"
    )
    source.add_argument(
        "--replay", type=Path, help="muestra una revisión guardada con --out, sin re-ejecutarla"
    )
    parser.add_argument("--no-llm", action="store_true", help="solo la etapa determinística")
    parser.add_argument("--markdown", type=Path, help="guarda el reporte en Markdown")
    parser.add_argument("--out", type=Path, help="guarda la revisión completa en JSON")
    return parser.parse_args(argv)


def run_review(args: argparse.Namespace, cfg: LLMConfig) -> Review:
    repo = Path(args.repo).resolve()
    started = time.perf_counter()

    if args.patch:
        diff_text = args.patch.read_text(encoding="utf-8")
        ref, patch, target = args.base, args.patch, f"{args.base} + {args.patch.name}"
    else:
        diff_text = diff_between(repo, args.base, args.head)
        ref, patch, target = args.head, None, f"{args.base}...{args.head}"

    diffs = parse_diff(diff_text)
    print(f"Revisando {target}: {len(diffs)} archivos cambiados...", file=sys.stderr)

    results = []
    if diffs:
        with checkout(repo, ref, patch) as workdir:
            results = run_static_analysis(workdir, diffs)
            if not args.no_llm:
                static_findings = [f for r in results for f in r.findings]
                llm_result = run_llm_review(workdir, diffs, static_findings, cfg)
                verifier = verify_findings(workdir, diffs, llm_result, static_findings, cfg)
                results += [llm_result, verifier]

    return Review(
        target=target,
        files=[d.path for d in diffs],
        results=results,
        verdict=decide(results),
        duration_s=round(time.perf_counter() - started, 1),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # la consola de Windows no siempre es UTF-8
    load_dotenv()
    args = parse_args(argv)
    cfg = LLMConfig.from_env()

    if args.warmup:
        print(f"Cargando {cfg.model} ({cfg.provider})...")
        print(f"Listo en {warmup(cfg):.1f}s")
        return EXIT_APPROVE

    try:
        if args.replay:
            review = Review.from_dict(json.loads(args.replay.read_text(encoding="utf-8")))
            print(f"(Repetición de la revisión del {review.created_at})")
        else:
            review = run_review(args, cfg)
    except (WorkspaceError, OSError, ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(render_console(review))
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(review), encoding="utf-8")
        print(f"\nReporte Markdown: {args.markdown}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(review.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Revisión completa (JSON): {args.out}")

    return EXIT_APPROVE if review.verdict.approved else EXIT_CHANGES


if __name__ == "__main__":
    sys.exit(main())
