"""测试 pyic.Extension 机制"""

import pytest
import pyic


class TestExtensionBasic:
    """测试 Extension 基本功能"""

    def test_extension_generic_syntax(self):
        """测试 Extension[T] 泛型语法"""
        class User(pyic.Object):
            name: str

        class UserExt(pyic.Extension[User]):
            pass

        # 验证 _target_class 被设置
        assert UserExt._target_class is User

    def test_extension_of(self):
        """测试 Extension.of() 方法"""
        class Person(pyic.Object):
            name: str

        class PersonExt(pyic.Extension[Person]):
            _counter: int = 0

        p = Person(name="Alice")
        ext = PersonExt.of(p)

        assert ext is not None
        assert ext._instance is p

    def test_extension_of_cached(self):
        """测试 Extension.of() 缓存"""
        class Item(pyic.Object):
            value: int

        class ItemExt(pyic.Extension[Item]):
            pass

        item = Item(value=42)
        ext1 = ItemExt.of(item)
        ext2 = ItemExt.of(item)

        assert ext1 is ext2

    def test_extension_private_state(self):
        """测试 Extension 私有状态"""
        class Counter(pyic.Object):
            name: str

        class CounterExt(pyic.Extension[Counter]):
            _count: int = 0

            def increment(self) -> int:
                self._count += 1
                return self._count

        c = Counter(name="test")
        ext = CounterExt.of(c)

        assert ext.increment() == 1
        assert ext.increment() == 2
        assert ext._count == 2

    def test_extension_access_target_attributes(self):
        """测试 Extension 访问目标实例属性"""
        class Product(pyic.Object):
            name: str
            price: float

        class ProductExt(pyic.Extension[Product]):
            def get_display(self) -> str:
                return f"{self.name}: ${self.price}"

        p = Product(name="Widget", price=9.99)
        ext = ProductExt.of(p)

        assert ext.get_display() == "Widget: $9.99"


class TestExtensionInit:
    """测试 Extension 初始化"""

    def test_extension_init_hook(self):
        """测试 __extension_init__ 钩子"""
        class Config(pyic.Object):
            name: str

        init_called = []

        class ConfigExt(pyic.Extension[Config]):
            _initialized: bool = False

            def __extension_init__(self):
                self._initialized = True
                init_called.append(True)

        c = Config(name="test")
        ext = ConfigExt.of(c)

        assert ext._initialized
        assert len(init_called) == 1

        # 再次获取不应重复调用
        ext2 = ConfigExt.of(c)
        assert len(init_called) == 1

    def test_extension_default_values(self):
        """测试 Extension 默认值"""
        class Data(pyic.Object):
            value: int

        class DataExt(pyic.Extension[Data]):
            _cache: list = None
            _count: int = 0

            def __extension_init__(self):
                self._cache = []

        d = Data(value=10)
        ext = DataExt.of(d)

        assert ext._cache == []
        assert ext._count == 0


class TestExtensionWithImpl:
    """测试 Extension 与 impl 配合使用"""

    def test_impl_using_extension(self):
        """测试在 impl 中使用 Extension"""
        class Greeter(pyic.Object):
            name: str

            def greet(self) -> str:
                """Say hello"""
                ...

        class GreeterExt(pyic.Extension[Greeter]):
            _call_count: int = 0

            def _format_greeting(self) -> str:
                return f"Hello, {self.name}!"

            def __extension_init__(self):
                self._call_count = 0

        @pyic.impl(Greeter.greet)
        def greet(self: Greeter) -> str:
            ext = GreeterExt.of(self)
            ext._call_count += 1
            return ext._format_greeting()

        g = Greeter(name="World")
        assert g.greet() == "Hello, World!"
        assert g.greet() == "Hello, World!"

        ext = GreeterExt.of(g)
        assert ext._call_count == 2
