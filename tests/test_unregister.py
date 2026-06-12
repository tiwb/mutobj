# L2 契约测试：unregister 后 impl 链回退到 __default__
"""Tests for impl chain tracking and impl_unregister."""

import pytest
import mutobj
from mutobj import impl_unregister


class TestImplSourceTracking:

    def test_impl_records_source_in_chain(self):
        class Svc(mutobj.Declaration):
            def run(self) -> str: ...

        @mutobj.impl(Svc.run)
        def run(self: Svc) -> str:
            return "ok"

        chain = mutobj.impl_chain(Svc.run)
        # 链中应有来源为当前模块的条目
        modules = [entry.source_module for entry in chain if entry.source_module != "__default__"]
        assert __name__ in modules

    def test_impl_override_updates_chain(self):
        class Svc2(mutobj.Declaration):
            def run(self) -> str: ...

        @mutobj.impl(Svc2.run)
        def run_v1(self) -> str:
            return "v1"

        @mutobj.impl(Svc2.run)
        def run_v2(self) -> str:
            return "v2"

        chain = mutobj.impl_chain(Svc2.run)
        # 同模块就地替换，链中应有 __default__ + 当前模块条目
        modules = [entry.source_module for entry in chain]
        assert "__default__" in modules
        assert __name__ in modules

class TestUnregisterModuleImpls:

    def test_unregister_restores_default_method(self):
        class A(mutobj.Declaration):
            def do_it(self) -> str: ...

        @mutobj.impl(A.do_it)
        def do_it(self) -> str:
            return "done"

        a = A()
        assert a.do_it() == "done"

        count = impl_unregister(__name__)
        assert count >= 1

        # 卸载后恢复默认实现（方法体为 ...，隐式返回 None）
        result = a.do_it()
        assert result is None

    def test_unregister_restores_default_classmethod(self):
        class B(mutobj.Declaration):
            @classmethod
            def create(cls) -> str: ...

        @mutobj.impl(B.create)
        def create(cls) -> str:
            return "created"

        assert B.create() == "created"

        impl_unregister(__name__)

        # 卸载后恢复默认实现
        result = B.create()
        assert result is None

    def test_unregister_restores_default_staticmethod(self):
        class C(mutobj.Declaration):
            @staticmethod
            def helper() -> str: ...

        @mutobj.impl(C.helper)
        def helper() -> str:
            return "helped"

        assert C.helper() == "helped"

        impl_unregister(__name__)

        # 卸载后恢复默认实现
        result = C.helper()
        assert result is None

    def test_unregister_restores_default_property_getter(self):
        class D(mutobj.Declaration):
            @property
            def value(self) -> int: ...

        @mutobj.impl(D.value.getter)
        def get_value(self) -> int:
            return 42

        d = D()
        assert d.value == 42

        impl_unregister(__name__)

        # 卸载后恢复默认 getter（方法体为 ...，隐式返回 None）
        result = d.value
        assert result is None

    def test_unregister_returns_count(self):
        class E(mutobj.Declaration):
            def m1(self) -> str: ...
            def m2(self) -> str: ...

        @mutobj.impl(E.m1)
        def m1(self) -> str:
            return "1"

        @mutobj.impl(E.m2)
        def m2(self) -> str:
            return "2"

        count = impl_unregister(__name__)
        assert count >= 2

    def test_unregister_only_removes_matching_module(self):
        class F(mutobj.Declaration):
            def alpha(self) -> str: ...
            def beta(self) -> str: ...

        # Register alpha from "unreg_mod_a"
        def alpha_impl(self) -> str:
            return "a"
        alpha_impl.__module__ = "unreg_mod_a"
        mutobj.impl(F.alpha)(alpha_impl)

        # Register beta from "unreg_mod_b"
        def beta_impl(self) -> str:
            return "b"
        beta_impl.__module__ = "unreg_mod_b"
        mutobj.impl(F.beta)(beta_impl)

        f = F()
        assert f.alpha() == "a"
        assert f.beta() == "b"

        # Unregister only unreg_mod_a
        count = impl_unregister("unreg_mod_a")
        assert count == 1

        # alpha 恢复默认实现
        assert f.alpha() is None
        # beta should still work
        assert f.beta() == "b"

    def test_unregister_removes_from_chain(self):
        class G(mutobj.Declaration):
            def work(self) -> str: ...

        @mutobj.impl(G.work)
        def work(self) -> str:
            return "working"

        chain = mutobj.impl_chain(G.work)
        assert any(entry.source_module == __name__ for entry in chain)

        impl_unregister(__name__)

        # 外部模块条目应被移除，仅剩 __default__
        chain = mutobj.impl_chain(G.work)
        assert all(entry.source_module == "__default__" for entry in chain)

    def test_unregister_nonexistent_module_is_noop(self):
        count = impl_unregister("nonexistent.module.xyz")
        assert count == 0

    def test_unregister_chain_entry_persists_with_default(self):
        class H(mutobj.Declaration):
            def proc(self) -> str: ...

        @mutobj.impl(H.proc)
        def proc(self) -> str:
            return "processed"

        chain = mutobj.impl_chain(H.proc)
        assert len(chain) > 0

        impl_unregister(__name__)

        # 链仍存在（含 __default__ 条目）
        chain = mutobj.impl_chain(H.proc)
        assert len(chain) == 1
        assert chain[0].source_module == "__default__"


class TestStubMethods:
    """卸载 __default__ 后，桩方法抛出 NotImplementedError"""

    def test_stub_method_raises_not_implemented(self):
        """普通方法的桩抛出 NotImplementedError"""
        class S(mutobj.Declaration):
            def work(self) -> str: ...

        obj = S()
        mutobj.impl_unregister("__default__")

        with pytest.raises(NotImplementedError, match="but not implemented"):
            obj.work()

    def test_stub_classmethod_raises_not_implemented(self):
        """classmethod 的桩抛出 NotImplementedError"""
        class S(mutobj.Declaration):
            @classmethod
            def make(cls) -> "S": ...

        mutobj.impl_unregister("__default__")

        with pytest.raises(NotImplementedError, match="but not implemented"):
            S.make()

    def test_stub_staticmethod_raises_not_implemented(self):
        """staticmethod 的桩抛出 NotImplementedError"""
        class S(mutobj.Declaration):
            @staticmethod
            def util(x: int) -> int: ...

        mutobj.impl_unregister("__default__")

        with pytest.raises(NotImplementedError, match="but not implemented"):
            S.util(1)

    def test_impl_call_super_at_bottom_raises(self):
        """链底调用 impl_call_super 时框架抛出 NotImplementedError（行 410 覆盖）"""
        class S(mutobj.Declaration):
            def run(self) -> str: ...

        obj = S()
        mutobj.impl_unregister("__default__")

        @mutobj.impl(S.run)
        def run(self) -> str:
            return mutobj.impl_call_super(S.run, self)

        with pytest.raises(NotImplementedError, match="No super implementation"):
            obj.run()
