from reviewer.gate import decide
from reviewer.models import Finding, Review, ToolResult
from reviewer.report import merge, render_console, render_markdown


def bandit_sqli():
    return Finding("bandit", "shop/db.py", 72, "medium", "security", "SQLi", rule="B608")


def llm_sqli():
    return Finding(
        "llm",
        "shop/db.py",
        72,
        "high",
        "security",
        "Inyección SQL",
        suggestion="Usar `?`.",
        verified=True,
        verification="corroborado por B608",
    )


def llm_money():
    return Finding(
        "llm",
        "shop/checkout.py",
        27,
        "high",
        "money",
        "Usa float.",
        verified=True,
        verification="The code divides by 100.",
    )


def test_merge_pairs_tool_finding_with_corroborating_llm_finding():
    pairs = merge([bandit_sqli(), llm_sqli(), llm_money()])
    assert [(f.source, e.source if e else None) for f, e in pairs] == [
        ("bandit", "llm"),
        ("llm", None),
    ]


def make_review(*findings):
    results = [
        ToolResult("bandit", True, 0.1, [f for f in findings if f.source == "bandit"]),
        ToolResult("llm", True, 1.0, [f for f in findings if f.source == "llm"]),
    ]
    return Review("main...feature/x", ["shop/db.py"], results, decide(results), 1.5, "2026-10-12")


def test_markdown_shows_verdict_reasons_and_merged_finding():
    md = render_markdown(make_review(bandit_sqli(), llm_sqli(), llm_money()))
    assert md.startswith("## ❌ Cambios requeridos")
    assert "bandit `B608` + LLM" in md
    assert "**`shop/db.py:72`** · HIGH" in md  # severidad mayor del par
    assert "> **Sugerencia:** Usar `?`." in md  # la sugerencia viene del LLM
    assert md.count("Inyección SQL") == 0  # el mensaje del LLM fusionado no se repite


def test_approved_review_without_findings():
    review = make_review()
    assert "## ✅ Aprobado" in render_markdown(review)
    assert "VEREDICTO: APPROVE" in render_console(review)


def test_review_round_trips_through_json_dict():
    review = make_review(bandit_sqli(), llm_sqli())
    assert Review.from_dict(review.to_dict()) == review
