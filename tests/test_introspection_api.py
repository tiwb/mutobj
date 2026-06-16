"""Tests for mutobj impl introspection and descriptor metadata APIs."""

from __future__ import annotations

import pytest

import mutobj


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

    def test_impl_has_override_property_getter_with_impl(self) -> None:
        """property getter 有 @impl 时 impl_has_override 返回 True。"""
        class Svc(mutobj.Declaration):
            @property
            def name(self) -> str: ...

        @mutobj.impl(Svc.name.getter)
        def svc_name(self) -> str:
            return "impl"

        decl_func = mutobj.get_declaration_func(Svc, "name.getter")
        assert decl_func is not None
        assert mutobj.impl_has_override(decl_func) is True

    def test_impl_has_override_property_getter_without_impl(self) -> None:
        """property getter 无 @impl 时 impl_has_override 返回 False。"""
        class Svc(mutobj.Declaration):
            @property
            def name(self) -> str: ...

        decl_func = mutobj.get_declaration_func(Svc, "name.getter")
        assert decl_func is not None
        assert mutobj.impl_has_override(decl_func) is False

    def test_impl_has_override_property_setter_with_impl(self) -> None:
        """property setter 有 @impl 时 impl_has_override 返回 True。"""
        class Svc(mutobj.Declaration):
            @property
            def name(self) -> str: ...

            @name.setter
            def name(self, value: str) -> None: ...

        @mutobj.impl(Svc.name.setter)
        def svc_name(self, value: str) -> None:
            pass

        decl_func = mutobj.get_declaration_func(Svc, "name.setter")
        assert decl_func is not None
        assert mutobj.impl_has_override(decl_func) is True

    def test_impl_has_override_property_setter_without_impl(self) -> None:
        """property setter 无 @impl 时 impl_has_override 返回 False。"""
        class Svc(mutobj.Declaration):
            @property
            def name(self) -> str: ...

            @name.setter
            def name(self, value: str) -> None: ...

        decl_func = mutobj.get_declaration_func(Svc, "name.setter")
        assert decl_func is not None
        assert mutobj.impl_has_override(decl_func) is False


class TestImplChain:

    def testimpl_chain_returns_copy(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> int:
                return 1

        chain = mutobj.impl_chain(Svc.run)
        assert len(chain) == 1
        chain.clear()
        assert len(mutobj.impl_chain(Svc.run)) == 1


class TestImplCallSuper:

    def test_impl_call_super_works(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self, x: int) -> int:
                return x + 1

        @mutobj.impl(Svc.run)
        def run(self, x: int) -> int:
            return mutobj.impl_call_super(Svc.run, self, x) * 10

        assert Svc().run(3) == 40


class TestFieldInfoDefaultErrors:

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
    """测试公开反射 API：fields。"""

    def test_make_default_returns_value(self) -> None:
        class Action(mutobj.Declaration):
            categories: tuple[str, ...] = ()
            order: int | None = None
            label: str = "x"

        assert Action.categories.make_default() == ()
        assert Action.order.make_default() is None
        assert Action.label.make_default() == "x"

    def test_make_default_invokes_factory_each_call(self) -> None:
        class Item(mutobj.Declaration):
            entries: list[int] = mutobj.field(default_factory=lambda: [1, 2, 3])

        a = Item.entries.make_default()
        b = Item.entries.make_default()
        assert a == [1, 2, 3]
        assert b == [1, 2, 3]
        assert a is not b  # 工厂每次生成新对象

    def test_make_default_without_default_raises(self) -> None:
        class Item(mutobj.Declaration):
            value: int

        try:
            Item.value.make_default()
        except ValueError as exc:
            assert "has no default" in str(exc)
        else:
            raise AssertionError("expected ValueError")

    def test_class_field_returns_field_info(self) -> None:
        class Action(mutobj.Declaration):
            categories: tuple[str, ...] = ("a",)

        from mutobj import FieldInfo

        info = Action.categories
        assert isinstance(info, FieldInfo)
        assert info.name == "categories"
        assert info.has_default is True
        assert info.make_default() == ("a",)
        assert info.init is True

    def test_fields_returns_all_field_infos(self) -> None:
        class Action(mutobj.Declaration):
            categories: tuple[str, ...] = ()
            order: int | None = None
            label: str = "x"

        from mutobj import FieldInfo

        result = mutobj.fields(Action)
        assert set(result.keys()) == {"categories", "order", "label"}
        for name, info in result.items():
            assert isinstance(info, FieldInfo)
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

        assert Child.x.make_default() == 99
        assert Base.x.make_default() == 1
        # fields(Child) 返回最派生的 descriptor
        assert mutobj.fields(Child)["x"].make_default() == 99

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

