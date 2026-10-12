"""Evaluación: hallazgos esperados contra detectados, repetida N veces para medir estabilidad.

Uso:
    python eval/run_eval.py                  # 1 corrida por rama
    python eval/run_eval.py --runs 3         # 3 corridas por rama
    python eval/run_eval.py --no-llm         # solo la parte determinística (línea base)

Un bug cuenta como detectado si algún hallazgo cae en su archivo, dentro de su rango de líneas y
con una de sus categorías. "Bloquea" = lo detectó un hallazgo bloqueante del gate.
Un falso positivo bloqueante es un hallazgo bloqueante que no corresponde a ningún bug esperado.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from review import parse_args as review_args  # noqa: E402
from review import run_review  # noqa: E402
from reviewer.llm import LLMConfig  # noqa: E402
from reviewer.models import Finding  # noqa: E402
from reviewer.report import merge  # noqa: E402

EXPECTED = Path(__file__).with_name("expected.json")
RESULTS = Path(__file__).with_name("results.md")


def matches(finding: Finding, bug: dict) -> bool:
    low, high = bug["lines"]
    return (
        finding.file == bug["file"]
        and finding.line is not None
        and low <= finding.line <= high
        and finding.category in bug["categories"]
    )


def score(review, spec: dict) -> dict:
    blocking = [f for f, _ in merge(review.verdict.blocking)]
    comments = [f for f, _ in merge(review.verdict.comments)]
    bugs = {}
    for bug in spec["bugs"]:
        if any(matches(f, bug) for f in blocking):
            bugs[bug["id"]] = "bloquea"
        elif any(matches(f, bug) for f in comments):
            bugs[bug["id"]] = "comentario"
        else:
            bugs[bug["id"]] = "no detectado"
    unmatched = [f for f in blocking if not any(matches(f, b) for b in spec["bugs"])]
    llm = next((r for r in review.results if r.tool == "llm"), None)
    return {
        "decision_ok": review.verdict.decision == spec["decision"],
        "decision": review.verdict.decision,
        "bugs": bugs,
        "false_positives": [f"{f.file}:{f.line} {f.message[:70]}" for f in unmatched],
        "comments": len(comments),
        "seconds": review.duration_s,
        "review_s": (llm.stats or {}).get("review_s") if llm else None,
    }


def render(all_scores: dict[str, list[dict]], spec: dict, label: str) -> str:
    out = [f"# Evaluación ({label})", ""]
    for branch, scores in all_scores.items():
        n = len(scores)
        ok = sum(s["decision_ok"] for s in scores)
        out += [
            f"## `{branch}` — esperado `{spec[branch]['decision']}`",
            "",
            f"- Veredicto correcto: **{ok}/{n}** corridas",
        ]
        totals = [s["seconds"] for s in scores]
        out.append(f"- Tiempo total por corrida: {min(totals):.0f}–{max(totals):.0f} s")
        llm_times = [s["review_s"] for s in scores if s["review_s"] is not None]
        if llm_times:
            out.append(
                f"- Del cual, revisión LLM (sin carga del modelo): "
                f"{min(llm_times):.0f}–{max(llm_times):.0f} s"
            )
        fps = sum(len(s["false_positives"]) for s in scores)
        out.append(f"- Falsos positivos bloqueantes: {fps} en {n} corridas")
        for s in scores:
            out += [f"  - {fp}" for fp in s["false_positives"]]
        if spec[branch]["bugs"]:
            out += ["", "| Bug | " + " | ".join(f"corrida {i + 1}" for i in range(n)) + " |"]
            out.append("|---|" + "---|" * n)
            for bug in spec[branch]["bugs"]:
                cells = [s["bugs"][bug["id"]] for s in scores]
                out.append(f"| {bug['id']} | " + " | ".join(cells) + " |")
            total = Counter(v for s in scores for v in s["bugs"].values())
            n_bugs = len(spec[branch]["bugs"]) * n
            out += [
                "",
                f"Bloquean {total['bloquea']}/{n_bugs}, solo comentario "
                f"{total['comentario']}/{n_bugs}, no detectados {total['no detectado']}/{n_bugs}.",
            ]
        out.append("")
    return "\n".join(out)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()

    spec = json.loads(EXPECTED.read_text(encoding="utf-8"))
    cfg = LLMConfig.from_env()
    all_scores: dict[str, list[dict]] = {}
    for branch in spec:
        all_scores[branch] = []
        for i in range(args.runs):
            print(f"{branch}: corrida {i + 1}/{args.runs}...", file=sys.stderr)
            argv = ["--repo", str(ROOT), "--head", branch] + (["--no-llm"] if args.no_llm else [])
            review = run_review(review_args(argv), cfg)
            all_scores[branch].append(score(review, spec[branch]))

    label = "solo determinístico" if args.no_llm else f"{cfg.model}, {args.runs} corridas"
    report = render(all_scores, spec, label)
    print(report)
    target = RESULTS.with_name("results-no-llm.md") if args.no_llm else RESULTS
    target.write_text(report, encoding="utf-8")
    print(f"Guardado en {target.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
