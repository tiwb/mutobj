"""mutobj.lint 测试 — 核心数据结构与扫描入口（LintMessage / lint_directory）"""

from __future__ import annotations

from pathlib import Path

import pytest

from mutobj.lint import LintMessage, lint_directory

from ._helpers import make_pkg, write


# ============================================================ lint_directory


class TestLintDirectory:
    def test_recursive_scan(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "ok.py", """
            from mutobj import Declaration
            class A(Declaration):
                def m(self): ...
        """)
        write(pkg, "sub/bad.py", """
            from mutobj import Declaration
            class B(Declaration):
                def stub(self): ...
                def impl(self):
                    return 1
        """)
        # sub 也需要是包
        (pkg / "sub" / "__init__.py").write_text("", encoding="utf-8")
        msgs = lint_directory(pkg)
        assert any("bad.py" in m.path for m in msgs)
        assert all("ok.py" not in m.path for m in msgs)

    def test_default_excludes_pycache(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "__pycache__/bad.py", """
            from mutobj import Declaration
            class B(Declaration):
                def stub(self): ...
                def impl(self):
                    return 1
        """)
        msgs = lint_directory(pkg)
        assert msgs == []

    def test_custom_exclude(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "vendor/bad.py", """
            from mutobj import Declaration
            class B(Declaration):
                def stub(self): ...
                def impl(self):
                    return 1
        """)
        msgs = lint_directory(pkg, exclude=["vendor"])
        assert msgs == []

    def test_results_sorted(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "z.py", """
            from mutobj import Declaration
            class Z(Declaration):
                def stub(self): ...
                def impl(self):
                    return 1
        """)
        write(pkg, "a.py", """
            from mutobj import Declaration
            class A(Declaration):
                def stub(self): ...
                def impl(self):
                    return 1
        """)
        msgs = lint_directory(pkg)
        paths = [m.path for m in msgs]
        assert paths == sorted(paths)


# ============================================================ LintMessage


class TestLintMessage:
    def test_immutable(self) -> None:
        m = LintMessage(
            path="x", line=1, column=0, rule_id="R001",
            message="msg", severity="error",
        )
        with pytest.raises(Exception):
            m.line = 2  # type: ignore[misc]

    def test_sortable(self) -> None:
        a = LintMessage(path="a.py", line=1, column=0, rule_id="R001",
                        message="m", severity="error")
        b = LintMessage(path="a.py", line=2, column=0, rule_id="R001",
                        message="m", severity="error")
        c = LintMessage(path="b.py", line=1, column=0, rule_id="R001",
                        message="m", severity="error")
        assert sorted([c, b, a]) == [a, b, c]
