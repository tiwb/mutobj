from __future__ import annotations

from pathlib import Path

from mutobj.lint import check

from ._helpers import import_temp_pkg, make_pkg, write


class TestR002Semantic:
    def test_stub_without_impl_reports(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "service.py", """
            from mutobj import Declaration

            class Service(Declaration):
                def run(self, value: int) -> str: ...
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        assert len(messages) == 1
        assert messages[0].rule_id == "R002"
        assert messages[0].severity == "error"

    def test_registered_impl_passes(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "service.py", """
            from mutobj import Declaration

            class Service(Declaration):
                def run(self, value: int) -> str: ...


            from . import _service_impl as _service_impl  # noqa: F401, E402
        """)
        write(pkg, "_service_impl.py", """
            from mutobj import impl

            from .service import Service


            @impl(Service.run)
            def service_run(self, value: int) -> str:
                return str(value)
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        assert not [message for message in messages if message.rule_id == "R002" and message.severity == "error"]


    def test_property_getter_with_impl_passes(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "service.py", """
            from mutobj import Declaration

            class Service(Declaration):
                @property
                def name(self) -> str: ...


            from . import _service_impl as _service_impl  # noqa: F401, E402
        """)
        write(pkg, "_service_impl.py", """
            from mutobj import impl

            from .service import Service


            @impl(Service.name.getter)
            def service_name(self) -> str:
                return "stub"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        errors = [m for m in messages if m.rule_id == "R002" and m.severity == "error"]
        assert not errors, f"Unexpected R002 errors: {errors}"

    def test_property_getter_without_impl_reports(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "service.py", """
            from mutobj import Declaration

            class Service(Declaration):
                @property
                def name(self) -> str: ...
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        errors = [m for m in messages if m.rule_id == "R002" and m.severity == "error"]
        assert len(errors) == 1
        assert "Service.name" in errors[0].symbol


class TestR002Format:
    def test_missing_bottom_import_warns(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class View(Declaration):
                def render(self) -> str: ...
        """)
        write(pkg, "_view_impl.py", """
            from mutobj import impl

            from .view import View


            @impl(View.render)
            def view_render(self) -> str:
                return "ok"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.view", "pkg._view_impl"]).messages
        warnings = [message for message in messages if message.rule_id == "R002" and message.severity == "warning"]
        assert len(warnings) == 1
        assert "缺少" in warnings[0].message

    def test_relative_import_alias_and_noqa_pass(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class View(Declaration):
                def render(self) -> str: ...


            from . import _view_impl as _view_impl  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", """
            from mutobj import impl

            from .view import View


            @impl(View.render)
            def view_render(self) -> str:
                return "ok"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        assert not [message for message in messages if message.rule_id == "R002" and message.severity == "warning"]

    def test_wrong_spacing_warns(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class View(Declaration):
                def render(self) -> str: ...

            from . import _view_impl as _view_impl  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", """
            from mutobj import impl

            from .view import View


            @impl(View.render)
            def view_render(self) -> str:
                return "ok"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        spacing_warnings = [m for m in messages if "空行" in m.message]
        assert len(spacing_warnings) == 1
        assert spacing_warnings[0].rule_id == "R002"

    def test_init_py_skip_format(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "__init__.py", """
            from mutobj import Declaration

            class Service(Declaration):
                def run(self) -> str: ...
        """)
        write(pkg, "_service_impl.py", """
            from mutobj import impl

            from . import Service


            @impl(Service.run)
            def service_run(self) -> str:
                return "ok"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        assert not [m for m in messages if m.rule_id == "R002" and m.severity == "warning"]

    def test_missing_alias_warns(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class View(Declaration):
                def render(self) -> str: ...


            from . import _view_impl  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", """
            from mutobj import impl

            from .view import View


            @impl(View.render)
            def view_render(self) -> str:
                return "ok"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        assert any(message.rule_id == "R002" and "as" in message.message for message in messages)

    def test_absolute_import_format_warns(self, tmp_path: Path) -> None:
        """末尾 import 使用绝对导入 `import pkg._view_impl` 格式不被识别 → 报缺少 import"""
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class View(Declaration):
                def render(self) -> str: ...


            import pkg._view_impl
        """)
        write(pkg, "_view_impl.py", """
            from mutobj import impl

            from .view import View


            @impl(View.render)
            def view_render(self) -> str:
                return "ok"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        # 绝对 import 不被 _is_import_of 识别，会报"缺少 import 注册语句"
        warnings = [m for m in messages if m.rule_id == "R002" and m.severity == "warning"]
        assert any("缺少" in m.message for m in warnings)

    def test_noqa_missing_e402_warns(self, tmp_path: Path) -> None:
        """末尾 import 行 noqa 只有 F401 缺 E402 → 报缺少 E402"""
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class View(Declaration):
                def render(self) -> str: ...


            from . import _view_impl as _view_impl  # noqa: F401
        """)
        write(pkg, "_view_impl.py", """
            from mutobj import impl

            from .view import View


            @impl(View.render)
            def view_render(self) -> str:
                return "ok"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        assert any("E402" in m.message for m in messages if m.rule_id == "R002")

    def test_no_impl_file_skips_format(self, tmp_path: Path) -> None:
        """没有 _impl.py 文件时跳过格式检查（不报 warning）"""
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class View(Declaration):
                def render(self) -> str: ...
        """)
        # 不创建 _view_impl.py
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        # 会有 R002 error（stub 无 impl），但不应有 format warning
        warnings = [m for m in messages if m.rule_id == "R002" and m.severity == "warning"]
        assert not warnings, f"Unexpected format warnings: {warnings}"
