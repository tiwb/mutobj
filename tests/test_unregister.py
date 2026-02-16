"""Tests for impl source tracking and unregister_module_impls."""

import pytest
import mutobj
from mutobj.core import (
    _impl_sources,
    _method_registry,
    _property_registry,
    _DECLARED_METHODS,
    unregister_module_impls,
)


class TestImplSourceTracking:

    def test_impl_records_source_module(self):
        class Svc(mutobj.Declaration):
            def run(self) -> str: ...

        @mutobj.impl(Svc.run)
        def run(self: Svc) -> str:
            return "ok"

        assert (Svc, "run") in _impl_sources
        assert _impl_sources[(Svc, "run")] == __name__

    def test_impl_override_updates_source(self):
        class Svc2(mutobj.Declaration):
            def run(self) -> str: ...

        @mutobj.impl(Svc2.run)
        def run_v1(self) -> str:
            return "v1"

        old_source = _impl_sources[(Svc2, "run")]

        @mutobj.impl(Svc2.run, override=True)
        def run_v2(self) -> str:
            return "v2"

        assert _impl_sources[(Svc2, "run")] == old_source  # same test module


class TestUnregisterModuleImpls:

    def test_unregister_restores_stub_method(self):
        class A(mutobj.Declaration):
            def do_it(self) -> str: ...

        @mutobj.impl(A.do_it)
        def do_it(self) -> str:
            return "done"

        a = A()
        assert a.do_it() == "done"

        source_module = _impl_sources[(A, "do_it")]
        count = unregister_module_impls(source_module)
        assert count >= 1

        with pytest.raises(NotImplementedError):
            a.do_it()

    def test_unregister_restores_stub_classmethod(self):
        class B(mutobj.Declaration):
            @classmethod
            def create(cls) -> str: ...

        @mutobj.impl(B.create)
        def create(cls) -> str:
            return "created"

        assert B.create() == "created"

        source_module = _impl_sources[(B, "create")]
        unregister_module_impls(source_module)

        with pytest.raises(NotImplementedError):
            B.create()

    def test_unregister_restores_stub_staticmethod(self):
        class C(mutobj.Declaration):
            @staticmethod
            def helper() -> str: ...

        @mutobj.impl(C.helper)
        def helper() -> str:
            return "helped"

        assert C.helper() == "helped"

        source_module = _impl_sources[(C, "helper")]
        unregister_module_impls(source_module)

        with pytest.raises(NotImplementedError):
            C.helper()

    def test_unregister_restores_property_getter(self):
        class D(mutobj.Declaration):
            @property
            def value(self) -> int: ...

        @mutobj.impl(D.value.getter)
        def get_value(self) -> int:
            return 42

        d = D()
        assert d.value == 42

        source_module = _impl_sources[(D, "value.getter")]
        unregister_module_impls(source_module)

        with pytest.raises(NotImplementedError):
            _ = d.value

    def test_unregister_returns_count(self):
        class E(mutobj.Declaration):
            def m1(self) -> str: ...
            def m2(self) -> str: ...

        # Use a unique fake module name to isolate
        @mutobj.impl(E.m1)
        def m1(self) -> str:
            return "1"

        @mutobj.impl(E.m2)
        def m2(self) -> str:
            return "2"

        source_module = _impl_sources[(E, "m1")]
        count = unregister_module_impls(source_module)
        assert count >= 2

    def test_unregister_only_removes_matching_module(self):
        class F(mutobj.Declaration):
            def alpha(self) -> str: ...
            def beta(self) -> str: ...

        # Register alpha from "module_a"
        def alpha_impl(self) -> str:
            return "a"
        alpha_impl.__module__ = "module_a"
        mutobj.impl(F.alpha)(alpha_impl)

        # Register beta from "module_b"
        def beta_impl(self) -> str:
            return "b"
        beta_impl.__module__ = "module_b"
        mutobj.impl(F.beta)(beta_impl)

        f = F()
        assert f.alpha() == "a"
        assert f.beta() == "b"

        # Unregister only module_a
        count = unregister_module_impls("module_a")
        assert count == 1

        with pytest.raises(NotImplementedError):
            f.alpha()
        # beta should still work
        assert f.beta() == "b"

    def test_unregister_removes_from_method_registry(self):
        class G(mutobj.Declaration):
            def work(self) -> str: ...

        @mutobj.impl(G.work)
        def work(self) -> str:
            return "working"

        assert "work" in _method_registry.get(G, {})

        source_module = _impl_sources[(G, "work")]
        unregister_module_impls(source_module)

        assert "work" not in _method_registry.get(G, {})

    def test_unregister_nonexistent_module_is_noop(self):
        count = unregister_module_impls("nonexistent.module.xyz")
        assert count == 0

    def test_unregister_removes_from_impl_sources(self):
        class H(mutobj.Declaration):
            def proc(self) -> str: ...

        @mutobj.impl(H.proc)
        def proc(self) -> str:
            return "processed"

        assert (H, "proc") in _impl_sources

        source_module = _impl_sources[(H, "proc")]
        unregister_module_impls(source_module)

        assert (H, "proc") not in _impl_sources
