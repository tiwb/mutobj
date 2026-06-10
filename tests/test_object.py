"""测试 mutobj.Declaration 基类"""

import pytest
import mutobj
from mutobj.core._constants import DECLARED_METHODS
from mutobj.core._state import attribute_registry


class TestDeclarationDeclaration:
    """测试 Declaration 声明解析"""

    def test_simple_class_declaration(self):
        """测试简单类声明"""
        class User(mutobj.Declaration):
            name: str
            age: int

        # 验证属性已注册
        assert User in attribute_registry
        assert "name" in attribute_registry[User]
        assert "age" in attribute_registry[User]

    def test_attribute_access(self):
        """测试属性访问"""
        class Person(mutobj.Declaration):
            name: str

        p = Person(name="Alice")
        assert p.name == "Alice"

        p.name = "Bob"
        assert p.name == "Bob"

    def test_attribute_not_set(self):
        """测试无默认值字段在构造时就被要求提供。"""
        class Item(mutobj.Declaration):
            value: int

        with pytest.raises(
            TypeError,
            match=r"Item missing field\(s\) after construction: 'value'",
        ):
            Item()

    def test_method_declaration_recognized(self):
        """测试方法声明被识别"""
        class Calculator(mutobj.Declaration):
            def add(self, a: int, b: int) -> int:
                """Add two numbers"""
                ...

        # 验证方法被识别为声明
        declared = getattr(Calculator, DECLARED_METHODS, set())
        assert "add" in declared

    def test_stub_method_with_pass(self):
        """测试使用 pass 的桩方法"""
        class Service(mutobj.Declaration):
            def process(self) -> None:
                pass

        declared = getattr(Service, DECLARED_METHODS, set())
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
        """测试部分关键字参数初始化现在会拒绝缺失必填字段。"""
        class Config(mutobj.Declaration):
            host: str
            port: int

        with pytest.raises(
            TypeError,
            match=r"Config missing field\(s\) after construction: 'port'",
        ):
            Config(host="localhost")
