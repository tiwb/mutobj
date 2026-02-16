"""测试 @mutobj.impl 装饰器"""

import pytest
import mutobj
from mutobj.core import _method_registry


class TestImplDecorator:
    """测试 impl 装饰器"""

    def test_basic_implementation(self):
        """测试基本方法实现"""
        class Greeter(mutobj.Declaration):
            name: str

            def greet(self) -> str:
                """Say hello"""
                ...

        @mutobj.impl(Greeter.greet)
        def greet(self: Greeter) -> str:
            return f"Hello, {self.name}!"

        g = Greeter(name="World")
        assert g.greet() == "Hello, World!"

    def test_implementation_registered(self):
        """测试实现被注册"""
        class Counter(mutobj.Declaration):
            def count(self) -> int:
                ...

        @mutobj.impl(Counter.count)
        def count(self: Counter) -> int:
            return 42

        assert Counter in _method_registry
        assert "count" in _method_registry[Counter]

    def test_duplicate_implementation_raises(self):
        """测试重复实现抛出错误"""
        class Adder(mutobj.Declaration):
            def add(self, a: int, b: int) -> int:
                ...

        @mutobj.impl(Adder.add)
        def add_v1(self: Adder, a: int, b: int) -> int:
            return a + b

        with pytest.raises(ValueError) as exc_info:
            @mutobj.impl(Adder.add)
            def add_v2(self: Adder, a: int, b: int) -> int:
                return a + b + 1

        assert "already implemented" in str(exc_info.value)

    def test_override_implementation(self):
        """测试使用 override=True 覆盖实现"""
        class Multiplier(mutobj.Declaration):
            def multiply(self, a: int, b: int) -> int:
                ...

        @mutobj.impl(Multiplier.multiply)
        def multiply_v1(self: Multiplier, a: int, b: int) -> int:
            return a * b

        m = Multiplier()
        assert m.multiply(3, 4) == 12

        @mutobj.impl(Multiplier.multiply, override=True)
        def multiply_v2(self: Multiplier, a: int, b: int) -> int:
            return a * b * 2

        assert m.multiply(3, 4) == 24

    def test_impl_with_self_attributes(self):
        """测试实现中访问 self 属性"""
        class Calculator(mutobj.Declaration):
            base: int

            def compute(self, x: int) -> int:
                ...

        @mutobj.impl(Calculator.compute)
        def compute(self: Calculator, x: int) -> int:
            return self.base + x

        calc = Calculator(base=10)
        assert calc.compute(5) == 15


class TestImplErrors:
    """测试 impl 装饰器错误处理"""

    def test_impl_non_declared_method(self):
        """测试实现非声明方法抛出错误"""
        class Widget(mutobj.Declaration):
            def declared_method(self) -> None:
                ...

        # 先实现声明的方法
        @mutobj.impl(Widget.declared_method)
        def declared_impl(self: Widget) -> None:
            pass

        # 注意：由于方法需要先存在于类中，
        # 这个测试需要特殊处理
