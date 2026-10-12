import json
from pathlib import Path

from reviewer.diff import FileDiff
from reviewer.models import Finding, ToolResult
from reviewer.static import keep_changed_lines, parse_bandit, parse_junit, parse_ruff

WORKDIR = Path("/tmp/review/src")


def test_parse_bandit_maps_severity_and_cwe():
    output = json.dumps(
        {
            "results": [
                {
                    "filename": "shop/db.py",
                    "line_number": 72,
                    "issue_severity": "MEDIUM",
                    "issue_text": "Possible SQL injection.",
                    "issue_cwe": {"id": 89},
                    "test_id": "B608",
                }
            ]
        }
    )
    [finding] = parse_bandit(output, WORKDIR)
    assert finding.file == "shop/db.py"
    assert finding.severity == "medium"
    assert finding.rule == "B608"
    assert "CWE-89" in finding.message


def test_parse_ruff_classifies_pyflakes_as_bug():
    output = json.dumps(
        [
            {
                "filename": "shop/app.py",
                "location": {"row": 3, "column": 1},
                "code": "F401",
                "message": "`os` imported but unused",
                "fix": {"message": "Remove unused import"},
            },
            {
                "filename": "shop/app.py",
                "location": {"row": 9, "column": 101},
                "code": "E501",
                "message": "Line too long",
                "fix": None,
            },
        ]
    )
    unused, long_line = parse_ruff(output, WORKDIR)
    assert (unused.category, unused.severity) == ("bug", "medium")
    assert unused.suggestion == "Remove unused import"
    assert (long_line.category, long_line.severity) == ("style", "low")


def test_parse_junit_reports_only_failures():
    xml = """<testsuites><testsuite>
      <testcase classname="shop.tests.test_x" name="test_ok" line="3"/>
      <testcase classname="shop.tests.test_x" name="test_bad" line="7">
        <failure message="assert 1 == 2">trace</failure>
      </testcase>
    </testsuite></testsuites>"""
    [finding] = parse_junit(xml)
    assert finding.file == "shop/tests/test_x.py"
    assert finding.line == 8  # junit numera desde 0
    assert finding.severity == "high"
    assert "test_bad" in finding.message


def test_keep_changed_lines_drops_preexisting_findings():
    def finding(line):
        return Finding("ruff", "shop/app.py", line, "low", "style", "msg")

    result = ToolResult("ruff", True, 0.1, [finding(5), finding(20)])
    diffs = [FileDiff(path="shop/app.py", added_lines={5: "x = 1"})]
    kept = keep_changed_lines(result, diffs)
    assert [f.line for f in kept.findings] == [5]
    assert kept.omitted == 1
