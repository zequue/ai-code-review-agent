from reviewer.models import Finding
from reviewer.verify import corroborating_tool


def finding(source, line, rule=None, file="shop/db.py"):
    return Finding(source, file, line, "high", "security", "msg", rule=rule)


def test_llm_finding_matching_bandit_is_corroborated():
    static = [finding("bandit", 72, rule="B608")]
    assert corroborating_tool(finding("llm", 72), static) == "B608"
    assert corroborating_tool(finding("llm", 73), static) == "B608"


def test_distant_lines_other_files_or_linters_do_not_corroborate():
    static = [
        finding("bandit", 72, rule="B608"),
        finding("ruff", 10, rule="F401"),
        finding("bandit", 10, rule="B608", file="shop/app.py"),
    ]
    assert corroborating_tool(finding("llm", 80), static) is None
    assert corroborating_tool(finding("llm", 10), static) is None
