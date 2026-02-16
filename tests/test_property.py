"""测试 mutobj Property 支持"""

import pytest
import mutobj


class TestPropertyDeclaration:
    """测试 Property 声明"""

    def test_property_declaration(self):
        """测试 property 声明被识别"""
        class User(mutobj.Declaration):
            name: str

            @property
            def display_name(self) -> str:
                """显示名称"""
                ...

        # 验证 property 被识别为声明
        from mutobj.core import _DECLARED_PROPERTIES
        declared = getattr(User, _DECLARED_PROPERTIES, set())
        assert "display_name" in declared

    def test_default_property_getter_runs(self):
        """测试默认 property getter（方法体为 ...）直接执行"""
        class Config(mutobj.Declaration):
            @property
            def value(self) -> int:
                """配置值"""
                ...

        c = Config()
        # 默认 getter 执行方法体（... 是表达式，函数隐式返回 None）
        result = c.value
        assert result is None


class TestPropertyImplementation:
    """测试 Property 实现"""

    def test_property_getter_implementation(self):
        """测试实现 property getter"""
        class Product(mutobj.Declaration):
            name: str
            price: float

            @property
            def display_price(self) -> str:
                """格式化价格"""
                ...

        @mutobj.impl(Product.display_price.getter)
        def display_price(self: Product) -> str:
            return f"${self.price:.2f}"

        p = Product(name="Widget", price=9.99)
        assert p.display_price == "$9.99"

    def test_property_setter_implementation(self):
        """测试实现 property setter"""
        class Counter(mutobj.Declaration):
            _value: int

            @property
            def value(self) -> int:
                """计数值"""
                ...

        @mutobj.impl(Counter.value.getter)
        def value_getter(self: Counter) -> int:
            return self._value

        @mutobj.impl(Counter.value.setter)
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
        class ReadOnly(mutobj.Declaration):
            _data: str

            @property
            def data(self) -> str:
                """只读数据"""
                ...

        @mutobj.impl(ReadOnly.data.getter)
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
        class Formatter(mutobj.Declaration):
            value: str

            @property
            def formatted(self) -> str:
                """格式化值"""
                ...

        @mutobj.impl(Formatter.formatted.getter)
        def formatted_v1(self: Formatter) -> str:
            return f"[{self.value}]"

        f = Formatter(value="test")
        assert f.formatted == "[test]"

        @mutobj.impl(Formatter.formatted.getter)
        def formatted_v2(self: Formatter) -> str:
            return f"<{self.value}>"

        assert f.formatted == "<test>"

    def test_different_module_property_getter_overrides(self):
        """测试不同模块 property getter 自动覆盖"""
        class Wrapper(mutobj.Declaration):
            @property
            def wrapped(self) -> str:
                ...

        def wrapped_v1(self: Wrapper) -> str:
            return "v1"
        wrapped_v1.__module__ = "prop_dup_mod_a"
        mutobj.impl(Wrapper.wrapped.getter)(wrapped_v1)

        def wrapped_v2(self: Wrapper) -> str:
            return "v2"
        wrapped_v2.__module__ = "prop_dup_mod_b"
        mutobj.impl(Wrapper.wrapped.getter)(wrapped_v2)

        w = Wrapper()
        assert w.wrapped == "v2"  # v2 为活跃实现
