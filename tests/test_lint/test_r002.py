"""mutobj.lint 测试 — R002: 声明文件底部 _impl import 规范"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ._helpers import make_pkg, write
from mutobj.lint import lint_directory, lint_file


# ============================================================ R002: 声明文件底部 _impl import 检查


class TestR002MissingImport:
    def test_missing_import_reports(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert len(r002) == 1
        assert "_view_impl" in r002[0].message
        assert r002[0].severity == "warning"

    def test_no_impl_file_no_report(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"
        """)
        msgs = lint_file(f)
        assert msgs == []

    def test_non_package_dir_no_report(self, tmp_path: Path) -> None:
        """没有 __init__.py 的目录不检查 R002"""
        d = tmp_path / "scripts"
        d.mkdir()
        f = d / "main.py"
        f.write_text(textwrap.dedent("""
            from mutobj import Declaration

            class App(Declaration):
                name: str = "app"
        """).lstrip(), encoding="utf-8")
        (d / "_main_impl.py").write_text("")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert r002 == []

    def test_non_impl_pattern_underscore_file_ignored(self, tmp_path: Path) -> None:
        """_protocol.py 之类不是 _impl 模式，不触发 R002"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "protocol.py", """
            from mutobj import Declaration

            class Proto(Declaration):
                version: int = 1
        """)
        write(pkg, "_protocol.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert r002 == []


class TestR002ImportVariants:
    def test_absolute_import_is_ok(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"


            import pkg._view_impl  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert r002 == []

    def test_from_import_module_is_ok(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"


            from pkg._view_impl import register  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert r002 == []

    def test_relative_import_is_ok(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"


            from . import _view_impl as _view_impl  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert r002 == []

    def test_from_package_import_module_is_ok(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"


            from pkg import _view_impl  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert r002 == []

    def test_import_as_alias_is_ok(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"


            import pkg._view_impl as _vi  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert r002 == []


class TestR002ImportSpacing:
    def test_two_blank_lines_before_import_is_ok(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"


            import pkg._view_impl  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert r002 == []

    def test_one_blank_line_warns(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"

            import pkg._view_impl  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert len(r002) == 1
        assert "空行" in r002[0].message

    def test_zero_blank_lines_warns(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"
            import pkg._view_impl  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert len(r002) == 1
        assert "空行" in r002[0].message


class TestR002Directory:
    def test_lint_directory_finds_pairs(self, tmp_path: Path) -> None:
        """lint_directory 扫描多文件，发现配对并报告"""
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"
        """)
        write(pkg, "_view_impl.py", "")
        write(pkg, "client.py", """
            from mutobj import Declaration

            class Client(Declaration):
                async def connect(self): ...


            import pkg._client_impl  # noqa: F401, E402
        """)
        write(pkg, "_client_impl.py", "")
        msgs = lint_directory(pkg)
        r002_msgs = [m for m in msgs if m.rule_id == "R002"]
        assert len(r002_msgs) == 1
        assert "view.py" in r002_msgs[0].path
        # client.py 有 import → 不报告
        assert all("client.py" not in m.path for m in r002_msgs)


# ============================================================ R002 第二轮：noqa 注释检查


class TestR002NoqaCheck:
    """R002 第二轮：import 行的 # noqa: F401, E402 注释检查"""

    def test_correct_noqa_passes(self, tmp_path: Path) -> None:
        """from . import ... as ...  # noqa: F401, E402 → OK"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"


            from . import _view_impl as _view_impl  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert r002 == []

    def test_missing_noqa_reports(self, tmp_path: Path) -> None:
        """缺少 # noqa: 注释 → R002 warning"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"


            from . import _view_impl as _view_impl
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert len(r002) == 1
        assert "noqa" in r002[0].message

    def test_missing_f401_reports(self, tmp_path: Path) -> None:
        """noqa 注释缺 F401 → R002 warning"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"


            from . import _view_impl as _view_impl  # noqa: E402
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert len(r002) == 1
        assert "F401" in r002[0].message

    def test_missing_e402_reports(self, tmp_path: Path) -> None:
        """noqa 注释缺 E402 → R002 warning"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"


            from . import _view_impl as _view_impl  # noqa: F401
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert len(r002) == 1
        assert "E402" in r002[0].message

    def test_noqa_reversed_order_passes(self, tmp_path: Path) -> None:
        """# noqa: E402, F401（顺序颠倒）→ OK"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"


            from . import _view_impl as _view_impl  # noqa: E402, F401
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert r002 == []

    def test_absolute_import_noqa_passes(self, tmp_path: Path) -> None:
        """import pkg._xxx_impl  # noqa: F401, E402 → OK"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"


            import pkg._view_impl  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert r002 == []

    def test_noqa_with_spaces_passes(self, tmp_path: Path) -> None:
        """# noqa: F401, E402（中间空格正常）→ OK"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"


            import pkg._view_impl  # noqa: F401,  E402
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert r002 == []


# ============================================================ R002 第二轮：as 别名检查


class TestR002AliasCheck:
    """R002 第二轮：from . import 的 as 别名检查"""

    def test_correct_alias_passes(self, tmp_path: Path) -> None:
        """from . import _xxx_impl as _xxx_impl → OK"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"


            from . import _view_impl as _view_impl  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert r002 == []

    def test_missing_alias_reports(self, tmp_path: Path) -> None:
        """from . import _xxx_impl（缺 as 别名）→ R002 warning"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"


            from . import _view_impl  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert len(r002) == 1
        assert "as" in r002[0].message

    def test_mismatched_alias_reports(self, tmp_path: Path) -> None:
        """from . import _xxx_impl as wrong_name → R002 warning"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"


            from . import _view_impl as _vi  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert len(r002) == 1
        assert "as" in r002[0].message

    def test_absolute_import_alias_not_checked(self, tmp_path: Path) -> None:
        """import pkg._xxx_impl as xxx — 绝对 import 不检查 as 别名"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"


            import pkg._view_impl as _v  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert r002 == []

    def test_noqa_and_alias_both_missing_reports_two(self, tmp_path: Path) -> None:
        """缺 noqa + 缺 as → 两条 R002 warning"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"


            from . import _view_impl
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r002 = [m for m in msgs if m.rule_id == "R002"]
        assert len(r002) == 2
        messages = " ".join(m.message for m in r002)
        assert "noqa" in messages
        assert "as" in messages
