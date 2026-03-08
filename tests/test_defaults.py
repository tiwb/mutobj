"""属性默认值测试"""

import pytest

import mutobj
from mutobj import field
from mutobj.core import _attribute_registry, AttributeDescriptor, _MISSING


# ── 基本默认值 ──────────────────────────────────────────────────

class TestImmutableDefaults:
    """不可变类型默认值"""

    def test_str_default(self):
        class User(mutobj.Declaration):
            name: str = "anonymous"

        u = User()
        assert u.name == "anonymous"

    def test_int_default(self):
        class Counter(mutobj.Declaration):
            value: int = 0

        c = Counter()
        assert c.value == 0

    def test_float_default(self):
        class Metric(mutobj.Declaration):
            score: float = 1.0

        m = Metric()
        assert m.score == 1.0

    def test_bool_default(self):
        class Feature(mutobj.Declaration):
            enabled: bool = False

        f = Feature()
        assert f.enabled is False

    def test_none_default(self):
        class Client(mutobj.Declaration):
            recorder: object | None = None

        c = Client()
        assert c.recorder is None

    def test_tuple_default(self):
        class Config(mutobj.Declaration):
            dims: tuple[int, int] = (0, 0)

        c = Config()
        assert c.dims == (0, 0)

    def test_kwargs_override_default(self):
        class User(mutobj.Declaration):
            name: str = "anonymous"
            age: int = 0

        u = User(name="Alice", age=25)
        assert u.name == "Alice"
        assert u.age == 25

    def test_partial_kwargs_with_defaults(self):
        class User(mutobj.Declaration):
            name: str
            age: int = 0
            active: bool = True

        u = User(name="Bob")
        assert u.name == "Bob"
        assert u.age == 0
        assert u.active is True

    def test_no_default_still_raises(self):
        """无默认值的属性未传入时仍报 AttributeError"""
        class Item(mutobj.Declaration):
            name: str
            count: int = 1

        item = Item()
        assert item.count == 1
        with pytest.raises(AttributeError):
            _ = item.name


class TestFieldFunction:
    """field() 函数"""

    def test_field_with_default(self):
        class Config(mutobj.Declaration):
            name: str = field(default="default")

        c = Config()
        assert c.name == "default"

    def test_field_default_factory_list(self):
        class Container(mutobj.Declaration):
            items: list[str] = field(default_factory=list)

        a = Container()
        b = Container()
        assert a.items == []
        assert b.items == []
        a.items.append("x")
        assert a.items == ["x"]
        assert b.items == []  # 独立实例

    def test_field_default_factory_dict(self):
        class Store(mutobj.Declaration):
            data: dict[str, int] = field(default_factory=dict)

        a = Store()
        b = Store()
        a.data["k"] = 1
        assert a.data == {"k": 1}
        assert b.data == {}

    def test_field_default_factory_set(self):
        class Tags(mutobj.Declaration):
            values: set[str] = field(default_factory=set)

        a = Tags()
        b = Tags()
        a.values.add("x")
        assert "x" in a.values
        assert "x" not in b.values

    def test_field_default_factory_custom(self):
        class Holder(mutobj.Declaration):
            data: list[int] = field(default_factory=lambda: [1, 2, 3])

        h = Holder()
        assert h.data == [1, 2, 3]

    def test_field_both_raises(self):
        """同时传 default 和 default_factory 报错"""
        with pytest.raises(TypeError, match="不能同时指定"):
            field(default=1, default_factory=int)


# ── 错误检测 ──────────────────────────────────────────────────

class TestMutableDefaultError:
    """可变类型直接赋值报错"""

    def test_list_default_raises(self):
        with pytest.raises(TypeError, match="可变默认值.*list"):
            class Bad(mutobj.Declaration):
                tags: list = []

    def test_dict_default_raises(self):
        with pytest.raises(TypeError, match="可变默认值.*dict"):
            class Bad(mutobj.Declaration):
                data: dict = {}

    def test_set_default_raises(self):
        with pytest.raises(TypeError, match="可变默认值.*set"):
            class Bad(mutobj.Declaration):
                ids: set = set()

    def test_bytearray_default_raises(self):
        with pytest.raises(TypeError, match="可变默认值.*bytearray"):
            class Bad(mutobj.Declaration):
                buf: bytearray = bytearray()


# ── 继承 ──────────────────────────────────────────────────────

