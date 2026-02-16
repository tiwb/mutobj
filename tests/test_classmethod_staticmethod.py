"""测试 mutobj classmethod/staticmethod 支持"""

import pytest
import mutobj
from mutobj.core import _DECLARED_CLASSMETHODS, _DECLARED_STATICMETHODS


class TestClassmethodDeclaration:
    """测试 classmethod 声明"""

    def test_classmethod_declaration_recognized(self):
        """测试 classmethod 声明被识别"""
        class Factory(mutobj.Declaration):
            @classmethod
            def create(cls) -> "Factory":
                """创建实例"""
                ...

        declared = getattr(Factory, _DECLARED_CLASSMETHODS, set())
        assert "create" in declared

    def test_unimplemented_classmethod_raises(self):
        """测试调用未实现的 classmethod 抛出 NotImplementedError"""
        class Builder(mutobj.Declaration):
            @classmethod
            def build(cls) -> "Builder":
                """构建实例"""
                ...

        with pytest.raises(NotImplementedError) as exc_info:
            Builder.build()

        assert "build" in str(exc_info.value)
        assert "Classmethod" in str(exc_info.value)


class TestClassmethodImplementation:
    """测试 classmethod 实现"""

    def test_classmethod_implementation(self):
        """测试实现 classmethod"""
        class Counter(mutobj.Declaration):
            value: int

            @classmethod
            def from_value(cls, val: int) -> "Counter":
                """从值创建"""
                ...

        @mutobj.impl(Counter.from_value)
        def from_value(cls, val: int) -> Counter:
            instance = cls()
            instance.value = val
            return instance

        c = Counter.from_value(42)
        assert c.value == 42

    def test_classmethod_with_inheritance(self):
        """测试 classmethod 在子类中的行为"""
        class Base(mutobj.Declaration):
            name: str

            @classmethod
            def create_with_name(cls, name: str) -> "Base":
                """使用名称创建"""
                ...

        @mutobj.impl(Base.create_with_name)
        def create_with_name(cls, name: str) -> Base:
            instance = cls()
            instance.name = name
            return instance

        b = Base.create_with_name("test")
        assert b.name == "test"
        assert type(b) is Base


class TestStaticmethodDeclaration:
    """测试 staticmethod 声明"""

    def test_staticmethod_declaration_recognized(self):
        """测试 staticmethod 声明被识别"""
        class Utils(mutobj.Declaration):
            @staticmethod
            def helper(x: int) -> int:
                """辅助函数"""
                ...

        declared = getattr(Utils, _DECLARED_STATICMETHODS, set())
        assert "helper" in declared

    def test_unimplemented_staticmethod_raises(self):
        """测试调用未实现的 staticmethod 抛出 NotImplementedError"""
        class Calculator(mutobj.Declaration):
            @staticmethod
            def compute(x: int, y: int) -> int:
                """计算"""
                ...

        with pytest.raises(NotImplementedError) as exc_info:
            Calculator.compute(1, 2)

        assert "compute" in str(exc_info.value)
        assert "Staticmethod" in str(exc_info.value)


class TestStaticmethodImplementation:
    """测试 staticmethod 实现"""

    def test_staticmethod_implementation(self):
        """测试实现 staticmethod"""
        class Math(mutobj.Declaration):
            @staticmethod
            def add(a: int, b: int) -> int:
                """加法"""
                ...

        @mutobj.impl(Math.add)
        def add(a: int, b: int) -> int:
            return a + b

        assert Math.add(3, 4) == 7

    def test_staticmethod_no_self_or_cls(self):
        """测试 staticmethod 不接收 self 或 cls"""
        class Validator(mutobj.Declaration):
            @staticmethod
            def is_valid(value: str) -> bool:
                """验证"""
                ...

        @mutobj.impl(Validator.is_valid)
        def is_valid(value: str) -> bool:
            return len(value) > 0

        assert Validator.is_valid("hello") is True
        assert Validator.is_valid("") is False

    def test_staticmethod_callable_on_instance(self):
        """测试 staticmethod 可以在实例上调用"""
        class Parser(mutobj.Declaration):
            @staticmethod
            def parse(text: str) -> list:
                """解析"""
                ...

        @mutobj.impl(Parser.parse)
        def parse(text: str) -> list:
            return text.split(",")

        p = Parser()
        assert Parser.parse("a,b,c") == ["a", "b", "c"]
        assert p.parse("x,y") == ["x", "y"]


class TestMixedMethods:
    """测试混合方法类型"""

    def test_class_with_all_method_types(self):
        """测试同时包含普通方法、classmethod、staticmethod"""
        class Service(mutobj.Declaration):
            name: str

            def process(self) -> str:
                """处理"""
                ...

            @classmethod
            def create(cls) -> "Service":
                """创建"""
                ...

            @staticmethod
            def validate(data: str) -> bool:
                """验证"""
                ...

        @mutobj.impl(Service.process)
        def process(self: Service) -> str:
            return f"Processing {self.name}"

        @mutobj.impl(Service.create)
        def create(cls) -> Service:
            s = cls()
            s.name = "default"
            return s

        @mutobj.impl(Service.validate)
        def validate(data: str) -> bool:
            return data.startswith("valid")

        # 测试普通方法
        s = Service(name="test")
        assert s.process() == "Processing test"

        # 测试 classmethod
        s2 = Service.create()
        assert s2.name == "default"

        # 测试 staticmethod
        assert Service.validate("valid_data") is True
        assert Service.validate("invalid") is False
