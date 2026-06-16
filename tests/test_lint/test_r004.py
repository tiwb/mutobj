from __future__ import annotations

from pathlib import Path

from mutobj.lint import check

from ._helpers import import_temp_pkg, make_pkg, write


class TestR004Runtime:
    def test_signature_mismatch_reports(self, tmp_path: Path) -> None:
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
            def service_run(self, value: str) -> int:
                return 1
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        assert any(message.rule_id == "R004" and "类型不匹配" in message.message for message in messages)

    def test_async_allowed_suppresses_async_shape_error(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "service.py", """
            from mutobj import Declaration

            class Service(Declaration):
                def run(self) -> str: ...


            from . import _service_impl as _service_impl  # noqa: F401, E402
        """)
        write(pkg, "_service_impl.py", """
            from mutobj import impl
            from mutobj.lint import AsyncAllowed

            from .service import Service


            @impl(Service.run, AsyncAllowed())
            async def service_run(self) -> str:
                return "ok"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        assert not [message for message in messages if message.rule_id == "R004"]

    def test_signature_override_suppresses_all_r004(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "service.py", """
            from mutobj import Declaration

            class Service(Declaration):
                def run(self, value: int) -> str: ...


            from . import _service_impl as _service_impl  # noqa: F401, E402
        """)
        write(pkg, "_service_impl.py", """
            from mutobj import impl
            from mutobj.lint import SignatureOverride

            from .service import Service


            @impl(Service.run, SignatureOverride("legacy shim"))
            def service_run(self, value: str) -> int:
                return 1
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        assert not [message for message in messages if message.rule_id == "R004"]

    def test_param_count_mismatch(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "service.py", """
            from mutobj import Declaration

            class Service(Declaration):
                def run(self, x: int) -> str: ...


            from . import _service_impl as _service_impl  # noqa: F401, E402
        """)
        write(pkg, "_service_impl.py", """
            from mutobj import impl

            from .service import Service


            @impl(Service.run)
            def service_run(self, x: int, extra: str) -> str:
                return extra
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r004 = [m for m in messages if m.rule_id == "R004"]
        assert len(r004) == 1
        assert "参数数量" in r004[0].message

    def test_param_name_mismatch(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "service.py", """
            from mutobj import Declaration

            class Service(Declaration):
                def run(self, x: int) -> str: ...


            from . import _service_impl as _service_impl  # noqa: F401, E402
        """)
        write(pkg, "_service_impl.py", """
            from mutobj import impl

            from .service import Service


            @impl(Service.run)
            def service_run(self, y: int) -> str:
                return str(y)
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r004 = [m for m in messages if m.rule_id == "R004"]
        assert len(r004) == 1
        assert "参数名与声明不一致" in r004[0].message

    def test_return_type_mismatch(self, tmp_path: Path) -> None:
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
            def service_run(self) -> int:
                return 1
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r004 = [m for m in messages if m.rule_id == "R004"]
        assert len(r004) == 1
        assert "返回类型" in r004[0].message

    def test_descriptor_setter_type_mismatch(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "config.py", """
            from mutobj import Declaration

            class Config(Declaration):
                threshold: int = 0


            from . import _config_impl as _config_impl  # noqa: F401, E402
        """)
        write(pkg, "_config_impl.py", """
            from mutobj import impl

            from .config import Config


            @impl(Config.threshold.setter)
            def config_threshold(self, value: str) -> None:
                ...
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r004 = [m for m in messages if m.rule_id == "R004"]
        assert len(r004) == 1
        assert "值参数类型不匹配" in r004[0].message

    def test_staticmethod_param_type_checked(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "service.py", """
            from mutobj import Declaration

            class Service(Declaration):
                @staticmethod
                def create(value: int) -> "Service": ...


            from . import _service_impl as _service_impl  # noqa: F401, E402
        """)
        write(pkg, "_service_impl.py", """
            from mutobj import impl

            from .service import Service


            @impl(Service.create)
            def service_create(value: str) -> "Service":
                ...
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r004 = [m for m in messages if m.rule_id == "R004"]
        assert len(r004) == 1
        assert "类型不匹配" in r004[0].message

    def test_default_value_mismatch(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "service.py", """
            from mutobj import Declaration

            class Service(Declaration):
                def run(self, value: int = 0) -> str: ...


            from . import _service_impl as _service_impl  # noqa: F401, E402
        """)
        write(pkg, "_service_impl.py", """
            from mutobj import impl

            from .service import Service


            @impl(Service.run)
            def service_run(self, value: int = 1) -> str:
                return str(value)
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r004 = [m for m in messages if m.rule_id == "R004"]
        assert len(r004) == 1
        assert "默认值" in r004[0].message


class TestR004Implementation:
    """Implementation 子类的 R004 签名检查（应取 impl 类上真实方法而非 bridge）。"""

    def test_method_signature_matches_passes(self, tmp_path: Path) -> None:
        """Implementation 子类方法签名与声明一致时不应报 R004。"""
        pkg = make_pkg(tmp_path)
        write(pkg, "impl_svc.py", """
            from mutobj import Declaration

            class ImplSvc(Declaration):
                def __init__(self) -> None: ...
                def run(self, value: int) -> str: ...
        """)
        write(pkg, "_impl_svc_impl.py", """
            import mutobj
            from .impl_svc import ImplSvc


            class ImplSvcImpl(mutobj.Implementation[ImplSvc]):
                def __init__(self) -> None: ...

                def run(self, value: int) -> str:
                    return str(value)
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r004 = [m for m in messages if m.rule_id == "R004"]
        assert not r004, f"Expected no R004, got: {[m.message for m in r004]}"

    def test_param_count_mismatch_reports(self, tmp_path: Path) -> None:
        """Implementation 子类方法参数数量不一致时报 R004。"""
        pkg = make_pkg(tmp_path)
        write(pkg, "impl_svc.py", """
            from mutobj import Declaration

            class ImplSvc(Declaration):
                def __init__(self) -> None: ...
                def run(self, value: int) -> str: ...
        """)
        write(pkg, "_impl_svc_impl.py", """
            import mutobj
            from .impl_svc import ImplSvc


            class ImplSvcImpl(mutobj.Implementation[ImplSvc]):
                def __init__(self) -> None: ...

                def run(self, value: int, extra: str) -> str:
                    return extra
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r004 = [m for m in messages if m.rule_id == "R004"]
        assert len(r004) == 1
        assert "参数数量" in r004[0].message

    def test_param_name_mismatch_reports(self, tmp_path: Path) -> None:
        """Implementation 子类方法参数名不一致时报 R004。"""
        pkg = make_pkg(tmp_path)
        write(pkg, "impl_svc.py", """
            from mutobj import Declaration

            class ImplSvc(Declaration):
                def __init__(self) -> None: ...
                def run(self, value: int) -> str: ...
        """)
        write(pkg, "_impl_svc_impl.py", """
            import mutobj
            from .impl_svc import ImplSvc


            class ImplSvcImpl(mutobj.Implementation[ImplSvc]):
                def __init__(self) -> None: ...

                def run(self, val: int) -> str:
                    return str(val)
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r004 = [m for m in messages if m.rule_id == "R004"]
        assert len(r004) == 1
        assert "参数名与声明不一致" in r004[0].message

    def test_return_type_mismatch_reports(self, tmp_path: Path) -> None:
        """Implementation 子类方法返回类型不一致时报 R004。"""
        pkg = make_pkg(tmp_path)
        write(pkg, "impl_svc.py", """
            from mutobj import Declaration

            class ImplSvc(Declaration):
                def __init__(self) -> None: ...
                def run(self, value: int) -> str: ...
        """)
        write(pkg, "_impl_svc_impl.py", """
            import mutobj
            from .impl_svc import ImplSvc


            class ImplSvcImpl(mutobj.Implementation[ImplSvc]):
                def __init__(self) -> None: ...

                def run(self, value: int) -> int:
                    return value
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r004 = [m for m in messages if m.rule_id == "R004"]
        assert len(r004) == 1
        assert "返回类型" in r004[0].message

    def test_async_mismatch_reports(self, tmp_path: Path) -> None:
        """Implementation 子类方法 async/sync 与声明不一致时报 R004。"""
        pkg = make_pkg(tmp_path)
        write(pkg, "impl_svc.py", """
            from mutobj import Declaration

            class ImplSvc(Declaration):
                def __init__(self) -> None: ...
                def run(self, value: int) -> str: ...
        """)
        write(pkg, "_impl_svc_impl.py", """
            import mutobj
            from .impl_svc import ImplSvc


            class ImplSvcImpl(mutobj.Implementation[ImplSvc]):
                def __init__(self) -> None: ...

                async def run(self, value: int) -> str:
                    return str(value)
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r004 = [m for m in messages if m.rule_id == "R004"]
        assert len(r004) == 1
        assert "async/sync" in r004[0].message

    def test_property_getter_signature_matches_passes(self, tmp_path: Path) -> None:
        """Implementation 子类 @property getter 签名与声明一致时不报 R004。"""
        pkg = make_pkg(tmp_path)
        write(pkg, "settings.py", """
            from mutobj import Declaration

            class Settings(Declaration):
                @property
                def threshold(self) -> int: ...


            from . import _settings_impl as _settings_impl  # noqa: F401, E402
        """)
        write(pkg, "_settings_impl.py", """
            import mutobj
            from .settings import Settings


            class SettingsImpl(mutobj.Implementation[Settings]):
                @property
                def threshold(self) -> int:
                    return 42
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r004 = [m for m in messages if m.rule_id == "R004"]
        assert not r004, f"Expected no R004, got: {[m.message for m in r004]}"

    def test_property_getter_return_type_mismatch_reports(self, tmp_path: Path) -> None:
        """Implementation 子类 @property getter 返回类型与声明不一致时报 R004。"""
        pkg = make_pkg(tmp_path)
        write(pkg, "settings.py", """
            from mutobj import Declaration

            class Settings(Declaration):
                @property
                def threshold(self) -> int: ...


            from . import _settings_impl as _settings_impl  # noqa: F401, E402
        """)
        write(pkg, "_settings_impl.py", """
            import mutobj
            from .settings import Settings


            class SettingsImpl(mutobj.Implementation[Settings]):
                @property
                def threshold(self) -> str:
                    return "high"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r004 = [m for m in messages if m.rule_id == "R004"]
        assert len(r004) == 1
        assert "返回类型" in r004[0].message


class TestR004FutureAnnotations:
    """PEP 563 (from __future__ import annotations) 嵌套引号处理。

    当声明侧同时启用 PEP 563 和引号 forward reference（如 "str | Foo"），
    PEP 563 会将注解存为 "'str | Foo'"（字符串字面量内嵌引号）。
    lint 应能正确解析并比对 impl 侧的非引号注解。
    """

    def test_quoted_union_annotation_matches(self, tmp_path: Path) -> None:
        """声明侧 'from __future__' + "str | Foo" 应匹配 impl 的 str | Foo。"""
        pkg = make_pkg(tmp_path)
        write(pkg, "types.py", "class Foo: pass\n")
        write(pkg, "service.py", """
            from __future__ import annotations

            from mutobj import Declaration

            class Service(Declaration):
                def run(self, value: "str | Foo") -> None: ...

            from . import _service_impl as _service_impl  # noqa: F401, E402
        """)
        write(pkg, "_service_impl.py", """
            from __future__ import annotations

            from mutobj import impl

            from .types import Foo
            from .service import Service

            @impl(Service.run)
            def service_run(self, value: str | Foo) -> None:
                pass
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r004 = [m for m in messages if m.rule_id == "R004"]
        assert not r004, f"Expected no R004, got: {[m.message for m in r004]}"

    def test_quoted_callable_annotation_matches(self, tmp_path: Path) -> None:
        """声明侧 'from __future__' + Callable[..., "Foo"] 应匹配 impl 的 Callable[..., Foo]。"""
        pkg = make_pkg(tmp_path)
        write(pkg, "types.py", "class Foo: pass\n")
        write(pkg, "service.py", """
            from __future__ import annotations
            from collections.abc import Callable

            from mutobj import Declaration

            class Service(Declaration):
                def run(self, fn: Callable[..., "Foo"]) -> None: ...

            from . import _service_impl as _service_impl  # noqa: F401, E402
        """)
        write(pkg, "_service_impl.py", """
            from __future__ import annotations
            from collections.abc import Callable

            from mutobj import impl

            from .types import Foo
            from .service import Service

            @impl(Service.run)
            def service_run(self, fn: Callable[..., Foo]) -> None:
                pass
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r004 = [m for m in messages if m.rule_id == "R004"]
        assert not r004, f"Expected no R004, got: {[m.message for m in r004]}"

    def test_quoted_return_annotation_matches(self, tmp_path: Path) -> None:
        """声明侧 'from __future__' + -> "Foo" 应匹配 impl 的 -> Foo。"""
        pkg = make_pkg(tmp_path)
        write(pkg, "types.py", "class Foo: pass\n")
        write(pkg, "service.py", """
            from __future__ import annotations

            from mutobj import Declaration

            class Service(Declaration):
                def run(self) -> "Foo": ...

            from . import _service_impl as _service_impl  # noqa: F401, E402
        """)
        write(pkg, "_service_impl.py", """
            from __future__ import annotations

            from mutobj import impl

            from .types import Foo
            from .service import Service

            @impl(Service.run)
            def service_run(self) -> Foo:
                return Foo()
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r004 = [m for m in messages if m.rule_id == "R004"]
        assert not r004, f"Expected no R004, got: {[m.message for m in r004]}"

    def test_future_annotations_without_quoting_matches(self, tmp_path: Path) -> None:
        """声明侧和 impl 都用 PEP 563 且无多余引号——应匹配（对照组）。"""
        pkg = make_pkg(tmp_path)
        write(pkg, "types.py", "class Foo: pass\n")
        write(pkg, "service.py", """
            from __future__ import annotations

            from mutobj import Declaration

            class Service(Declaration):
                def run(self, value: str | Foo) -> None: ...

            from . import _service_impl as _service_impl  # noqa: F401, E402
        """)
        write(pkg, "_service_impl.py", """
            from __future__ import annotations

            from mutobj import impl

            from .types import Foo
            from .service import Service

            @impl(Service.run)
            def service_run(self, value: str | Foo) -> None:
                pass
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r004 = [m for m in messages if m.rule_id == "R004"]
        assert not r004, f"Expected no R004, got: {[m.message for m in r004]}"

    def test_future_annotations_genuine_mismatch_still_reports(self, tmp_path: Path) -> None:
        """声明侧 'from __future__' + "str | Foo" vs impl 的 int——应报告 R004。"""
        pkg = make_pkg(tmp_path)
        write(pkg, "types.py", "class Foo: pass\n")
        write(pkg, "service.py", """
            from __future__ import annotations

            from mutobj import Declaration

            class Service(Declaration):
                def run(self, value: "str | Foo") -> None: ...

            from . import _service_impl as _service_impl  # noqa: F401, E402
        """)
        write(pkg, "_service_impl.py", """
            from __future__ import annotations

            from mutobj import impl

            from .service import Service

            @impl(Service.run)
            def service_run(self, value: int) -> None:
                pass
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r004 = [m for m in messages if m.rule_id == "R004"]
        assert len(r004) == 1
        assert "类型不匹配" in r004[0].message
