"""测试 pyic Property 支持"""

import pytest
import pyic


class TestPropertyDeclaration:
    """测试 Property 声明"""

    def test_property_declaration(self):
        """测试 property 声明被识别"""
        class User(pyic.Object):
            name: str

            @property
            def display_name(self) -> str:
                """显示名称"""
                ...

        # 验证 property 被识别为声明
        from pyic.core import _DECLARED_PROPERTIES
        declared = getattr(User, _DECLARED_PROPERTIES, set())
        assert "display_name" in declared

    def test_unimplemented_property_raises(self):
        """测试访问未实现的 property 抛出 NotImplementedError"""
        class Config(pyic.Object):
            @property
            def value(self) -> int:
                """配置值"""
                ...

        c = Config()
        with pytest.raises(NotImplementedError) as exc_info:
            _ = c.value

        assert "value" in str(exc_info.value)
        assert "getter is not implemented" in str(exc_info.value)


class TestPropertyImplementation:
    """测试 Property 实现"""

    def test_property_getter_implementation(self):
        """测试实现 property getter"""
        class Product(pyic.Object):
            name: str
            price: float

            @property
            def display_price(self) -> str:
                """格式化价格"""
                ...

        @pyic.impl(Product.display_price.getter)
        def display_price(self: Product) -> str:
            return f"${self.price:.2f}"

        p = Product(name="Widget", price=9.99)
        assert p.display_price == "$9.99"

    def test_property_setter_implementation(self):
        """测试实现 property setter"""
        class Counter(pyic.Object):
            _value: int

            @property
            def value(self) -> int:
                """计数值"""
                ...

        @pyic.impl(Counter.value.getter)
        def value_getter(self: Counter) -> int:
            return self._value

        @pyic.impl(Counter.value.setter)
        def value_setter(self: Counter, val: int) -> None:
            if val < 0:
                raise ValueError("Value must be non-negative")
            self._value = val

        c = Counter()
        c._value = 0

        c.value = 10
        assert c.value == 10

        with pytest.raises(ValueError):
            c.value = -1

    def test_readonly_property(self):
        """测试只读 property（无 setter）"""
        class ReadOnly(pyic.Object):
            _data: str

            @property
            def data(self) -> str:
                """只读数据"""
                ...

        @pyic.impl(ReadOnly.data.getter)
        def data_getter(self: ReadOnly) -> str:
            return self._data

        obj = ReadOnly()
        obj._data = "test"
        assert obj.data == "test"

        with pytest.raises(AttributeError) as exc_info:
            obj.data = "new"

        assert "read-only" in str(exc_info.value) or "setter is not implemented" in str(exc_info.value)


class TestPropertyOverride:
    """测试 Property 覆盖"""

    def test_property_getter_override(self):
        """测试覆盖 property getter"""
        class Formatter(pyic.Object):
            value: str

            @property
            def formatted(self) -> str:
                """格式化值"""
                ...

        @pyic.impl(Formatter.formatted.getter)
        def formatted_v1(self: Formatter) -> str:
            return f"[{self.value}]"

        f = Formatter(value="test")
        assert f.formatted == "[test]"

        @pyic.impl(Formatter.formatted.getter, override=True)
        def formatted_v2(self: Formatter) -> str:
            return f"<{self.value}>"

        assert f.formatted == "<test>"

    def test_duplicate_property_getter_raises(self):
        """测试重复实现 property getter 抛出错误"""
        class Wrapper(pyic.Object):
            @property
            def wrapped(self) -> str:
                ...

        @pyic.impl(Wrapper.wrapped.getter)
        def wrapped_v1(self: Wrapper) -> str:
            return "v1"

        with pytest.raises(ValueError) as exc_info:
            @pyic.impl(Wrapper.wrapped.getter)
            def wrapped_v2(self: Wrapper) -> str:
                return "v2"

        assert "already implemented" in str(exc_info.value)
