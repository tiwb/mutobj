"""Pyright regression tests for mutobj static typing.

- Positive fixtures (``tests/type_check/fixtures/``): must produce **zero**
  pyright diagnostics. They represent standard mutobj usage patterns.
- Negative fixtures (``tests/type_check/expected_errors/``): must produce
  diagnostics matching ``# pyright-expected:`` annotations in the source.

Pyright is invoked at most **twice** — once per directory — regardless of
how many fixture files exist.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"
EXPECTED_ERRORS = HERE / "expected_errors"

pytestmark = pytest.mark.skipif(
    shutil.which("pyright") is None,
    reason="pyright CLI not available",
)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _run_pyright(target: Path) -> dict:
    """Run ``pyright --outputjson`` on *target* and return the parsed report.

    pyright writes valid JSON to stdout even when diagnostics exist.
    """
    proc = subprocess.run(
        ["pyright", "--outputjson", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    return json.loads(proc.stdout)


def _diagnostics_for_file(report: dict, fixture: Path) -> list[dict]:
    """Return diagnostics from *report* that belong to *fixture*."""
    fixture_resolved = fixture.resolve()
    result: list[dict] = []
    for d in report.get("generalDiagnostics", []):
        file_str = d.get("file", "")
        if file_str:
            try:
                if Path(file_str).resolve() == fixture_resolved:
                    result.append(d)
            except (OSError, ValueError):
                pass  # malformed path in pyright output — skip
    return result


def _format_diagnostic(d: dict) -> str:
    """Format a single pyright diagnostic for error messages."""
    start = d["range"]["start"]
    return (
        f"  [{d.get('rule', d.get('severity', '?'))}] "
        f"{start['line'] + 1}:{start['character'] + 1} "
        f"{d['message']}"
    )


# ---------------------------------------------------------------------------
# 正向 fixtures — 零诊断
# ---------------------------------------------------------------------------

_POSITIVE_FILES = sorted(FIXTURES.glob("*.py"))

if _POSITIVE_FILES:

    @pytest.fixture(scope="module")
    def _positive_report() -> dict:
        """pyright report for the entire ``fixtures/`` directory (once)."""
        return _run_pyright(FIXTURES)

    @pytest.mark.parametrize(
        "fixture",
        _POSITIVE_FILES,
        ids=lambda p: p.stem,
    )
    def test_fixture_typechecks_clean(
        fixture: Path, _positive_report: dict
    ) -> None:
        """Each positive fixture must produce zero pyright diagnostics."""
        diags = _diagnostics_for_file(_positive_report, fixture)
        if diags:
            lines = [
                f"pyright reported {len(diags)} diagnostic(s) "
                f"in {fixture.name}:"
            ]
            lines.extend(_format_diagnostic(d) for d in diags)
            pytest.fail("\n".join(lines))


# ---------------------------------------------------------------------------
# 反向 fixtures — 预期特定诊断
# ---------------------------------------------------------------------------

# Format:  # pyright-expected: <rule> <message substring>
_EXPECTED_RE = re.compile(r'^\s*#\s*pyright-expected:\s*(\S+)\s+(.+)\s*$')

_NEGATIVE_FILES = (
    sorted(EXPECTED_ERRORS.glob("*.py"))
    if EXPECTED_ERRORS.is_dir()
    else []
)


def _extract_expected(fixture: Path) -> list[tuple[str, str]]:
    """Parse ``# pyright-expected:`` annotations from fixture source.

    Returns list of ``(rule, message_substring)`` tuples.
    """
    expected: list[tuple[str, str]] = []
    with open(fixture, encoding="utf-8") as f:
        for line in f:
            m = _EXPECTED_RE.match(line.rstrip("\n"))
            if m:
                expected.append((m.group(1), m.group(2)))
    return expected


if _NEGATIVE_FILES:

    @pytest.fixture(scope="module")
    def _negative_report() -> dict:
        """pyright report for the entire ``expected_errors/`` directory (once)."""
        return _run_pyright(EXPECTED_ERRORS)

    @pytest.mark.parametrize(
        "fixture",
        _NEGATIVE_FILES,
        ids=lambda p: p.stem,
    )
    def test_fixture_reports_expected_errors(
        fixture: Path, _negative_report: dict
    ) -> None:
        """Each negative fixture must produce exactly the diagnostics
        declared by its ``# pyright-expected:`` annotations.
        """
        expected = _extract_expected(fixture)
        actual = _diagnostics_for_file(_negative_report, fixture)

        # ── build (rule, message) pairs for matching ──
        actual_pairs: list[tuple[str, str]] = [
            (d.get("rule", ""), d["message"]) for d in actual
        ]

        # ── match expected → actual ──
        unmatched_expected: list[tuple[str, str]] = []
        matched_indices: set[int] = set()
        for e_rule, e_msg in expected:
            found = False
            for i, (a_rule, a_msg) in enumerate(actual_pairs):
                if i in matched_indices:
                    continue
                if e_rule == a_rule and e_msg in a_msg:
                    matched_indices.add(i)
                    found = True
                    break
            if not found:
                unmatched_expected.append((e_rule, e_msg))

        # ── unmatched actual ──
        unmatched_actual = [
            actual[i] for i in range(len(actual))
            if i not in matched_indices
        ]

        # ── report ──
        if unmatched_expected or unmatched_actual:
            lines = [f"Diagnostic mismatch in {fixture.name}:"]
            if unmatched_expected:
                lines.append("  Expected but NOT reported:")
                for rule, msg in unmatched_expected:
                    lines.append(f'    [{rule}] "{msg}"')
            if unmatched_actual:
                lines.append("  Unexpected diagnostics:")
                lines.extend(
                    f"    {_format_diagnostic(d).strip()}"
                    for d in unmatched_actual
                )
            pytest.fail("\n".join(lines))
