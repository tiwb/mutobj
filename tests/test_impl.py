"""测试 @mutobj.impl 装饰器"""

import pytest
import mutobj
from mutobj.core import _impl_chain


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

    def test_implementation_registered_in_chain(self):
        """测试实现被注册到覆盖链"""
        class Counter(mutobj.Declaration):
            def count(self) -> int:
                ...

        @mutobj.impl(Counter.count)
        def count(self: Counter) -> int:
            return 42

        key = (Counter, "count")
        assert key in _impl_chain
        chain = _impl_chain[key]
        # 链中应有默认实现和外部实现
        assert len(chain) >= 2
        # 链顶应为外部实现
        assert chain[-1][0] is count

    def test_different_module_impl_overrides(self):
        """测试不同模块实现自动覆盖（后注册者成为活跃实现）"""
        class Adder(mutobj.Declaration):
            def add(self, a: int, b: int) -> int:
                ...

        def add_v1(self: Adder, a: int, b: int) -> int:
            return a + b
        add_v1.__module__ = "dup_check_mod_a"
        mutobj.impl(Adder.add)(add_v1)

        def add_v2(self: Adder, a: int, b: int) -> int:
            return a + b + 1
        add_v2.__module__ = "dup_check_mod_b"
        mutobj.impl(Adder.add)(add_v2)

        a = Adder()
        assert a.add(1, 2) == 4  # v2 为活跃实现

    def test_same_module_reimpl_replaces(self):
        """测试同模块重复实现自动替换（reload 语义）"""
        class Replacer(mutobj.Declaration):
            def work(self) -> str:
                ...

        @mutobj.impl(Replacer.work)
        def work_v1(self: Replacer) -> str:
            return "v1"

        r = Replacer()
        assert r.work() == "v1"

        @mutobj.impl(Replacer.work)
        def work_v2(self: Replacer) -> str:
            return "v2"

        assert r.work() == "v2"

    def test_override_implementation(self):
        """测试覆盖实现（不同模块后注册者覆盖）"""
        class Multiplier(mutobj.Declaration):
            def multiply(self, a: int, b: int) -> int:
                ...

        @mutobj.impl(Multiplier.multiply)
        def multiply_v1(self: Multiplier, a: int, b: int) -> int:
            return a * b

        m = Multiplier()
        assert m.multiply(3, 4) == 12

        def multiply_v2(self: Multiplier, a: int, b: int) -> int:
            return a * b * 2
        multiply_v2.__module__ = "override_test_mod"
        mutobj.impl(Multiplier.multiply)(multiply_v2)

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

    def test_impl_refuses_to_pollute_declaration_base(self):
        """子类未声明 __init__ 桩时, @impl(Cls.__init__) 反推到 Declaration —
        必须报错而非静默替换 Declaration.__init__ 污染所有子类。"""
        import pytest

        class Box(mutobj.Declaration):
            width: float = 0.0

        # Box 未声明 __init__,Box.__init__ 实际是 Declaration.__init__
        with pytest.raises(ValueError, match="refusing to register on Declaration"):
            @mutobj.impl(Box.__init__)
            def _box_init(self: Box, w: float) -> None:
                self.width = w

        # 防污染生效后,其他 Declaration 子类的 __init__ 不受影响
        class Other(mutobj.Declaration):
            name: str = ""

        assert Other(name="ok").name == "ok"
