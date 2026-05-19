"""
mutobj.lint 测试 — 覆盖 R001 各类场景与 CLI 行为
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from mutobj.lint import LintMessage, lint_directory, lint_file
from mutobj.lint.__main__ import main as cli_main


# ============================================================ helpers


def write(tmp: Path, rel: str, code: str) -> Path:
    """在 tmp 下创建文件（自动建父目录），写入 dedent 后的代码"""
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(code).lstrip(), encoding="utf-8")
    return p


def make_pkg(tmp: Path, name: str = "pkg") -> Path:
    """创建一个最小包结构 pkg/__init__.py，返回包目录"""
    pkg = tmp / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    return pkg


# ============================================================ R001: 单文件 / 直接基类


class TestR001PureDeclarationFile:
    def test_all_stubs_no_error(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "decl.py", """
            from mutobj import Declaration

            class Foo(Declaration):
                def method_a(self) -> int: ...
                def method_b(self, x: int) -> str: ...
        """)
        msgs = lint_file(pkg / "decl.py")
        assert msgs == []

    def test_stub_with_docstring(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "decl.py", '''
            from mutobj import Declaration

            class Foo(Declaration):
                def method_a(self) -> int:
                    """方法 A 的文档"""
                    ...
        ''')
        msgs = lint_file(pkg / "decl.py")
        assert msgs == []

    def test_empty_class_treated_as_declaration(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "decl.py", """
            from mutobj import Declaration

            class Foo(Declaration):
                pass
        """)
        msgs = lint_file(pkg / "decl.py")
        assert msgs == []


class TestR001PureImplementationFile:
    def test_all_implementations_no_error(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "impl.py", """
            from mutobj import Declaration

            class Foo(Declaration):
                def method_a(self) -> int:
                    return 1
                def method_b(self, x: int) -> str:
                    return str(x)
        """)
        msgs = lint_file(pkg / "impl.py")
        assert msgs == []

    def test_pass_body_is_implementation(self, tmp_path: Path) -> None:
        """单纯的 pass 算实现，与 ... 桩区分开"""
        pkg = make_pkg(tmp_path)
        write(pkg, "impl.py", """
            from mutobj import Declaration

            class Foo(Declaration):
                def method_a(self) -> None:
                    pass
                def method_b(self) -> None:
                    pass
        """)
        msgs = lint_file(pkg / "impl.py")
        assert msgs == []


class TestR001ClassLevelMix:
    def test_stub_plus_raise_mix(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "bad.py", """
            from mutobj import Declaration

            class Foo(Declaration):
                def stub_m(self) -> int: ...
                def impl_m(self) -> int:
                    raise NotImplementedError
        """)
        msgs = lint_file(f)
        assert len(msgs) == 1
        assert msgs[0].rule_id == "R001"
        assert "impl_m" in msgs[0].message
        assert "类级" in msgs[0].message

    def test_stub_plus_pass_mix(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "bad.py", """
            from mutobj import Declaration

            class Foo(Declaration):
                def stub_m(self) -> int: ...
                def impl_m(self) -> None:
                    pass
        """)
        msgs = lint_file(f)
        assert len(msgs) == 1
        assert msgs[0].rule_id == "R001"


class TestR001FileLevelMix:
    def test_declaration_class_and_implementation_class_in_same_file(
        self, tmp_path: Path,
    ) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "bad.py", """
            from mutobj import Declaration

            class Decl(Declaration):
                def method_a(self) -> int: ...

            class Impl(Declaration):
                def method_a(self) -> int:
                    return 1
        """)
        msgs = lint_file(f)
        # 文件级混合：两个类都报告
        assert len(msgs) >= 2
        names_in_msgs = " ".join(m.message for m in msgs)
        assert "Decl" in names_in_msgs
        assert "Impl" in names_in_msgs
        assert any("文件级" in m.message for m in msgs)


# ============================================================ R001: 跳过 / 不报警


class TestR001Skip:
    def test_no_declaration_class_skipped(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "plain.py", """
            class Plain:
                def m(self) -> int:
                    return 1
                def stub(self): ...
        """)
        # 普通类即使有 ... 也不报警
        assert lint_file(f) == []

    def test_unknown_base_conservative(self, tmp_path: Path) -> None:
        """无法判定基类（未 import Declaration、跨包）→ 不报警"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "ambig.py", """
            from some_other_package import SomeBase

            class Foo(SomeBase):
                def m1(self): ...
                def m2(self):
                    return 1
        """)
        assert lint_file(f) == []


# ============================================================ R001: 装饰器与 overload


class TestR001Decorators:
    def test_overload_excluded(self, tmp_path: Path) -> None:
        """@overload 桩不影响实现类的判定"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "impl.py", """
            from typing import overload
            from mutobj import Declaration

            class Foo(Declaration):
                @overload
                def m(self, x: int) -> int: ...
                @overload
                def m(self, x: str) -> str: ...
                def m(self, x):
                    return x
        """)
        assert lint_file(f) == []

    def test_typing_overload_qualified(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "impl.py", """
            import typing
            from mutobj import Declaration

            class Foo(Declaration):
                @typing.overload
                def m(self, x: int) -> int: ...
                def m(self, x):
                    return x
        """)
        assert lint_file(f) == []

    def test_property_stub_treated_as_stub(self, tmp_path: Path) -> None:
        """@property 装饰器透明：body 决定一切"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "decl.py", """
            from mutobj import Declaration

            class Foo(Declaration):
                @property
                def name(self) -> str: ...
                def method(self) -> int: ...
        """)
        assert lint_file(f) == []

    def test_property_impl_in_decl_class_reports(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "bad.py", """
            from mutobj import Declaration

            class Foo(Declaration):
                @property
                def name(self) -> str: ...
                @property
                def value(self) -> int:
                    return 1
        """)
        msgs = lint_file(f)
        assert len(msgs) == 1
        assert "value" in msgs[0].message


# ============================================================ R001: import 别名 / 跨文件


class TestR001ImportAlias:
    def test_declaration_aliased(self, tmp_path: Path) -> None:
        """from mutobj import Declaration as D"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "decl.py", """
            from mutobj import Declaration as D

            class Foo(D):
                def m(self): ...
        """)
        assert lint_file(f) == []

    def test_mutobj_module_attribute(self, tmp_path: Path) -> None:
        """import mutobj; class Foo(mutobj.Declaration)"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "decl.py", """
            import mutobj

            class Foo(mutobj.Declaration):
                def m(self): ...
                def n(self): ...
        """)
        assert lint_file(f) == []

    def test_mutobj_module_attribute_mixed_reports(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "bad.py", """
            import mutobj

            class Foo(mutobj.Declaration):
                def m(self): ...
                def n(self):
                    return 1
        """)
        msgs = lint_file(f)
        assert len(msgs) == 1
        assert "类级" in msgs[0].message


class TestR001CrossFile:
    def test_transitive_same_package(self, tmp_path: Path) -> None:
        """B 文件继承 A 文件中的 Declaration 子类，应被识别"""
        pkg = make_pkg(tmp_path)
        write(pkg, "base.py", """
            from mutobj import Declaration

            class Animal(Declaration):
                def speak(self) -> str: ...
        """)
        f = write(pkg, "derived.py", """
            from pkg.base import Animal

            class Dog(Animal):
                def speak(self) -> str: ...
                def fetch(self) -> None: ...
        """)
        # 让 resolver 能找到 pkg.base，需要把 tmp_path 作为搜索根
        # 但 lint_file 的 resolver 是基于 Python 包路径推断，pkg.base 应可解析
        msgs = lint_file(f)
        assert msgs == []

    def test_transitive_same_package_mixed_reports(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "base.py", """
            from mutobj import Declaration

            class Animal(Declaration):
                def speak(self) -> str: ...
        """)
        f = write(pkg, "derived.py", """
            from pkg.base import Animal

            class Dog(Animal):
                def speak(self) -> str: ...
                def fetch(self) -> None:
                    return None
        """)
        msgs = lint_file(f)
        assert len(msgs) == 1
        assert msgs[0].rule_id == "R001"

    def test_relative_import(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "base.py", """
            from mutobj import Declaration

            class Animal(Declaration):
                def speak(self) -> str: ...
        """)
        f = write(pkg, "derived.py", """
            from .base import Animal

            class Dog(Animal):
                def speak(self) -> str: ...
        """)
        msgs = lint_file(f)
        assert msgs == []

    def test_cross_top_package_unresolvable_no_warn(
        self, tmp_path: Path,
    ) -> None:
        """跨顶层包不解析，保守不报警"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "user.py", """
            from totally_unknown.thing import Base

            class Foo(Base):
                def m1(self): ...
                def m2(self):
                    return 1
        """)
        assert lint_file(f) == []


# ============================================================ R001: 无行为类 / __init__ 纳入判定


class TestR001Behaviorless:
    """零方法的 Declaration 子类不参与文件级混合判定"""

    def test_marker_coexists_with_implementation(
        self, tmp_path: Path,
    ) -> None:
        """空 Marker 类 + 实现类 → 应通过（之前会误报文件级混合）"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "mixed.py", """
            from mutobj import Declaration

            class Marker(Declaration):
                \"\"\"空标记类\"\"\"
                pass

            class WithImpl(Declaration):
                def m(self) -> int:
                    return 1
        """)
        assert lint_file(f) == []

    def test_marker_coexists_with_declaration(
        self, tmp_path: Path,
    ) -> None:
        """空 Marker 类 + 声明类 → 应通过"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "with_decl.py", """
            from mutobj import Declaration

            class Marker(Declaration):
                pass

            class Decl(Declaration):
                def m(self) -> int: ...
        """)
        assert lint_file(f) == []

    def test_all_behaviorless_classes(self, tmp_path: Path) -> None:
        """多个全空 Declaration 子类共存 → 通过"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "empties.py", """
            from mutobj import Declaration

            class A(Declaration): pass
            class B(Declaration): pass
            class C(Declaration): pass
        """)
        assert lint_file(f) == []

    def test_marker_does_not_get_file_level_reported(
        self, tmp_path: Path,
    ) -> None:
        """即使文件级混合发生，无行为类也不被报告"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "real_mix.py", """
            from mutobj import Declaration

            class Marker(Declaration):
                pass

            class Decl(Declaration):
                def m(self) -> int: ...

            class Impl(Declaration):
                def n(self) -> int:
                    return 1
        """)
        msgs = lint_file(f)
        # Decl 和 Impl 报告，Marker 不报告
        reported_names = " ".join(m.message for m in msgs)
        assert "Decl" in reported_names
        assert "Impl" in reported_names
        assert "Marker" not in reported_names


class TestR001InitNotExempt:
    """`__init__` 不豁免：与普通方法走同一套桩/实现判定。

    设计依据：mutobj `Declaration` 基类已提供通用 `__init__`，派生计算走
    `__post_init__`。decl 文件中的 `__init__` 要么不写（用基类），要么写成
    桩（`...` + `@impl`）。含 `super().__init__()` / `pass` / 赋值等实际语句的
    `__init__` 是实现，与同类的桩方法违反R001 一致性。
    """

    def test_super_init_call_in_declaration_class_is_violation(
        self, tmp_path: Path,
    ) -> None:
        """声明类中 `__init__` 调 super().__init__() → 类级混合报告"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "decl_super_init.py", """
            from mutobj import Declaration

            class Foo(Declaration):
                def __init__(self, x: int):
                    super().__init__()
                    self.x = x

                def method_a(self) -> int: ...
                def method_b(self) -> str: ...
        """)
        msgs = lint_file(f)
        assert len(msgs) == 1
        assert msgs[0].rule_id == "R001"
        # 被报告的是实现方法（__init__）
        assert "__init__" in msgs[0].message
        assert "类级风格混合" in msgs[0].message

    def test_pass_init_in_declaration_class_is_violation(
        self, tmp_path: Path,
    ) -> None:
        """声明类中 `__init__` body 是 `pass` → 类级混合报告。

        跟 R001 对 `pass` 的一贯处理一致：`pass` 是实现。
        """
        pkg = make_pkg(tmp_path)
        f = write(pkg, "decl_pass_init.py", """
            from mutobj import Declaration

            class Foo(Declaration):
                def __init__(self, x: int):
                    pass

                def method_a(self) -> int: ...
        """)
        msgs = lint_file(f)
        assert len(msgs) == 1
        assert "__init__" in msgs[0].message

    def test_stub_init_in_declaration_class_is_ok(
        self, tmp_path: Path,
    ) -> None:
        """声明类中 `__init__` 是 `...` 桩 → 合法（可由 @impl 提供实现）"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "decl_stub_init.py", """
            from mutobj import Declaration

            class Foo(Declaration):
                def __init__(self, x: int) -> None: ...
                def method_a(self) -> int: ...
                def method_b(self) -> str: ...
        """)
        assert lint_file(f) == []

    def test_stub_init_in_implementation_class_is_violation(
        self, tmp_path: Path,
    ) -> None:
        """实现类中 `__init__` 是 `...` 桩 → 类级混合报告。

        实现侧不应出现桩方法，__init__ 同样适用。
        """
        pkg = make_pkg(tmp_path)
        f = write(pkg, "impl_stub_init.py", """
            from mutobj import Declaration

            class Foo(Declaration):
                def __init__(self, x: int) -> None: ...

                def method_a(self) -> int:
                    return 1
        """)
        msgs = lint_file(f)
        # `method_a` 是实现、`__init__` 是桩 → 类级混合。类级混合下报告的是实现方法。
        assert len(msgs) == 1
        assert "method_a" in msgs[0].message

    def test_only_implementation_init_is_implementation_class(
        self, tmp_path: Path,
    ) -> None:
        """全类只有实现型 `__init__` → 实现类（不再是无行为类）。

        与同文件的声明类共存 → 文件级混合报告。
        """
        pkg = make_pkg(tmp_path)
        f = write(pkg, "only_init_impl.py", """
            from mutobj import Declaration

            class Foo(Declaration):
                def __init__(self, x: int):
                    self.x = x

            class Decl(Declaration):
                def m(self) -> int: ...
        """)
        msgs = lint_file(f)
        # Foo 是实现类、Decl 是声明类 → 文件级混合，两个都被报告
        names = " ".join(m.message for m in msgs)
        assert "Foo" in names
        assert "Decl" in names
        assert all("文件级风格混合" in m.message for m in msgs)

    def test_only_stub_init_is_declaration_class(
        self, tmp_path: Path,
    ) -> None:
        """全类只有桩型 `__init__` → 声明类。

        与同文件的实现类共存 → 文件级混合报告。
        """
        pkg = make_pkg(tmp_path)
        f = write(pkg, "only_init_stub.py", """
            from mutobj import Declaration

            class Foo(Declaration):
                def __init__(self, x: int) -> None: ...

            class Impl(Declaration):
                def m(self) -> int:
                    return 1
        """)
        msgs = lint_file(f)
        names = " ".join(m.message for m in msgs)
        assert "Foo" in names
        assert "Impl" in names
        assert all("文件级风格混合" in m.message for m in msgs)


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


# ============================================================ CLI


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


# ============================================================ R001 扩展：decl-impl 配对约束


class TestR001PairedDeclEnforcement:
    """decl-impl 配对的声明侧文件中，Declaration 子类必须是纯声明类"""

    def test_paired_decl_with_raise_notimplementederror_reports(
        self, tmp_path: Path,
    ) -> None:
        """声明侧文件中有 raise NotImplementedError → R001"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                def render(self):
                    raise NotImplementedError
                async def on_event(self, event):
                    raise NotImplementedError
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r001_msgs = [m for m in msgs if m.rule_id == "R001"]
        assert len(r001_msgs) == 1
        assert "MyView" in r001_msgs[0].message
        assert "_impl" in r001_msgs[0].message

    def test_paired_decl_all_stubs_is_clean(self, tmp_path: Path) -> None:
        """声明侧文件全 ... 桩 → 不报"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "channel.py", """
            from mutobj import Declaration

            class Channel(Declaration):
                async def send(self, data): ...
                async def recv(self): ...


            from . import _channel_impl as _channel_impl  # noqa: F401, E402
        """)
        write(pkg, "_channel_impl.py", "")
        msgs = lint_file(f)
        assert msgs == []

    def test_paired_decl_mixed_reports_both_violations(
        self, tmp_path: Path,
    ) -> None:
        """既有桩又有实现的类 → 类级混合 + decl 配对违规都报"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                path: str = "/"
                def render(self): ...
                def on_event(self, event):
                    raise NotImplementedError
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        r001_msgs = [m for m in msgs if m.rule_id == "R001"]
        assert len(r001_msgs) >= 2
        # 一条是类级混合（原 R001），一条是 decl 配对约束
        assert any("类级" in m.message for m in r001_msgs)
        assert any("_impl" in m.message for m in r001_msgs)

    def test_paired_decl_marker_class_is_ok(self, tmp_path: Path) -> None:
        """声明侧文件中的零方法标记类 → 不报"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class Marker(Declaration):
                pass

            class MyView(Declaration):
                def render(self): ...


            from . import _view_impl as _view_impl  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", "")
        msgs = lint_file(f)
        assert msgs == []

    def test_not_paired_no_extra_check(self, tmp_path: Path) -> None:
        """没有 _impl 配对 → 不触发 decl 侧约束（原 R001 行为）"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                def render(self):
                    raise NotImplementedError
        """)
        # 没有 _view_impl.py → 不检查配对约束
        msgs = lint_file(f)
        assert msgs == []


# ============================================================ Dogfooding


class TestDogfooding:
    def test_mutobj_self_clean(self) -> None:
        """对 mutobj 自身 src 跑 lint，应零违规"""
        import mutobj
        src_root = Path(mutobj.__file__).parent
        msgs = lint_directory(src_root)
        # 允许列出一下若失败便于排查
        assert msgs == [], "\n".join(
            f"{m.path}:{m.line}:{m.column}: {m.rule_id} {m.message}"
            for m in msgs
        )
