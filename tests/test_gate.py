from reviewer.gate import decide
from reviewer.models import Finding, ToolResult


def finding(source, severity="high", verified=None, line=10):
    return Finding(source, "shop/app.py", line, severity, "security", "msg", verified=verified)


def result(tool, *findings, ok=True):
    return ToolResult(tool, ok, 0.1, list(findings), error=None if ok else "boom")


def test_clean_change_is_approved():
    verdict = decide([result("ruff"), result("bandit"), result("pytest"), result("llm")])
    assert verdict.decision == "APPROVE"
    assert verdict.reasons == [] and verdict.blocking == []


def test_failing_test_blocks():
    verdict = decide([result("pytest", finding("pytest"))])
    assert verdict.decision == "REQUEST_CHANGES"
    assert verdict.reasons == ["tests: hay tests que fallan"]


def test_bandit_medium_blocks_but_low_is_a_comment():
    assert decide([result("bandit", finding("bandit", "medium"))]).decision == "REQUEST_CHANGES"
    verdict = decide([result("bandit", finding("bandit", "low"))])
    assert verdict.decision == "APPROVE"
    assert len(verdict.comments) == 1


def test_llm_blocks_only_when_verified_and_high():
    unverified = decide([result("llm", finding("llm", "critical", verified=None))])
    assert unverified.decision == "APPROVE"
    medium = decide([result("llm", finding("llm", "medium", verified=True))])
    assert medium.decision == "APPROVE"
    confirmed = decide([result("llm", finding("llm", "high", verified=True))])
    assert confirmed.decision == "REQUEST_CHANGES"


def test_ruff_findings_never_block():
    verdict = decide([result("ruff", finding("ruff", "medium"))])
    assert verdict.decision == "APPROVE"


def test_deterministic_tool_failure_fails_closed():
    verdict = decide([result("pytest", ok=False)])
    assert verdict.decision == "REQUEST_CHANGES"
    assert "pytest" in verdict.reasons[0]


def test_llm_failure_fails_open_with_warning():
    verdict = decide([result("bandit"), result("llm", ok=False)])
    assert verdict.decision == "APPROVE"
    assert "parcial" in verdict.warnings[0]


def test_blocking_findings_are_sorted_by_severity():
    verdict = decide(
        [
            result("bandit", finding("bandit", "medium")),
            result("rules", finding("rules", "critical")),
        ]
    )
    assert [f.severity for f in verdict.blocking] == ["critical", "medium"]
