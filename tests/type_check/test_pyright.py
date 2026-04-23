"""Pyright regression tests for Declaration subclass static typing.

These tests invoke the `pyright` CLI on fixtures under `./fixtures/` and
assert zero diagnostics. Each fixture is self-contained — it uses mutobj
in the *standard* way and should type-check cleanly. Any regression in
mutobj's typing surface (e.g. `Declaration.__new__` returning the base
class instead of `Self`) will cause pyright to flag the fixture and fail
the test.

If pyright is not installed, tests are skipped.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.skipif(
    shutil.which("pyright") is None,
    reason="pyright CLI not available",
)


def _run_pyright(target: Path) -> dict:
    proc = subprocess.run(
        ["pyright", "--outputjson", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    # pyright 有诊断时 exit code 非 0，但 stdout 的 JSON 仍然有效
    return json.loads(proc.stdout)


@pytest.mark.parametrize(
    "fixture",
    sorted(FIXTURES.glob("*.py")),
    ids=lambda p: p.stem,
)
def test_fixture_typechecks_clean(fixture: Path) -> None:
    """Every fixture must pass pyright with zero errors and warnings.

    Fixtures represent standard mutobj usage patterns. When mutobj's typing
    regresses (e.g. __new__ stops returning Self), pyright will flag the
    usage and this test fails with the diagnostic list.
    """
    report = _run_pyright(fixture)
    summary = report["summary"]
    diagnostics = report.get("generalDiagnostics", [])

    if summary["errorCount"] or summary["warningCount"]:
        lines = [f"pyright reported {summary['errorCount']} errors, "
                 f"{summary['warningCount']} warnings in {fixture.name}:"]
        for d in diagnostics:
            start = d["range"]["start"]
            lines.append(
                f"  [{d['severity']}] {start['line'] + 1}:{start['character'] + 1} "
                f"{d['message']}"
            )
        pytest.fail("\n".join(lines))
