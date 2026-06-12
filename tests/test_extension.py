"""测试 mutobj.Extension 机制"""

import pytest
import mutobj


class TestExtensionBasic:
    """测试 Extension 基本功能"""

    def test_extension_generic_syntax(self):
        """测试 Extension[T] 泛型语法"""
        class User(mutobj.Declaration):
            name: str

        class UserExt(mutobj.Extension[User]):
            pass

        assert mutobj.extension_base(UserExt) is User

    def test_extension_get_or_create(self):
        """测试 Extension.get_or_create() 方法"""
        class Person(mutobj.Declaration):
            name: str

        class PersonExt(mutobj.Extension[Person]):
            _counter: int = 0

        p = Person(name="Alice")
        ext = PersonExt.get_or_create(p)

        assert ext is not None
        assert ext.target is p

    def test_extension_get_or_create_cached(self):
        """测试 get_or_create() 缓存"""
        class Item(mutobj.Declaration):
            value: int

        class ItemExt(mutobj.Extension[Item]):
            pass

        item = Item(value=42)
        ext1 = ItemExt.get_or_create(item)
        ext2 = ItemExt.get_or_create(item)

        assert ext1 is ext2

    def test_extension_private_state(self):
        """测试 Extension 私有状态"""
        class Counter(mutobj.Declaration):
            name: str

        class CounterExt(mutobj.Extension[Counter]):
            _count: int = 0

            def increment(self) -> int:
                self._count += 1
                return self._count

        c = Counter(name="test")
        ext = CounterExt.get_or_create(c)

        assert ext.increment() == 1
        assert ext.increment() == 2
        assert ext._count == 2

    def test_extension_access_target_attributes(self):
        """测试 Extension 通过 instance 访问目标实例属性"""
        class Product(mutobj.Declaration):
            name: str
            price: float

        class ProductExt(mutobj.Extension[Product]):
            def get_display(self) -> str:
                return f"{self.target.name}: ${self.target.price}"

        p = Product(name="Widget", price=9.99)
        ext = ProductExt.get_or_create(p)

        assert ext.get_display() == "Widget: $9.99"


class TestExtensionInit:
    """测试 Extension 初始化"""

    def test_extension_init_with_instance_access(self):
        """测试 __init__ 中 _instance 可访问"""
        class Config(mutobj.Declaration):
            name: str

        init_called = []

        class ConfigExt(mutobj.Extension[Config]):
            _initialized: bool = False

            def __init__(self):
                self._initialized = True
                init_called.append(self.target.name)

        c = Config(name="test")
        ext = ConfigExt.get_or_create(c)

        assert ext._initialized
        assert init_called == ["test"]

        # 再次获取不应重复调用
        ext2 = ConfigExt.get_or_create(c)
        assert len(init_called) == 1

    def test_extension_field_default_factory(self):
        """测试 field(default_factory=...) 按实例独立"""
        class Data(mutobj.Declaration):
            value: int

        class DataExt(mutobj.Extension[Data]):
            _cache: list = mutobj.field(default_factory=list)
            _count: int = 0

        d1 = Data(value=10)
        d2 = Data(value=20)
        ext1 = DataExt.get_or_create(d1)
        ext2 = DataExt.get_or_create(d2)

        assert ext1._cache == []
        assert ext1._count == 0
        ext1._cache.append("a")
        assert ext1._cache == ["a"]
        assert ext2._cache == []  # 实例独立

    def test_extension_field_default_value(self):
        """测试 field(default=...) 不可变默认值"""
        class Cfg(mutobj.Declaration):
            name: str

        class CfgExt(mutobj.Extension[Cfg]):
            _level: int = mutobj.field(default=5)

        c = Cfg(name="x")
        ext = CfgExt.get_or_create(c)
        assert ext._level == 5


class TestExtensionWithImpl:
    """测试 Extension 与 impl 配合使用"""

    def test_impl_using_extension(self):
        """测试在 impl 中使用 Extension"""
        class Greeter(mutobj.Declaration):
            name: str

            def greet(self) -> str:
                """Say hello"""
                ...

        class GreeterExt(mutobj.Extension[Greeter]):
            _call_count: int = 0

            def _format_greeting(self) -> str:
                return f"Hello, {self.target.name}!"

        @mutobj.impl(Greeter.greet)
        def greet(self: Greeter) -> str:
            ext = GreeterExt.get_or_create(self)
            ext._call_count += 1
            return ext._format_greeting()

        g = Greeter(name="World")
        assert g.greet() == "Hello, World!"
        assert g.greet() == "Hello, World!"

        ext = GreeterExt.get_or_create(g)
        assert ext._call_count == 2


