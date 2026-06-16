from __future__ import annotations

from pathlib import Path

from mutobj.lint import check

from ._helpers import import_temp_pkg, make_pkg, write


class TestR003Runtime:
    def test_method_name_requires_type_and_member_prefix(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "service.py", """
            from mutobj import Declaration

            class Service(Declaration):
                def run(self) -> str: ...


            from . import _service_impl as _service_impl  # noqa: F401, E402
        """)
        write(pkg, "_service_impl.py", """
            from mutobj import impl

            from .service import Service


            @impl(Service.run)
            def run(self) -> str:
                return "ok"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        warnings = [message for message in messages if message.rule_id == "R003"]
        assert len(warnings) == 1
        assert "service_run" in warnings[0].message

    def test_field_getter_uses_owner_type_name(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "config.py", """
            from mutobj import Declaration

            class Config(Declaration):
                root: str = "/"


            from . import _config_impl as _config_impl  # noqa: F401, E402
        """)
        write(pkg, "_config_impl.py", """
            from mutobj import impl

            from .config import Config


            @impl(Config.root.getter)
            def getter(self) -> str:
                return "/tmp"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        warnings = [message for message in messages if message.rule_id == "R003"]
        assert len(warnings) == 1
        assert "config_root" in warnings[0].message

    def test_setter_uses_owner_type_name(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "config.py", """
            from mutobj import Declaration

            class Config(Declaration):
                root: str = "/"


            from . import _config_impl as _config_impl  # noqa: F401, E402
        """)
        write(pkg, "_config_impl.py", """
            from mutobj import impl

            from .config import Config


            @impl(Config.root.setter)
            def setter(self, value: str) -> None:
                ...
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r003 = [m for m in messages if m.rule_id == "R003"]
        assert any("setter" in m.message and "config_root" in m.message for m in r003)

    def test_init_uses_init_suffix(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "service.py", """
            from mutobj import Declaration

            class Service(Declaration):
                def __init__(self, value: int) -> None: ...


            from . import _service_impl as _service_impl  # noqa: F401, E402
        """)
        write(pkg, "_service_impl.py", """
            from mutobj import impl

            from .service import Service


            @impl(Service.__init__)
            def service_init(self, value: int) -> None:
                self.value = value
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        assert not [message for message in messages if message.rule_id == "R003"]

    def test_correct_name_passes(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "service.py", """
            from mutobj import Declaration

            class Service(Declaration):
                def run(self) -> str: ...


            from . import _service_impl as _service_impl  # noqa: F401, E402
        """)
        write(pkg, "_service_impl.py", """
            from mutobj import impl

            from .service import Service


            @impl(Service.run)
            def service_run(self) -> str:
                return "ok"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        assert not [m for m in messages if m.rule_id == "R003"]

    def test_underscore_prefix_with_correct_name_warns(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "service.py", """
            from mutobj import Declaration

            class Service(Declaration):
                def run(self) -> str: ...


            from . import _service_impl as _service_impl  # noqa: F401, E402
        """)
        write(pkg, "_service_impl.py", """
            from mutobj import impl

            from .service import Service


            @impl(Service.run)
            def _service_run(self) -> str:
                return "ok"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r003 = [m for m in messages if m.rule_id == "R003"]
        assert len(r003) == 1
        assert "不应使用 `_` 前缀" in r003[0].message

    def test_underscore_prefix_with_wrong_name_warns(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "service.py", """
            from mutobj import Declaration

            class Service(Declaration):
                def run(self) -> str: ...


            from . import _service_impl as _service_impl  # noqa: F401, E402
        """)
        write(pkg, "_service_impl.py", """
            from mutobj import impl

            from .service import Service


            @impl(Service.run)
            def _wrong_name(self) -> str:
                return "ok"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r003 = [m for m in messages if m.rule_id == "R003"]
        assert len(r003) == 1
        assert "不应使用 `_` 前缀，且应以" in r003[0].message
        assert "service_run" in r003[0].message

    def test_implementation_bridge_skipped(self, tmp_path: Path) -> None:
        """Implementation 子类的 bridge 函数应跳过 R003 命名检查。"""
        pkg = make_pkg(tmp_path)
        write(pkg, "impl_svc2.py", """
            from mutobj import Declaration

            class ImplSvc2(Declaration):
                def __init__(self) -> None: ...
                def run(self, value: int) -> str: ...
        """)
        write(pkg, "_impl_svc2_impl.py", """
            import mutobj
            from .impl_svc2 import ImplSvc2


            class ImplSvc2Impl(mutobj.Implementation[ImplSvc2]):
                def __init__(self) -> None: ...

                def run(self, value: int) -> str:
                    return str(value)
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r003 = [m for m in messages if m.rule_id == "R003"]
        assert not r003, f"Implementation bridge should be skipped, got: {[m.message for m in r003]}"
