"""测试 mutobj 继承支持"""

import pytest
import mutobj


class TestBasicInheritance:
    """测试基本继承"""

    def test_subclass_inherits_attributes(self):
        """测试子类继承父类属性"""
        class Animal(mutobj.Declaration):
            name: str
            age: int

        class Dog(Animal):
            breed: str

        d = Dog(name="Buddy", age=3, breed="Labrador")
        assert d.name == "Buddy"
        assert d.age == 3
        assert d.breed == "Labrador"

    def test_subclass_inherits_method_implementation(self):
        """测试子类继承父类方法实现"""
        class Vehicle(mutobj.Declaration):
            brand: str

            def start(self) -> str:
                """启动"""
                ...

        @mutobj.impl(Vehicle.start)
        def start(self: Vehicle) -> str:
            return f"{self.brand} started"

        class Car(Vehicle):
            model: str

        c = Car(brand="Toyota", model="Camry")
        assert c.start() == "Toyota started"

    def test_multi_level_inheritance(self):
        """测试多级继承"""
        class A(mutobj.Declaration):
            a: int

            def method_a(self) -> int:
                ...

        @mutobj.impl(A.method_a)
        def method_a(self: A) -> int:
            return self.a

        class B(A):
            b: int

        class C(B):
            c: int

        obj = C(a=1, b=2, c=3)
        assert obj.a == 1
        assert obj.b == 2
        assert obj.c == 3
        assert obj.method_a() == 1


class TestMethodOverride:
    """测试方法覆盖"""

    def test_subclass_can_override_method(self):
        """测试子类可以覆盖父类方法"""
        class Animal(mutobj.Declaration):
            name: str

            def speak(self) -> str:
                ...

        @mutobj.impl(Animal.speak)
        def animal_speak(self: Animal) -> str:
            return f"{self.name} makes a sound"

        class Dog(Animal):
            def speak(self) -> str:
                ...

        @mutobj.impl(Dog.speak)
        def dog_speak(self: Dog) -> str:
            return f"{self.name} barks"

        a = Animal(name="Generic")
        d = Dog(name="Buddy")

        assert a.speak() == "Generic makes a sound"
        assert d.speak() == "Buddy barks"

    def test_override_does_not_affect_parent(self):
        """测试子类覆盖不影响父类"""
        class Base(mutobj.Declaration):
            value: int

            def compute(self) -> int:
                ...

        @mutobj.impl(Base.compute)
        def base_compute(self: Base) -> int:
            return self.value

        class Derived(Base):
            def compute(self) -> int:
                ...

        @mutobj.impl(Derived.compute)
        def derived_compute(self: Derived) -> int:
            return self.value * 2

        b = Base(value=10)
        d = Derived(value=10)

        assert b.compute() == 10
        assert d.compute() == 20


class TestPropertyInheritance:
    """测试 Property 继承"""

    def test_subclass_inherits_property(self):
        """测试子类继承 property"""
        class Person(mutobj.Declaration):
            first_name: str
            last_name: str

            @property
            def full_name(self) -> str:
                ...

        @mutobj.impl(Person.full_name.getter)
        def full_name(self: Person) -> str:
            return f"{self.first_name} {self.last_name}"

        class Employee(Person):
            employee_id: str

        e = Employee(first_name="John", last_name="Doe", employee_id="E001")
        assert e.full_name == "John Doe"


class TestClassmethodStaticmethodInheritance:
    """测试 classmethod/staticmethod 继承"""

    def test_subclass_inherits_classmethod(self):
        """测试子类继承 classmethod"""
        class Factory(mutobj.Declaration):
            value: int

            @classmethod
            def create(cls, v: int) -> "Factory":
                ...

        @mutobj.impl(Factory.create)
        def create(cls, v: int) -> Factory:
            obj = cls()
            obj.value = v
            return obj

        class ChildFactory(Factory):
            pass

        # 子类调用继承的 classmethod，应返回子类实例
        cf = ChildFactory.create(42)
        assert type(cf).__name__ == "ChildFactory"
        assert cf.value == 42

    def test_subclass_inherits_staticmethod(self):
        """测试子类继承 staticmethod"""
        class Utils(mutobj.Declaration):
            @staticmethod
            def helper(x: int) -> int:
                ...

        @mutobj.impl(Utils.helper)
        def helper(x: int) -> int:
            return x * 2

        class ExtendedUtils(Utils):
            pass

        assert ExtendedUtils.helper(5) == 10


