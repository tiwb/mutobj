"""Tests for mutobj impl introspection and descriptor metadata APIs."""

from __future__ import annotations

import warnings

import pytest

import mutobj


# impl_has 在 0.9 中已弃用，本文件仍保留其语义回归用例。
# 在本模块全局忽略 DeprecationWarning，使测试表达聊务不被警告淹没。
pytestmark = pytest.mark.filterwarnings(
    "ignore:mutobj.impl_has\\(\\) is deprecated:DeprecationWarning"
)


class TestImplHas:
    """impl_has 已弃用，语义等同于 impl_has_override。

    该类原本预期“有默认实现即为 True”，现已翻转为“仅 @impl 注册才为 True”。
    """

    def test_ellipsis_body_no_override(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> None: ...

        assert mutobj.impl_has(Svc.run) is False
        assert mutobj.impl_has_override(Svc.run) is False

    def test_pass_body_no_override(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> None:
                pass

        assert mutobj.impl_has(Svc.run) is False
        assert mutobj.impl_has_override(Svc.run) is False

    def test_explicit_notimplemented_no_override(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> None:
                raise NotImplementedError

        assert mutobj.impl_has(Svc.run) is False
        assert mutobj.impl_has_override(Svc.run) is False

    def test_real_default_body_no_override(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> int:
                return 1

        # 类体直接 def 不算 override（新语义）。
        assert mutobj.impl_has(Svc.run) is False
        assert mutobj.impl_has_override(Svc.run) is False

    def test_impl_override_sets_override_flag(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> None: ...

        @mutobj.impl(Svc.run)
        def run(self) -> int:
            return 7

        assert mutobj.impl_has(Svc.run) is True
        assert mutobj.impl_has_override(Svc.run) is True

    def test_inherited_delegate_from_unimplemented_base_no_override(self) -> None:
        class Base(mutobj.Declaration):
            def run(self) -> None:
                raise NotImplementedError

        class Child(Base):
            pass

        assert mutobj.impl_has(Child.run) is False
        assert mutobj.impl_has_override(Child.run) is False

    def test_inherited_delegate_from_real_base_no_override(self) -> None:
        class Base(mutobj.Declaration):
            def run(self) -> str:
                return "ok"

        class Child(Base):
            pass

        # 父类有 def 不等于“子类有 override”。
        assert mutobj.impl_has(Child.run) is False
        assert mutobj.impl_has_override(Child.run) is False

    def test_impl_has_emits_deprecation_warning(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> None: ...

        with warnings.catch_warnings(record=True) as records:
            warnings.simplefilter("always")
            mutobj.impl_has(Svc.run)
        assert any(
            issubclass(r.category, DeprecationWarning) and "impl_has" in str(r.message)
            for r in records
        )


class TestImplIsOwnAndInherited:
    """新增结构原语：impl_is_own / impl_is_inherited。"""

    def test_class_body_def_is_own(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> int:
                return 1

        assert mutobj.impl_is_own(Svc.run) is True
        assert mutobj.impl_is_inherited(Svc.run) is False

    def test_ellipsis_stub_is_own(self) -> None:
        # 类体 def 不论函数体是什么，都是 own。
        class Svc(mutobj.Declaration):
            def run(self) -> None: ...

        assert mutobj.impl_is_own(Svc.run) is True
        assert mutobj.impl_is_inherited(Svc.run) is False

    def test_child_without_redeclaration_is_inherited(self) -> None:
        class Base(mutobj.Declaration):
            def run(self) -> str:
                return "ok"

        class Child(Base):
            pass

        # Base 是 own; Child 为框架生成 delegate，为 inherited。
        assert mutobj.impl_is_own(Base.run) is True
        assert mutobj.impl_is_inherited(Base.run) is False
        assert mutobj.impl_is_own(Child.run) is False
        assert mutobj.impl_is_inherited(Child.run) is True

    def test_child_with_redeclaration_is_own(self) -> None:
        class Base(mutobj.Declaration):
            def run(self) -> str:
                return "base"

        class Child(Base):
            def run(self) -> str:  # 子类类体重新声明
                return "child"

        assert mutobj.impl_is_own(Child.run) is True
        assert mutobj.impl_is_inherited(Child.run) is False

    def test_impl_registered_does_not_change_chain_zero(self) -> None:
        """@impl 追加在链顶，不改变 chain[0]。"""
        class Svc(mutobj.Declaration):
            def run(self) -> None: ...

        @mutobj.impl(Svc.run)
        def _override(self) -> int:
            return 7

        # chain[0] 仍是用户类体里的 def
        assert mutobj.impl_is_own(Svc.run) is True
        assert mutobj.impl_is_inherited(Svc.run) is False
        assert mutobj.impl_has_override(Svc.run) is True

    def test_impl_on_child_keeps_inherited_marker(self) -> None:
        """子类不重新声明但被 @impl 覆盖，chain[0] 仍是 delegate，仍为 inherited。"""
        class Base(mutobj.Declaration):
            def run(self) -> str:
                return "base"

        class Child(Base):
            pass

        @mutobj.impl(Child.run)
        def _override(self) -> str:
            return "child-impl"

        assert mutobj.impl_is_own(Child.run) is False
        assert mutobj.impl_is_inherited(Child.run) is True
        assert mutobj.impl_has_override(Child.run) is True

    def test_no_chain_returns_false_on_both(self) -> None:
        """没有链的 method 两个 API 都返回 False（互斥仅在 chain 存在时成立）。

        Declaration 体系下很难从外部构造「有 token 但无 chain」场景（_resolve_impl_key 会报错），
        本用例作为占位说明意图。
        """
        pass


class TestImplChain:

    def testimpl_chain_returns_copy(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> int:
                return 1

        chain = mutobj.impl_chain(Svc.run)
        assert len(chain) == 1
        chain.clear()
        assert len(mutobj.impl_chain(Svc.run)) == 1


class TestImplCallSuperAlias:

    def test_impl_call_super_alias_works(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self, x: int) -> int:
                return x + 1

        @mutobj.impl(Svc.run)
        def run(self, x: int) -> int:
            return mutobj.impl_call_super(Svc.run, self, x) * 10

        assert Svc().run(3) == 40

    def test_call_super_impl_warns_and_delegates(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self, x: int) -> int:
                return x + 1

        @mutobj.impl(Svc.run)
        def run(self, x: int) -> int:
            with warnings.catch_warnings(record=True) as records:
                warnings.simplefilter("always")
                result = mutobj.call_super_impl(Svc.run, self, x)
            assert result == 4
            assert any(issubclass(r.category, DeprecationWarning) for r in records)
            return result * 10

        assert Svc().run(3) == 40


class TestAttributeDescriptorDefaults:

    def test_get_default_returns_scalar_default(self) -> None:
        class Item(mutobj.Declaration):
            count: int = 3

        assert Item.count.get_default() == 3
        assert Item.count.make_default() == 3

    def test_get_default_returns_factory_and_make_default_executes_it(self) -> None:
        class Item(mutobj.Declaration):
            entries: list[int] = mutobj.field(default_factory=lambda: [1, 2, 3])

        factory = Item.entries.get_default()
        assert callable(factory)
        assert factory() == [1, 2, 3]
        made = Item.entries.make_default()
        assert made == [1, 2, 3]
        assert made is not factory()

    def test_get_default_without_default_raises(self) -> None:
        class Item(mutobj.Declaration):
            value: int

        try:
            Item.value.get_default()
        except ValueError as exc:
            assert "has no default" in str(exc)
        else:
            raise AssertionError("expected ValueError")

    def test_make_default_without_default_raises(self) -> None:
        class Item(mutobj.Declaration):
            value: int

        try:
            Item.value.make_default()
        except ValueError as exc:
            assert "has no default" in str(exc)
        else:
            raise AssertionError("expected ValueError")


class TestFieldReflectionAPI:
    """测试公开反射 API：field_default / field_info / fields。"""

    def test_field_default_returns_value(self) -> None:
        class Action(mutobj.Declaration):
            categories: tuple[str, ...] = ()
            order: int | None = None
            label: str = "x"

        assert mutobj.field_default(Action.categories) == ()
        assert mutobj.field_default(Action.order) is None
        assert mutobj.field_default(Action.label) == "x"

    def test_field_default_invokes_factory_each_call(self) -> None:
        class Item(mutobj.Declaration):
            entries: list[int] = mutobj.field(default_factory=lambda: [1, 2, 3])

        a = mutobj.field_default(Item.entries)
        b = mutobj.field_default(Item.entries)
        assert a == [1, 2, 3]
        assert b == [1, 2, 3]
        assert a is not b  # 工厂每次生成新对象

    def test_field_default_without_default_raises(self) -> None:
        class Item(mutobj.Declaration):
            value: int

        try:
            mutobj.field_default(Item.value)
        except ValueError as exc:
            assert "has no default" in str(exc)
        else:
            raise AssertionError("expected ValueError")

    def test_field_default_rejects_non_descriptor_token(self) -> None:
        class Action(mutobj.Declaration):
            categories: tuple[str, ...] = ()

        inst = Action()
        # 实例属性是 tuple，不是 descriptor
        try:
            mutobj.field_default(inst.categories)
        except TypeError as exc:
            assert "class-level field token" in str(exc)
        else:
            raise AssertionError("expected TypeError")

        # 任意别的值也该被拒
        try:
            mutobj.field_default("some string")
        except TypeError:
            pass
        else:
            raise AssertionError("expected TypeError")

    def test_field_info_returns_descriptor(self) -> None:
        class Action(mutobj.Declaration):
            categories: tuple[str, ...] = ("a",)

        from mutobj import AttributeDescriptor

        info = mutobj.field_info(Action.categories)
        assert isinstance(info, AttributeDescriptor)
        assert info.name == "categories"
        assert info.has_default is True
        assert info.default == ("a",)
        assert info.init is True

    def test_field_info_rejects_non_descriptor(self) -> None:
        try:
            mutobj.field_info(123)
        except TypeError as exc:
            assert "class-level field token" in str(exc)
        else:
            raise AssertionError("expected TypeError")

    def test_fields_returns_all_descriptors(self) -> None:
        class Action(mutobj.Declaration):
            categories: tuple[str, ...] = ()
            order: int | None = None
            label: str = "x"

        from mutobj import AttributeDescriptor

        result = mutobj.fields(Action)
        assert set(result.keys()) == {"categories", "order", "label"}
        for name, info in result.items():
            assert isinstance(info, AttributeDescriptor)
            assert info.name == name

    def test_fields_inheritance_mro_order(self) -> None:
        class Base(mutobj.Declaration):
            x: int = 1
            y: int = 2

        class Child(Base):
            z: int = 3

        # 基类在前，子类在后（与 dataclass 一致）
        assert list(mutobj.fields(Child).keys()) == ["x", "y", "z"]
        assert list(mutobj.fields(Base).keys()) == ["x", "y"]

    def test_fields_subclass_overrides_descriptor(self) -> None:
        class Base(mutobj.Declaration):
            x: int = 1

        class Child(Base):
            x: int = 99  # 覆盖默认值

        assert mutobj.field_default(Child.x) == 99
        assert mutobj.field_default(Base.x) == 1
        # fields(Child) 返回最派生的 descriptor
        assert mutobj.fields(Child)["x"].default == 99

    def test_fields_dynamic_field_name_use_case(self) -> None:
        """上下文：动态字段名场景走 fields(cls)[name]。"""
        class Action(mutobj.Declaration):
            categories: tuple[str, ...] = ("x",)

        name = "categories"
        info = mutobj.fields(Action)[name]
        assert info.make_default() == ("x",)

    def test_fields_empty_for_no_field_class(self) -> None:
        class Empty(mutobj.Declaration):
            pass

        assert dict(mutobj.fields(Empty)) == {}
