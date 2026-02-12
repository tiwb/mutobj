"""测试 pyic 继承支持"""

import pytest
import pyic


class TestBasicInheritance:
    """测试基本继承"""

    def test_subclass_inherits_attributes(self):
        """测试子类继承父类属性"""
        class Animal(pyic.Object):
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
        class Vehicle(pyic.Object):
            brand: str

            def start(self) -> str:
                """启动"""
                ...

        @pyic.impl(Vehicle.start)
        def start(self: Vehicle) -> str:
            return f"{self.brand} started"

        class Car(Vehicle):
            model: str

        c = Car(brand="Toyota", model="Camry")
        assert c.start() == "Toyota started"

    def test_multi_level_inheritance(self):
        """测试多级继承"""
        class A(pyic.Object):
            a: int

            def method_a(self) -> int:
                ...

        @pyic.impl(A.method_a)
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
        class Animal(pyic.Object):
            name: str

            def speak(self) -> str:
                ...

        @pyic.impl(Animal.speak)
        def animal_speak(self: Animal) -> str:
            return f"{self.name} makes a sound"

        class Dog(Animal):
            def speak(self) -> str:
                ...

        @pyic.impl(Dog.speak)
        def dog_speak(self: Dog) -> str:
            return f"{self.name} barks"

        a = Animal(name="Generic")
        d = Dog(name="Buddy")

        assert a.speak() == "Generic makes a sound"
        assert d.speak() == "Buddy barks"

    def test_override_does_not_affect_parent(self):
        """测试子类覆盖不影响父类"""
        class Base(pyic.Object):
            value: int

            def compute(self) -> int:
                ...

        @pyic.impl(Base.compute)
        def base_compute(self: Base) -> int:
            return self.value

        class Derived(Base):
            def compute(self) -> int:
                ...

        @pyic.impl(Derived.compute)
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
        class Person(pyic.Object):
            first_name: str
            last_name: str

            @property
            def full_name(self) -> str:
                ...

        @pyic.impl(Person.full_name.getter)
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
        class Factory(pyic.Object):
            value: int

            @classmethod
            def create(cls, v: int) -> "Factory":
                ...

        @pyic.impl(Factory.create)
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
        class Utils(pyic.Object):
            @staticmethod
            def helper(x: int) -> int:
                ...

        @pyic.impl(Utils.helper)
        def helper(x: int) -> int:
            return x * 2

        class ExtendedUtils(Utils):
            pass

        assert ExtendedUtils.helper(5) == 10


class TestExtensionWithInheritance:
    """测试 Extension 与继承配合"""

    def test_extension_with_inherited_class(self):
        """测试 Extension 与继承类配合"""
        class Animal(pyic.Object):
            name: str

            def greet(self) -> str:
                ...

        class AnimalExt(pyic.Extension[Animal]):
            _count: int = 0

            def __extension_init__(self):
                self._count = 0

            def increment(self):
                self._count += 1

        @pyic.impl(Animal.greet)
        def greet(self: Animal) -> str:
            ext = AnimalExt.of(self)
            ext.increment()
            return f"Hello, I'm {self.name} (called {ext._count} times)"

        class Dog(Animal):
            breed: str

        d = Dog(name="Buddy", breed="Labrador")
        assert d.greet() == "Hello, I'm Buddy (called 1 times)"
        assert d.greet() == "Hello, I'm Buddy (called 2 times)"