class TestExtensionRegistry:
    """测试 Extension 注册机制"""

    def test_extension_auto_register(self):
        """测试 Extension[T] 声明自动注册"""
        class Animal(mutobj.Declaration):
            name: str

        class AnimalExt(mutobj.Extension[Animal]):
            _tag: str = ""

        ext_types = mutobj.extension_types(Animal)
        assert AnimalExt in ext_types

    def test_extension_types_query(self):
        """测试 extension_types() 查询"""
        class Vehicle(mutobj.Declaration):
            model: str

        class VehicleExt1(mutobj.Extension[Vehicle]):
            _speed: int = 0

        class VehicleExt2(mutobj.Extension[Vehicle]):
            _fuel: float = 0.0

        ext_types = mutobj.extension_types(Vehicle)
        assert VehicleExt1 in ext_types
        assert VehicleExt2 in ext_types

    def test_extension_types_with_filter(self):
        """测试 extension_types() 带类型过滤"""
        class Node(mutobj.Declaration):
            label: str

        class Serializable:
            def _serialize(self) -> dict: ...

        class NodeExt1(mutobj.Extension[Node], Serializable):
            _data: str = ""

            def _serialize(self) -> dict:
                return {"data": self._data}

        class NodeExt2(mutobj.Extension[Node]):
            _count: int = 0

        all_types = mutobj.extension_types(Node)
        assert NodeExt1 in all_types
        assert NodeExt2 in all_types

        ser_types = mutobj.extension_types(Node, Serializable)
        assert NodeExt1 in ser_types
        assert NodeExt2 not in ser_types

    def test_pure_inheritance_not_registered(self):
        """测试纯继承 Extension 子类不注册（决策 8）"""
        class Robot(mutobj.Declaration):
            name: str

        class RobotExt(mutobj.Extension[Robot]):
            _power: int = 100

        # 纯继承，没写 Extension[T] → 不注册
        class RobotExtPlus(RobotExt):
            _extra: str = ""

        ext_types = mutobj.extension_types(Robot)
        assert RobotExt in ext_types
        assert RobotExtPlus not in ext_types

        # 但 RobotExtPlus 仍可通过 get_or_create 使用
        r = Robot(name="R2D2")
        ext = RobotExtPlus.get_or_create(r)
        assert ext._power == 100
        assert ext._extra == ""

    def test_inheritance_with_explicit_registration(self):
        """测试继承 + 显式 Extension[T] 注册（决策 8）"""
        class Base(mutobj.Declaration):
            name: str

        class Advanced(Base):
            level: int = 1

        class BaseExt(mutobj.Extension[Base]):
            _tag: str = "base"

        class AdvancedExt(BaseExt, mutobj.Extension[Advanced]):
            _level_cache: dict = mutobj.field(default_factory=dict)

        base_types = mutobj.extension_types(Base)
        assert BaseExt in base_types
        assert AdvancedExt not in base_types

        adv_types = mutobj.extension_types(Advanced)
        assert AdvancedExt in adv_types

    def test_extension_types_mro_collection(self):
        """测试 extension_types() 沿 Declaration MRO 收集（决策 9）"""
        class Parent(mutobj.Declaration):
            name: str

        class Child(Parent):
            age: int = 0

        class ParentExt(mutobj.Extension[Parent]):
            _parent_data: str = ""

        class ChildExt(mutobj.Extension[Child]):
            _child_data: str = ""

        parent_types = mutobj.extension_types(Parent)
        assert ParentExt in parent_types
        assert ChildExt not in parent_types

        child_types = mutobj.extension_types(Child)
        assert ParentExt in child_types  # 沿 MRO 收集
        assert ChildExt in child_types


