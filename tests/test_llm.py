import json

from reviewer.diff import FileDiff
from reviewer.llm import files_to_review, parse_findings, render_file

DIFF = FileDiff(path="shop/checkout.py", added_lines={10: "x = 1", 11: "y = 2"})


def response(*findings):
    return json.dumps({"findings": list(findings)})


def item(**overrides):
    base = {
        "line": 10,
        "severity": "high",
        "category": "money",
        "message": "Usa float para dinero.",
        "suggestion": "Usar centavos enteros.",
        "confidence": 0.9,
    }
    return {**base, **overrides}


def test_valid_finding_is_kept():
    [finding], dropped = parse_findings(response(item()), DIFF)
    assert dropped == 0
    assert (finding.source, finding.file, finding.line) == ("llm", "shop/checkout.py", 10)
    assert finding.confidence == 0.9


def test_findings_outside_the_diff_are_dropped():
    findings, dropped = parse_findings(response(item(line=99), item(line=11)), DIFF)
    assert [f.line for f in findings] == [11]
    assert dropped == 1


def test_invalid_enums_and_duplicates_are_dropped():
    raw = response(item(severity="urgent"), item(category="style"), item(), item())
    findings, dropped = parse_findings(raw, DIFF)
    assert len(findings) == 1
    assert dropped == 3


def test_same_problem_on_nearby_lines_is_reported_once():
    diff = FileDiff(path="shop/checkout.py", added_lines={27: "a", 28: "b", 29: "c", 40: "d"})
    raw = response(item(line=27), item(line=29), item(line=40), item(line=28, category="bug"))
    findings, dropped = parse_findings(raw, diff)
    assert [(f.line, f.category) for f in findings] == [(27, "money"), (40, "money"), (28, "bug")]
    assert dropped == 1


def test_confidence_is_clamped_and_code_fences_tolerated():
    raw = "```json\n" + response(item(confidence=7)) + "\n```"
    [finding], _ = parse_findings(raw, DIFF)
    assert finding.confidence == 1.0


def test_render_marks_changed_lines():
    listing = render_file("a = 1\nb = 2\nc = 3", {2: "b = 2"})
    assert listing.splitlines() == ["    1  | a = 1", "    2 +| b = 2", "    3  | c = 3"]


def test_render_trims_large_files_around_changes():
    content = "\n".join(f"line {n}" for n in range(1, 1001))
    listing = render_file(content, {500: "line 500"})
    assert "  500 +| line 500" in listing
    assert "line 1\n" not in listing and "line 1000" not in listing
    assert listing.startswith("      ...")


def test_tests_and_deleted_files_are_not_sent_to_the_model():
    diffs = [
        FileDiff(path="shop/app.py", added_lines={1: "x"}),
        FileDiff(path="shop/tests/test_app.py", added_lines={1: "x"}),
        FileDiff(path="shop/old.py", is_deleted=True),
        FileDiff(path="README.md", added_lines={1: "x"}),
    ]
    assert [d.path for d in files_to_review(diffs)] == ["shop/app.py"]
