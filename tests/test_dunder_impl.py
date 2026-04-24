"""测试用户在 Declaration 子类里显式声明的 dunder / 单下划线方法的 @impl 行为。

参见 docs/specifications/bugfix-impl-dunder-target-misbinding.md。
"""
from __future__ import annotations

import sys
import types

import pytest

import mutobj


class TestDunderImpl:
    """显式声明的 dunder 方法可被 @impl 正确替换"""

    def test_init_stub_replaced_by_impl(self):
        """用户写的 __init__ stub 能被 @impl 覆盖（基本场景）"""
        class Widget(mutobj.Declaration):
            value: int

            def __init__(self) -> None: ...

        @mutobj.impl(Widget.__init__)
        def widget_init(self: Widget) -> None:
            self.value = 42

        w = Widget()
        assert w.value == 42

    def test_init_inherited_by_subclass(self):
        """子类 super().__init__() 能调到 @impl 注入的实现"""
        class DunderTestBase(mutobj.Declaration):
            tag: int

            def __init__(self) -> None: ...

        @mutobj.impl(DunderTestBase.__init__)
        def base_init(self: DunderTestBase) -> None:
            self.tag = 7

        class DunderTestSub(DunderTestBase):
            pass

        s = DunderTestSub()
        assert s.tag == 7

    def test_call_stub_replaced_by_impl(self):
        """用户写的 __call__ stub 能被 @impl 覆盖"""
        class Caller(mutobj.Declaration):
            def __call__(self, x: int) -> int: ...

        @mutobj.impl(Caller.__call__)
        def caller_call(self: Caller, x: int) -> int:
            return x * 2

        c = Caller()
        assert c(5) == 10


class TestSingleUnderscoreMethod:
    """单下划线方法（_xxx）也走注册"""

    def test_underscore_method_has_mutobj_class(self):
        """metaclass 给 _helper 设置 __mutobj_class__"""
        class Holder(mutobj.Declaration):
            def _helper(self) -> str: ...

        assert getattr(Holder._helper, "__mutobj_class__", None) is Holder

    def test_underscore_method_replaceable_by_impl(self):
        """_helper 可被 @impl 覆盖"""
        class Holder(mutobj.Declaration):
            def _helper(self) -> str: ...

        @mutobj.impl(Holder._helper)
        def helper_impl(self: Holder) -> str:
            return "from_impl"

        h = Holder()
        assert h._helper() == "from_impl"


class TestReservedDunders:
    """保留 dunder 在 Declaration 子类里定义不破坏 Python 类机制"""

    def test_init_subclass_works(self):
        """__init_subclass__ 仍是子类创建钩子，不被 mutobj 注册接管"""
        called: list[type] = []

        class Parent(mutobj.Declaration):
            def __init_subclass__(cls, **kwargs):
                super().__init_subclass__(**kwargs)
                called.append(cls)

        class Child(Parent):
            pass

        assert Child in called
        # 不应被注册为 declared method
        from mutobj.core import _impl_chain
        assert (Parent, "__init_subclass__") not in _impl_chain


class TestAmbiguousFallback:
    """Layer B：fallback 多匹配时报错"""

    def test_ambiguous_target_raises(self):
        """同名 Declaration 共存 + method 缺失 __mutobj_class__ → fallback 多匹配报错"""
        # 制造两个同名 Declaration
        mod_a = types.ModuleType("_test_amb_a")
        mod_b = types.ModuleType("_test_amb_b")
        sys.modules["_test_amb_a"] = mod_a
        sys.modules["_test_amb_b"] = mod_b
        try:
            exec(
                "import mutobj\n"
                "class Foo(mutobj.Declaration):\n"
                "    def bar(self) -> int: ...\n",
                mod_a.__dict__,
            )
            exec(
                "import mutobj\n"
                "class Foo(mutobj.Declaration):\n"
                "    def bar(self) -> int: ...\n",
                mod_b.__dict__,
            )

            FooA = mod_a.Foo

            # 强制让 method 缺失 __mutobj_class__，触发 fallback 路径
            method = FooA.bar
            try:
                del method.__mutobj_class__
            except AttributeError:
                pass

            with pytest.raises(ValueError, match="ambiguous target"):
                @mutobj.impl(method)
                def bar_impl(self) -> int:
                    return 1
        finally:
            sys.modules.pop("_test_amb_a", None)
            sys.modules.pop("_test_amb_b", None)

    def test_ambiguous_error_lists_candidates(self):
        """报错信息含两个候选类的全路径"""
        mod_a = types.ModuleType("_test_amb_c")
        mod_b = types.ModuleType("_test_amb_d")
        sys.modules["_test_amb_c"] = mod_a
        sys.modules["_test_amb_d"] = mod_b
        try:
            exec(
                "import mutobj\n"
                "class Bar(mutobj.Declaration):\n"
                "    def baz(self) -> None: ...\n",
                mod_a.__dict__,
            )
            exec(
                "import mutobj\n"
                "class Bar(mutobj.Declaration):\n"
                "    def baz(self) -> None: ...\n",
                mod_b.__dict__,
            )
            method = mod_a.Bar.baz
            try:
                del method.__mutobj_class__
            except AttributeError:
                pass

            with pytest.raises(ValueError) as exc_info:
                @mutobj.impl(method)
                def baz_impl(self) -> None: ...

            msg = str(exc_info.value)
            assert "_test_amb_c.Bar" in msg
            assert "_test_amb_d.Bar" in msg
        finally:
            sys.modules.pop("_test_amb_c", None)
            sys.modules.pop("_test_amb_d", None)


class TestSameNameDunderResolution:
    """两个同名 Declaration 都有 __init__ stub 时，@impl 能正确分发"""

    def test_same_name_init_resolved_correctly(self):
        """同名 Channel 共存，@impl(A.__init__) 装到 A，@impl(B.__init__) 装到 B"""
        mod_other = types.ModuleType("_test_chan_other")
        sys.modules["_test_chan_other"] = mod_other
        try:
            exec(
                "import mutobj\n"
                "class Channel(mutobj.Declaration):\n"
                "    other_field: int\n"
                "    def __init__(self) -> None: ...\n",
                mod_other.__dict__,
            )
            OtherChannel = mod_other.Channel

            class Channel(mutobj.Declaration):
                my_field: int

                def __init__(self) -> None: ...

            @mutobj.impl(Channel.__init__)
            def my_init(self: Channel) -> None:
                self.my_field = 100

            @mutobj.impl(OtherChannel.__init__)
            def other_init(self) -> None:
                self.other_field = 200

            c1 = Channel()
            c2 = OtherChannel()
            assert c1.my_field == 100
            assert c2.other_field == 200
        finally:
            sys.modules.pop("_test_chan_other", None)
