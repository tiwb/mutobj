"""测试 pyic.Object 基类"""

import pytest
import pyic
from pyic.core import _attribute_registry, _DECLARED_METHODS


class TestObjectDeclaration:
    """测试 Object 声明解析"""

    def test_simple_class_declaration(self):
        """测试简单类声明"""
        class User(pyic.Object):
            name: str
            age: int

        # 验证属性已注册
        assert User in _attribute_registry
        assert "name" in _attribute_registry[User]
        assert "age" in _attribute_registry[User]

    def test_attribute_access(self):
        """测试属性访问"""
        class Person(pyic.Object):
            name: str

        p = Person(name="Alice")
        assert p.name == "Alice"

        p.name = "Bob"
        assert p.name == "Bob"

    def test_attribute_not_set(self):
        """测试访问未设置的属性"""
        class Item(pyic.Object):
            value: int

        item = Item()
        with pytest.raises(AttributeError):
            _ = item.value

    def test_method_declaration_recognized(self):
        """测试方法声明被识别"""
        class Calculator(pyic.Object):
            def add(self, a: int, b: int) -> int:
                """Add two numbers"""
                ...

        # 验证方法被识别为声明
        declared = getattr(Calculator, _DECLARED_METHODS, set())
        assert "add" in declared

    def test_stub_method_with_pass(self):
        """测试使用 pass 的桩方法"""
        class Service(pyic.Object):
            def process(self) -> None:
                pass

        declared = getattr(Service, _DECLARED_METHODS, set())
        assert "process" in declared

    def test_unimplemented_method_raises(self):
        """测试调用未实现的方法抛出 NotImplementedError"""
        class Greeter(pyic.Object):
            def greet(self) -> str:
                """Say hello"""
                ...

        g = Greeter()
        with pytest.raises(NotImplementedError) as exc_info:
            g.greet()

        assert "greet" in str(exc_info.value)
        assert "not implemented" in str(exc_info.value)


class TestObjectInit:
    """测试 Object 初始化"""

    def test_kwargs_initialization(self):
        """测试通过关键字参数初始化"""
        class Product(pyic.Object):
            name: str
            price: float

        p = Product(name="Widget", price=9.99)
        assert p.name == "Widget"
        assert p.price == 9.99

    def test_partial_kwargs(self):
        """测试部分关键字参数初始化"""
        class Config(pyic.Object):
            host: str
            port: int

        c = Config(host="localhost")
        assert c.host == "localhost"

        with pytest.raises(AttributeError):
            _ = c.port