class TestExtensionEnumeration:
    """测试枚举与过滤"""

    def test_extensions_returns_created(self):
        """测试 extensions() 返回已创建的 Extension"""
        class Ship(mutobj.Declaration):
            name: str

        class ShipExt1(mutobj.Extension[Ship]):
            _speed: int = 0

        class ShipExt2(mutobj.Extension[Ship]):
            _fuel: float = 0.0

        s = Ship(name="Titanic")
        assert mutobj.extensions(s) == []

        ext1 = ShipExt1.get_or_create(s)
        exts = mutobj.extensions(s)
        assert len(exts) == 1
        assert ext1 in exts

        ext2 = ShipExt2.get_or_create(s)
        exts = mutobj.extensions(s)
        assert len(exts) == 2
        assert ext1 in exts
        assert ext2 in exts

    def test_extensions_with_type_filter(self):
        """测试 extensions() 带类型过滤（多继承接口）"""
        class Planet(mutobj.Declaration):
            name: str

        class Loggable:
            def _log(self) -> str: ...

        class PlanetExt1(mutobj.Extension[Planet], Loggable):
            _distance: float = 0.0

            def _log(self) -> str:
                return f"distance={self._distance}"

        class PlanetExt2(mutobj.Extension[Planet]):
            _moons: int = 0

        p = Planet(name="Mars")
        PlanetExt1.get_or_create(p)
        PlanetExt2.get_or_create(p)

        all_exts = mutobj.extensions(p)
        assert len(all_exts) == 2

        log_exts = mutobj.extensions(p, Loggable)
        assert len(log_exts) == 1
        assert isinstance(log_exts[0], PlanetExt1)

    def test_extensions_empty_for_new_instance(self):
        """测试未创建 Extension 的实例返回空列表"""
        class Star(mutobj.Declaration):
            name: str

        s = Star(name="Sun")
        assert mutobj.extensions(s) == []


class TestExtensionGet:
    """测试 get() 查询方法"""

    def test_get_returns_none_when_not_created(self):
        """测试未创建时返回 None"""
        class City(mutobj.Declaration):
            name: str

        class CityExt(mutobj.Extension[City]):
            _pop: int = 0

        c = City(name="Tokyo")
        assert CityExt.get(c) is None

    def test_get_returns_cached_instance(self):
        """测试已创建后返回缓存实例"""
        class River(mutobj.Declaration):
            name: str

        class RiverExt(mutobj.Extension[River]):
            _length: float = 0.0

        r = River(name="Nile")
        ext = RiverExt.get_or_create(r)
        assert RiverExt.get(r) is ext


class TestExtensionField:
    """测试 field() 在 Extension 中的支持"""

    def test_field_default_factory_list(self):
        """测试 field(default_factory=list) 按实例独立"""
        class Doc(mutobj.Declaration):
            title: str

        class DocExt(mutobj.Extension[Doc]):
            _tags: list = mutobj.field(default_factory=list)

        d1 = Doc(title="A")
        d2 = Doc(title="B")
        e1 = DocExt.get_or_create(d1)
        e2 = DocExt.get_or_create(d2)

        e1._tags.append("x")
        assert e1._tags == ["x"]
        assert e2._tags == []

    def test_field_default_factory_dict(self):
        """测试 field(default_factory=dict)"""
        class Log(mutobj.Declaration):
            name: str

        class LogExt(mutobj.Extension[Log]):
            _entries: dict = mutobj.field(default_factory=dict)

        l = Log(name="main")
        ext = LogExt.get_or_create(l)
        assert ext._entries == {}
        ext._entries["k"] = "v"
        assert ext._entries == {"k": "v"}

    def test_field_immutable_default(self):
        """测试 field(default=...) 不可变默认值"""
        class Svc(mutobj.Declaration):
            name: str

        class SvcExt(mutobj.Extension[Svc]):
            _timeout: int = mutobj.field(default=30)
            _prefix: str = mutobj.field(default="svc")

        s = Svc(name="api")
        ext = SvcExt.get_or_create(s)
        assert ext._timeout == 30
        assert ext._prefix == "svc"

    def test_multiple_instances_field_independent(self):
        """测试多个实例的 field 值互不影响"""
        class Task(mutobj.Declaration):
            name: str

        class TaskExt(mutobj.Extension[Task]):
            _results: list = mutobj.field(default_factory=list)
            _attempts: int = 0

        t1 = Task(name="a")
        t2 = Task(name="b")
        e1 = TaskExt.get_or_create(t1)
        e2 = TaskExt.get_or_create(t2)

        e1._results.append(1)
        e1._attempts = 3
        assert e2._results == []
        assert e2._attempts == 0