class TestExtensionWithInheritance:
    """测试 Extension 与继承配合"""

    def test_extension_with_inherited_class(self):
        """测试 Extension 与继承类配合"""
        class Animal(mutobj.Declaration):
            name: str

            def greet(self) -> str:
                ...

        class AnimalExt(mutobj.Extension[Animal]):
            _count: int = 0

            def __extension_init__(self):
                self._count = 0

            def increment(self):
                self._count += 1

        @mutobj.impl(Animal.greet)
        def greet(self: Animal) -> str:
            ext = AnimalExt.of(self)
            ext.increment()
            return f"Hello, I'm {self.name} (called {ext._count} times)"

        class Dog(Animal):
            breed: str

        d = Dog(name="Buddy", breed="Labrador")
        assert d.greet() == "Hello, I'm Buddy (called 1 times)"
        assert d.greet() == "Hello, I'm Buddy (called 2 times)"


class TestInheritedImplCollision:
    """测试多子类继承同一桩方法时 @impl 互不干扰"""

    def test_multi_subclass_independent_impl(self):
        """核心场景：多子类继承同一桩方法，各自 @impl 后行为独立"""
        class Base(mutobj.Declaration):
            def process(self, data: str) -> str: ...

        class DriverA(Base):
            pass

        class DriverB(Base):
            pass

        @mutobj.impl(DriverA.process)
        def process_a(self, data):
            return "A: " + data

        @mutobj.impl(DriverB.process)
        def process_b(self, data):
            return "B: " + data

        a = DriverA()
        b = DriverB()
        assert a.process("x") == "A: x"
        assert b.process("x") == "B: x"

    def test_single_subclass_unaffected(self):
        """单子类场景行为不变（回归）"""
        class Base(mutobj.Declaration):
            def compute(self) -> int: ...

        class Child(Base):
            pass

        @mutobj.impl(Child.compute)
        def compute_child(self):
            return 42

        assert Child().compute() == 42

    def test_parent_impl_not_affected_by_child(self):
        """子类 @impl 不影响父类"""
        class Base(mutobj.Declaration):
            value: int

            def compute(self) -> int: ...

        @mutobj.impl(Base.compute)
        def compute_base(self):
            return self.value

        class Derived(Base):
            pass

        @mutobj.impl(Derived.compute)
        def compute_derived(self):
            return self.value * 2

        assert Base(value=5).compute() == 5
        assert Derived(value=5).compute() == 10

    def test_deep_inheritance_chain(self):
        """深层继承链：A → B → C，C 未重新定义 A 的方法"""
        class A(mutobj.Declaration):
            def method(self) -> str: ...

        class B(A):
            pass

        class C(B):
            pass

        @mutobj.impl(A.method)
        def method_a(self):
            return "A"

        @mutobj.impl(C.method)
        def method_c(self):
            return "C"

        assert A().method() == "A"
        assert B().method() == "A"  # B 继承 A 的实现
        assert C().method() == "C"  # C 有自己的实现

    def test_classmethod_inheritance_collision(self):
        """classmethod 继承冲突修复"""
        class Base(mutobj.Declaration):
            @classmethod
            def create(cls) -> str: ...

        class ImplA(Base):
            pass

        class ImplB(Base):
            pass

        @mutobj.impl(ImplA.create)
        def create_a(cls):
            return "created A"

        @mutobj.impl(ImplB.create)
        def create_b(cls):
            return "created B"

        assert ImplA.create() == "created A"
        assert ImplB.create() == "created B"

    def test_staticmethod_inheritance_collision(self):
        """staticmethod 继承冲突修复"""
        class Base(mutobj.Declaration):
            @staticmethod
            def helper() -> str: ...

        class ImplA(Base):
            pass

        class ImplB(Base):
            pass

        @mutobj.impl(ImplA.helper)
        def helper_a():
            return "helper A"

        @mutobj.impl(ImplB.helper)
        def helper_b():
            return "helper B"

        assert ImplA.helper() == "helper A"
        assert ImplB.helper() == "helper B"

    def test_inherited_method_delegates_to_base_without_impl(self):
        """子类未提供 @impl 时，委托给基类实现"""
        class Base(mutobj.Declaration):
            name: str

            def greet(self) -> str: ...

        @mutobj.impl(Base.greet)
        def greet_base(self):
            return f"Hello {self.name}"

        class Child(Base):
            pass

        assert Child(name="World").greet() == "Hello World"