class TestInheritanceDefaults:
    """继承场景下的默认值"""

    def test_child_inherits_parent_default(self):
        class Animal(mutobj.Declaration):
            name: str
            sound: str = "..."

        class Dog(Animal):
            breed: str

        d = Dog(name="Buddy", breed="Labrador")
        assert d.sound == "..."

    def test_child_overrides_parent_default(self):
        class Animal(mutobj.Declaration):
            sound: str = "..."

        class Dog(Animal):
            sound: str = "woof"

        d = Dog()
        assert d.sound == "woof"

    def test_multi_level_inheritance(self):
        class A(mutobj.Declaration):
            x: int = 1
            y: int = 2

        class B(A):
            y: int = 20
            z: int = 30

        class C(B):
            z: int = 300

        c = C()
        assert c.x == 1    # 从 A 继承
        assert c.y == 20   # 从 B 继承（覆盖 A）
        assert c.z == 300   # C 自己的（覆盖 B）

    def test_child_adds_new_defaulted_attrs(self):
        class Base(mutobj.Declaration):
            name: str

        class Extended(Base):
            active: bool = True
            count: int = 0

        e = Extended(name="test")
        assert e.name == "test"
        assert e.active is True
        assert e.count == 0

    def test_child_field_default_factory(self):
        class Base(mutobj.Declaration):
            name: str

        class Child(Base):
            tags: list[str] = field(default_factory=list)

        c = Child(name="x")
        assert c.tags == []


# ── 与现有功能交互 ─────────────────────────────────────────────

class TestDefaultsWithImpl:
    """默认值与 @impl 配合"""

    def test_default_value_accessible_in_impl(self):
        class Greeter(mutobj.Declaration):
            prefix: str = "Hello"

            def greet(self, name: str) -> str: ...

        @mutobj.impl(Greeter.greet)
        def greet(self: Greeter, name: str) -> str:
            return f"{self.prefix}, {name}!"

        g = Greeter()
        assert g.greet("World") == "Hello, World!"

    def test_kwargs_override_in_impl(self):
        class Greeter(mutobj.Declaration):
            prefix: str = "Hello"

            def greet(self, name: str) -> str: ...

        @mutobj.impl(Greeter.greet)
        def greet(self: Greeter, name: str) -> str:
            return f"{self.prefix}, {name}!"

        g = Greeter(prefix="Hi")
        assert g.greet("World") == "Hi, World!"


class TestDefaultsWithExtension:
    """默认值与 Extension 配合"""

    def test_extension_reads_default_value(self):
        class Item(mutobj.Declaration):
            label: str = "untitled"

        class ItemExt(mutobj.Extension[Item]):
            def get_label(self) -> str:
                return self.label

        item = Item()
        ext = ItemExt.get_or_create(item)
        assert ext.get_label() == "untitled"


class TestDefaultsWithReload:
    """默认值与类重定义配合"""

    def test_redefinition_updates_default(self):
        class Cfg(mutobj.Declaration):
            val: int = 10

        first_cls = Cfg

        # 重定义同名类（模拟 reload）
        class Cfg(mutobj.Declaration):  # type: ignore[no-redef]
            val: int = 20

        assert Cfg is first_cls  # in-place 更新
        c = Cfg()
        assert c.val == 20

    def test_redefinition_adds_default(self):
        class Cfg2(mutobj.Declaration):
            val: int

        first_cls = Cfg2

        class Cfg2(mutobj.Declaration):  # type: ignore[no-redef]
            val: int = 99

        assert Cfg2 is first_cls
        c = Cfg2()
        assert c.val == 99


# ── 描述符内部状态 ──────────────────────────────────────────────

class TestDescriptorInternals:
    """AttributeDescriptor 内部状态检查"""

    def test_has_default_with_value(self):
        d = AttributeDescriptor("x", int, default=0)
        assert d.has_default is True

    def test_has_default_with_factory(self):
        d = AttributeDescriptor("x", list, default_factory=list)
        assert d.has_default is True

    def test_has_default_without(self):
        d = AttributeDescriptor("x", int)
        assert d.has_default is False

    def test_has_default_with_none(self):
        """default=None 是有效默认值，不等于无默认值"""
        d = AttributeDescriptor("x", int, default=None)
        assert d.has_default is True

    def test_missing_sentinel(self):
        assert repr(_MISSING) == "MISSING"
        assert bool(_MISSING) is False
