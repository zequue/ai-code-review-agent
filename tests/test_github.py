from reviewer.gate import decide
from reviewer.github import inline_comments
from reviewer.models import Finding, Review, ToolResult


def make_review(findings, changed_lines):
    results = [
        ToolResult("rules", True, 0.1, [f for f in findings if f.source == "rules"]),
        ToolResult("pytest", True, 0.1, [f for f in findings if f.source == "pytest"]),
        ToolResult("llm", True, 0.1, [f for f in findings if f.source == "llm"]),
    ]
    return Review(
        "main...x", list(changed_lines), results, decide(results), 1.0, "now", changed_lines
    )


def test_only_findings_on_changed_lines_become_inline_comments():
    admin = Finding("rules", "shop/app.py", 46, "critical", "auth", "Sin auth", rule="ADMIN")
    broken_test = Finding("pytest", "shop/tests/test_app.py", 11, "high", "test", "Falla")
    comment = Finding("llm", "shop/db.py", 5, "low", "bug", "Detalle menor")
    review = make_review([admin, broken_test, comment], {"shop/app.py": [46], "shop/db.py": [5]})

    comments = inline_comments(review)

    assert [(c["path"], c["line"]) for c in comments] == [("shop/app.py", 46), ("shop/db.py", 5)]
    assert comments[0]["body"].startswith("⛔ Bloqueante · **CRITICAL**")
    assert not comments[1]["body"].startswith("⛔")
    assert all(c["side"] == "RIGHT" for c in comments)