class TestExtensionSetattr:
    """测试 Extension 严格模式：未声明字段 setattr 报错，已声明字段 setattr 不代理到 Declaration。"""

    def test_undeclared_public_attr_rejected(self):
        """未声明字段赋值报 AttributeError（严格模式）。"""
        class Host(mutobj.Declaration):
            name: str = "host"

        class HostExt(mutobj.Extension[Host]):
            pass

        h = Host()
        ext = HostExt.get_or_create(h)
        with pytest.raises(AttributeError):
            ext.callback = lambda: "ext"  # type: ignore

    def test_overwrite_method_on_extension_rejected(self):
        """覆写方法名（未声明为字段）报 AttributeError。"""
        class Target(mutobj.Declaration):
            name: str

        class TargetExt(mutobj.Extension[Target]):
            def transform(self) -> str:
                return "default"

        t = Target(name="t")
        ext = TargetExt.get_or_create(t)
        assert ext.transform() == "default"
        with pytest.raises(AttributeError):
            ext.transform = lambda: "custom"  # type: ignore

    def test_declared_field_setattr_does_not_leak_to_declaration(self):
        """已声明字段赋值只作用于 Extension、不代理到宇主 Declaration。"""
        class Svc(mutobj.Declaration):
            name: str

        class SvcExt(mutobj.Extension[Svc]):
            _state: int = 0

        s = Svc(name="s")
        ext = SvcExt.get_or_create(s)
        ext._state = 42
        assert ext._state == 42
        assert not hasattr(s, "_state")

    def test_instance_is_public(self):
        class Obj(mutobj.Declaration):
            value: int = 10

        class ObjExt(mutobj.Extension[Obj]):
            pass

        o = Obj()
        ext = ObjExt.get_or_create(o)
        assert ext.target is o
        assert ext.target.value == 10


class TestExtensionFieldSystem:
    """验证 Extension 与 Declaration 共享一致的字段描述符体系。"""

    def test_lazy_default_factory_evaluated_on_first_access(self):
        """default_factory 首次访问时 lazy 求值、后续访问返回同一对象。"""
        calls: list[int] = []

        def make_list() -> list[int]:
            calls.append(1)
            return []

        class Host(mutobj.Declaration):
            pass

        class HostExt(mutobj.Extension[Host]):
            items: list[int] = mutobj.field(default_factory=make_list)

        h = Host()
        ext = HostExt.get_or_create(h)
        # __init__ 未访问 items，不该触发工厂。
        assert calls == []
        first = ext.items
        assert calls == [1]
        # 同一 ext 再次访问不重复求值、返回同一对象。
        second = ext.items
        assert calls == [1]
        assert first is second

    def test_required_field_missing_raises(self):
        """必填字段未赋值时 get_or_create 报 TypeError。"""
        class Host(mutobj.Declaration):
            pass

        class HostExt(mutobj.Extension[Host]):
            required: str  # 无默认值

        h = Host()
        with pytest.raises(TypeError, match="missing field"):
            HostExt.get_or_create(h)

    def test_required_field_assigned_in_init_passes(self):
        """必填字段在 __init__ 赋值后能通过完整性检查。"""
        class Host(mutobj.Declaration):
            pass

        class HostExt(mutobj.Extension[Host]):
            required: str

            def __init__(self) -> None:
                self.required = "ok"

        h = Host()
        ext = HostExt.get_or_create(h)
        assert ext.required == "ok"

    def test_subclass_inherits_parent_fields(self):
        """子类能访问父类声明的字段。"""
        class Host(mutobj.Declaration):
            pass

        class BaseExt(mutobj.Extension[Host]):
            base_field: int = 1

        class ChildExt(BaseExt):
            child_field: str = "x"

        h = Host()
        ext = ChildExt.get_or_create(h)
        assert ext.base_field == 1
        assert ext.child_field == "x"

    def test_classvar_excluded_from_field_system(self):
        """ClassVar 不被处理为实例字段，保持为类属性。"""
        from typing import ClassVar

        class Host(mutobj.Declaration):
            pass

        class HostExt(mutobj.Extension[Host]):
            shared: ClassVar[int] = 99
            instance_field: int = 0

        h = Host()
        ext = HostExt.get_or_create(h)
        # ClassVar 仍是类属性，读到 99；实例字段 lazy default 读到 0。
        assert ext.shared == 99
        assert HostExt.shared == 99
        assert ext.instance_field == 0
        # ClassVar 不作为字段；实例字段在 fields 中
        assert "shared" not in mutobj.fields(HostExt)
        assert "instance_field" in mutobj.fields(HostExt)
