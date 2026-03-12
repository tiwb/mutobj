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


# ── 无注解属性覆盖 ────────────────────────────────────────────

class TestUnannotatedOverride:
    """子类用无注解赋值覆盖父类声明属性"""

    # -- 核心场景 --

    def test_basic_override(self):
        """基本无注解覆盖：实例属性返回子类覆盖值"""
        class View(mutobj.Declaration):
            path: str = ""

        class HealthView(View):
            path = "/api/health"

        assert HealthView().path == "/api/health"

    def test_multi_level_skip_override(self):
        """多层继承跳级覆盖：A→B→C，C 覆盖 A 的属性"""
        class A(mutobj.Declaration):
            x: int = 1

        class B(A):
            pass

        class C(B):
            x = 100

        assert C().x == 100
        assert B().x == 1  # B 不受影响

    def test_kwargs_still_override(self):
        """kwargs 仍能覆盖无注解默认值"""
        class View(mutobj.Declaration):
            path: str = ""

        class HealthView(View):
            path = "/api/health"

        assert HealthView(path="/custom").path == "/custom"

    def test_parent_unaffected(self):
        """子类无注解覆盖不影响父类"""
        class Base(mutobj.Declaration):
            value: int = 0

        class Child(Base):
            value = 42

        assert Base().value == 0
        assert Child().value == 42

    def test_mixed_annotated_and_unannotated(self):
        """同一子类中带注解和无注解覆盖共存"""
        class Base(mutobj.Declaration):
            x: int = 1
            y: str = "a"
            z: float = 0.0

        class Child(Base):
            x: int = 10       # 带注解覆盖
            y = "b"           # 无注解覆盖
            # z 不覆盖

        c = Child()
        assert c.x == 10
        assert c.y == "b"
        assert c.z == 0.0

    # -- 边界情况 --

    def test_mutable_unannotated_override_raises(self):
        """可变类型无注解覆盖应报 TypeError"""
        class Base(mutobj.Declaration):
            items: list[int] = field(default_factory=list)

        with pytest.raises(TypeError, match="mutable default"):
            class Child(Base):
                items = [1, 2, 3]

    def test_field_unannotated_override(self):
        """field() 无注解覆盖应正确识别"""
        class Base(mutobj.Declaration):
            items: list[str] = field(default_factory=list)

        class Child(Base):
            items = field(default_factory=lambda: ["a", "b"])

        assert Child().items == ["a", "b"]
        assert Base().items == []  # 父类不受影响

    def test_callable_not_mistaken_as_override(self):
        """子类定义同名方法不应触发无注解覆盖逻辑（不创建新描述符）"""
        class Base(mutobj.Declaration):
            process: str = "default"

        class Child(Base):
            def process(self):
                return "method"

        # 无注解覆盖逻辑应跳过 callable，不为 Child 创建新的 AttributeDescriptor
        child_desc = Child.__dict__.get("process")
        assert not isinstance(child_desc, AttributeDescriptor)

    def test_private_attr_not_triggered(self):
        """私有属性不触发覆盖逻辑"""
        class Base(mutobj.Declaration):
            _internal: str = "base"

        class Child(Base):
            _internal = "child"

        # _internal 不在 _attribute_registry 中（下划线开头跳过）
        assert Child._internal == "child"

    # -- 注册表与交互验证 --

    def test_descriptor_created_on_subclass(self):
        """无注解覆盖后，子类 __dict__ 中有独立的 AttributeDescriptor"""
        class Base(mutobj.Declaration):
            val: int = 0

        class Child(Base):
            val = 99

        desc = Child.__dict__.get("val")
        assert isinstance(desc, AttributeDescriptor)
        assert desc.default == 99

    def test_attribute_registry_updated(self):
        """_attribute_registry 中子类包含覆盖属性"""
        class Base(mutobj.Declaration):
            val: int = 0

        class Child(Base):
            val = 99

        assert "val" in _attribute_registry[Child]

    def test_unannotated_override_with_impl(self):
        """无注解覆盖属性在 @impl 方法中可正确访问"""
        class View(mutobj.Declaration):
            path: str = ""

            def full_url(self) -> str: ...

        @mutobj.impl(View.full_url)
        def full_url(self: View) -> str:
            return f"http://localhost{self.path}"

        class HealthView(View):
            path = "/api/health"

        assert HealthView().full_url() == "http://localhost/api/health"
