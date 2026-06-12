"""Tests for @impl meta attachment APIs: impl_meta() / impl_meta_of()."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

import mutobj


# ===== 测试用 meta 类型（consumer 自定义形态，不强制基类） =====


class Stub:
    """marker：无字段的 stub 标记。"""


class Experimental:
    """marker：另一个无字段标记，验证多 meta 共存。"""


@dataclass
class Deprecated:
    since: str = ""
    reason: str = ""


# ===== 基础注册与查询 =====


class TestImplMetaRegistration:
    def test_no_meta_returns_empty_tuple(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> int: ...

        @mutobj.impl(Svc.run)
        def _run_impl(self: Svc) -> int:
            return 1

        assert mutobj.impl_meta(Svc.run) == ()

    def test_single_meta(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> int: ...

        @mutobj.impl(Svc.run, Stub())
        def _run_impl(self: Svc) -> int:
            raise NotImplementedError

        metas = mutobj.impl_meta(Svc.run)
        assert len(metas) == 1
        assert isinstance(metas[0], Stub)

    def test_multiple_metas_preserve_order(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> int: ...

        s, d = Stub(), Deprecated(since="0.8")

        @mutobj.impl(Svc.run, s, d)
        def _run_impl(self: Svc) -> int:
            return 1

        metas = mutobj.impl_meta(Svc.run)
        assert metas == (s, d)

    def test_meta_returns_tuple_type(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> int: ...

        @mutobj.impl(Svc.run, Stub())
        def _run_impl(self: Svc) -> int:
            return 1

        assert isinstance(mutobj.impl_meta(Svc.run), tuple)


class TestImplMetaOf:
    def test_typed_lookup_hit(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> int: ...

        @mutobj.impl(Svc.run, Stub(), Deprecated(since="0.8"))
        def _run_impl(self: Svc) -> int:
            return 1

        stub = mutobj.impl_meta_of(Svc.run, Stub)
        dep = mutobj.impl_meta_of(Svc.run, Deprecated)
        assert isinstance(stub, Stub)
        assert isinstance(dep, Deprecated)
        assert dep.since == "0.8"

    def test_typed_lookup_miss_returns_none(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> int: ...

        @mutobj.impl(Svc.run, Stub())
        def _run_impl(self: Svc) -> int:
            return 1

        assert mutobj.impl_meta_of(Svc.run, Deprecated) is None

    def test_typed_lookup_returns_first_match(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> int: ...

        first, second = Stub(), Stub()

        @mutobj.impl(Svc.run, first, second)
        def _run_impl(self: Svc) -> int:
            return 1

        assert mutobj.impl_meta_of(Svc.run, Stub) is first


# ===== 链顶语义：覆盖、卸载 =====


class TestImplMetaChainTopSemantics:
    def test_same_module_override_replaces_meta(self) -> None:
        """同模块再次注册（reload 场景）应替换 meta。"""
        class Svc(mutobj.Declaration):
            def run(self) -> int: ...

        @mutobj.impl(Svc.run, Stub())
        def _v1(self: Svc) -> int:
            return 1

        assert mutobj.impl_meta_of(Svc.run, Stub) is not None

        # 同模块同 target 再注册：模拟 reload
        @mutobj.impl(Svc.run, Experimental())
        def _v2(self: Svc) -> int:  # pyright: ignore[reportRedeclaration]
            return 2

        # 新 meta 替换旧 meta
        assert mutobj.impl_meta_of(Svc.run, Stub) is None
        assert mutobj.impl_meta_of(Svc.run, Experimental) is not None

    def test_same_module_override_with_empty_metas_clears(self) -> None:
        """同模块重注册时不传 meta，应清空原 meta。"""
        class Svc(mutobj.Declaration):
            def run(self) -> int: ...

        @mutobj.impl(Svc.run, Stub())
        def _v1(self: Svc) -> int:
            return 1

        @mutobj.impl(Svc.run)
        def _v2(self: Svc) -> int:  # pyright: ignore[reportRedeclaration]
            return 2

        assert mutobj.impl_meta(Svc.run) == ()

    def test_top_chain_meta_only(self) -> None:
        """chain 顶层覆盖时，meta 取链顶；下层 meta 不再可见。

        在 mutobj 单进程同模块场景下，构造多层 chain 需要不同 source_module。
        这里通过手工构造同 cls 多个 @impl 但不同 __module__ 来模拟。
        """
        class Svc(mutobj.Declaration):
            def run(self) -> int: ...

        @mutobj.impl(Svc.run, Stub())
        def _bottom(self: Svc) -> int:
            return 1

        def _top(self: Svc) -> int:
            return 2

        _top.__module__ = "synthetic_top_module"
        # 不带 meta 注册到链顶
        mutobj.impl(Svc.run)(_top)

        # chain 顶端是 _top（无 meta），链底的 Stub 不会被读到
        assert mutobj.impl_meta(Svc.run) == ()

    def test_unregister_clears_meta(self) -> None:
        """impl_unregister 应清除对应 meta。"""
        class Svc(mutobj.Declaration):
            def run(self) -> int: ...

        # 构造一个独立 module name 便于卸载
        def _impl_fn(self: Svc) -> int:
            return 1

        _impl_fn.__module__ = "test_impl_meta_synthetic_unreg"
        mutobj.impl(Svc.run, Stub())(_impl_fn)

        assert mutobj.impl_meta_of(Svc.run, Stub) is not None
        mutobj.impl_unregister("test_impl_meta_synthetic_unreg")
        # 卸载后链回到默认实现，meta 也应清空
        assert mutobj.impl_meta(Svc.run) == ()


# ===== delegate 透明转发 =====


class TestImplMetaDelegateTransparent:
    def test_subclass_no_override_inherits_parent_meta(self) -> None:
        """子类未 override 时，链顶是 delegate，应透明转发到父类链顶取 meta。"""
        class Base(mutobj.Declaration):
            def run(self) -> int: ...

        @mutobj.impl(Base.run, Stub())
        def _base_stub(self: Base) -> int:
            raise NotImplementedError

        class Child(Base):
            pass

        # Child.run 自身链顶是 delegate，应透明拿到 Base 的 Stub
        assert mutobj.impl_meta_of(Child.run, Stub) is not None
        assert mutobj.impl_meta_of(Base.run, Stub) is not None

    def test_subclass_with_own_def_does_not_inherit_meta(self) -> None:
        """子类自己在类体写了 def，链顶是用户 def 而非 delegate，不应继承父类 meta。"""
        class Base(mutobj.Declaration):
            def run(self) -> int: ...

        @mutobj.impl(Base.run, Stub())
        def _base_stub(self: Base) -> int:
            raise NotImplementedError

        class Child(Base):
            def run(self) -> int:
                return 42

        # Child 自己有 def，未挂 meta
        assert mutobj.impl_meta_of(Child.run, Stub) is None
        # Base 自己仍然有
        assert mutobj.impl_meta_of(Base.run, Stub) is not None

    def test_subclass_with_own_impl_register_does_not_inherit_meta(self) -> None:
        """子类通过 @impl 注册（未带 meta）覆盖父类链顶，meta 不应继承。"""
        class Base(mutobj.Declaration):
            def run(self) -> int: ...

        @mutobj.impl(Base.run, Stub())
        def _base_stub(self: Base) -> int:
            raise NotImplementedError

        class Child(Base):
            pass

        @mutobj.impl(Child.run)
        def _child_impl(self: Child) -> int:
            return 7

        assert mutobj.impl_meta_of(Child.run, Stub) is None

    def test_deep_inheritance_delegate_chain(self) -> None:
        """多层 delegate 透明转发到最底层声明者的链顶。"""
        class A(mutobj.Declaration):
            def run(self) -> int: ...

        @mutobj.impl(A.run, Stub())
        def _a_stub(self: A) -> int:
            raise NotImplementedError

        class B(A): pass
        class C(B): pass

        assert mutobj.impl_meta_of(C.run, Stub) is not None


# ===== 边界 =====


class TestImplMetaEdgeCases:
    def test_no_chain_returns_empty(self) -> None:
        """方法未被 @impl 注册过、且无类体 def 时（实际上 Declaration 会建 chain），
        非 mutobj 方法应抛错（由 _resolve_impl_key 行为决定）。
        这里测纯 Declaration 类体 def、无 @impl 的场景。"""
        class Svc(mutobj.Declaration):
            def run(self) -> int: ...

        # 类体 def 会进 chain 但无 meta
        assert mutobj.impl_meta(Svc.run) == ()
        assert mutobj.impl_meta_of(Svc.run, Stub) is None

    def test_non_declaration_method_raises(self) -> None:
        """非 Declaration 子类的方法应被 _resolve_impl_key 拒绝。"""
        class Plain:
            def foo(self) -> None: ...

        with pytest.raises((TypeError, ValueError, AttributeError)):
            mutobj.impl_meta(Plain.foo)


# ===== 与 impl_chain 的解耦：meta 不进 impl_chain_registry 返回值 =====


class TestImplMetaDoesNotPolluteImplChain:
    def testimpl_chain_tuple_shape_unchanged(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> int: ...

        @mutobj.impl(Svc.run, Stub(), Deprecated(since="1.0"))
        def _run_impl(self: Svc) -> int:
            return 1

        chain = mutobj.impl_chain(Svc.run)
        assert len(chain) > 0
