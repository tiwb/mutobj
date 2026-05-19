"""mutobj.lint 测试 — CLI: 文本/JSON/退出码/--exclude"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ._helpers import make_pkg, write
from mutobj.lint.__main__ import main as cli_main


class TestCLI:
    def test_text_output_clean(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "ok.py", """
            from mutobj import Declaration
            class A(Declaration):
                def m(self): ...
        """)
        rc = cli_main([str(f)])
        captured = capsys.readouterr()
        assert rc == 0
        assert captured.out.strip() == ""

    def test_text_output_violations(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "bad.py", """
            from mutobj import Declaration
            class B(Declaration):
                def stub(self): ...
                def impl(self):
                    return 1
        """)
        rc = cli_main([str(f)])
        captured = capsys.readouterr()
        assert rc == 1
        assert "R001" in captured.out
        assert "bad.py" in captured.out
        # 形如 path:line:col: R001 ...
        assert ":" in captured.out

    def test_json_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "bad.py", """
            from mutobj import Declaration
            class B(Declaration):
                def stub(self): ...
                def impl(self):
                    return 1
        """)
        rc = cli_main([str(f), "--json"])
        captured = capsys.readouterr()
        assert rc == 1
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert data
        item = data[0]
        assert item["type"] == "issue"
        assert item["check_name"] == "R001"
        assert item["location"]["path"]
        assert "begin" in item["location"]["positions"]

    def test_exclude_option(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "vendor/bad.py", """
            from mutobj import Declaration
            class B(Declaration):
                def stub(self): ...
                def impl(self):
                    return 1
        """)
        rc = cli_main([str(pkg), "--exclude", "vendor"])
        captured = capsys.readouterr()
        assert rc == 0
        assert "bad.py" not in captured.out

    def test_module_invocation(self, tmp_path: Path) -> None:
        """python -m mutobj.lint <path> 应可调用"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "ok.py", """
            from mutobj import Declaration
            class A(Declaration):
                def m(self): ...
        """)
        result = subprocess.run(
            [sys.executable, "-m", "mutobj.lint", str(f)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
