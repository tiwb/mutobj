"""mutobj.lint 测试 — 核心数据结构与扫描入口（LintMessage / lint_directory）"""

from __future__ import annotations

from pathlib import Path

import pytest

from mutobj.lint import LintMessage, lint_directory, lint_file

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


# ============================================================ lint_file 边界


class TestLintFileEdgeCases:
    """lint_file 边界输入：非 .py 文件 / 语法错误 / 读错误 / 非包目录"""

    def test_non_python_file_returns_empty(self, tmp_path: Path) -> None:
        """.txt 文件 → 返回 []"""
        f = tmp_path / "data.txt"
        f.write_text("not python", encoding="utf-8")
        assert lint_file(f) == []

    def test_syntax_error_returns_empty(self, tmp_path: Path) -> None:
        """语法错误的 .py 文件 → 返回 []"""
        f = tmp_path / "broken.py"
        f.write_text("def foo(\n", encoding="utf-8")
        assert lint_file(f) == []

    def test_oserror_returns_empty(self, tmp_path: Path) -> None:
        """读取 OSError → 返回 []"""
        from unittest.mock import patch

        pkg = make_pkg(tmp_path)
        f = write(pkg, "unreadable.py", """
            class X: pass
        """)
        with patch("pathlib.Path.read_text", side_effect=OSError("permission denied")):
            assert lint_file(f) == []

    def test_non_package_dir_no_crash(self, tmp_path: Path) -> None:
        """没有 __init__.py 的目录中 lint_file 不崩溃"""
        d = tmp_path / "scripts"
        d.mkdir()
        f = d / "main.py"
        # 普通类，非 Declaration 子类
        f.write_text("class Plain: pass", encoding="utf-8")
        assert lint_file(f) == []


class TestLintDirectoryFileArg:
    """lint_directory 传入文件路径（非目录）"""

    def test_single_file_arg_scans_file(self, tmp_path: Path) -> None:
        """lint_directory 传入单个 .py 文件也能扫描"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "bad.py", """
            from mutobj import Declaration
            class B(Declaration):
                def stub(self): ...
                def impl(self):
                    return 1
        """)
        msgs = lint_directory(f)
        assert len(msgs) > 0
        assert any("bad.py" in m.path for m in msgs)

    def test_non_py_file_arg_returns_empty(self, tmp_path: Path) -> None:
        """lint_directory 传入非 .py 文件 → 返回 []"""
        f = tmp_path / "readme.md"
        f.write_text("# hello", encoding="utf-8")
        assert lint_directory(f) == []


class TestLintDirectoryEdgeCases:
    """lint_directory 扫描中的边界文件"""

    def test_underscore_underscore_impl_stem_empty_skipped(
        self, tmp_path: Path,
    ) -> None:
        """__impl.py 文件 stem 为空 → _scan_impl_pairs 跳过"""
        pkg = make_pkg(tmp_path)
        write(pkg, "__impl.py", "")
        write(pkg, "legit.py", """
            from mutobj import Declaration
            class A(Declaration):
                def m(self): ...
        """)
        # 不应崩溃或误报
        msgs = lint_directory(pkg)
        assert msgs == []

    def test_double_underscore_impl_prefix_not_matched(
        self, tmp_path: Path,
    ) -> None:
        """___impl.py 不匹配 _*_impl.py 模式（fn[1:-8] 方式）"""
        pkg = make_pkg(tmp_path)
        write(pkg, "___impl.py", "")
        write(pkg, "ok.py", """
            from mutobj import Declaration
            class A(Declaration):
                def m(self): ...
        """)
        msgs = lint_directory(pkg)
        assert msgs == []


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
