"""测试 mutobj.Declaration 基类"""

import pytest
import mutobj
from mutobj.core import _attribute_registry, _DECLARED_METHODS


class TestDeclarationDeclaration:
    """测试 Declaration 声明解析"""

    def test_simple_class_declaration(self):
        """测试简单类声明"""
        class User(mutobj.Declaration):
            name: str
            age: int

        # 验证属性已注册
        assert User in _attribute_registry
        assert "name" in _attribute_registry[User]
        assert "age" in _attribute_registry[User]

    def test_attribute_access(self):
        """测试属性访问"""
        class Person(mutobj.Declaration):
            name: str

        p = Person(name="Alice")
        assert p.name == "Alice"

        p.name = "Bob"
        assert p.name == "Bob"

    def test_attribute_not_set(self):
        """测试访问未设置的属性"""
        class Item(mutobj.Declaration):
            value: int

        item = Item()
        with pytest.raises(AttributeError):
            _ = item.value

    def test_method_declaration_recognized(self):
        """测试方法声明被识别"""
        class Calculator(mutobj.Declaration):
            def add(self, a: int, b: int) -> int:
                """Add two numbers"""
                ...

        # 验证方法被识别为声明
        declared = getattr(Calculator, _DECLARED_METHODS, set())
        assert "add" in declared

    def test_stub_method_with_pass(self):
        """测试使用 pass 的桩方法"""
        class Service(mutobj.Declaration):
            def process(self) -> None:
                pass

        declared = getattr(Service, _DECLARED_METHODS, set())
        assert "process" in declared

    def test_default_impl_runs_without_error(self):
        """测试默认实现（方法体为 ...）直接执行，不抛出异常"""
        class Greeter(mutobj.Declaration):
            def greet(self) -> str:
                """Say hello"""
                ...

        g = Greeter()
        # 默认实现执行方法体（... 是表达式，函数隐式返回 None）
        result = g.greet()
        assert result is None


class TestDeclarationInit:
    """测试 Declaration 初始化"""

    def test_kwargs_initialization(self):
        """测试通过关键字参数初始化"""
        class Product(mutobj.Declaration):
            name: str
            price: float

        p = Product(name="Widget", price=9.99)
        assert p.name == "Widget"
        assert p.price == 9.99

    def test_partial_kwargs(self):
        """测试部分关键字参数初始化"""
        class Config(mutobj.Declaration):
            host: str
            port: int

        c = Config(host="localhost")
        assert c.host == "localhost"

        with pytest.raises(AttributeError):
            _ = c.port
