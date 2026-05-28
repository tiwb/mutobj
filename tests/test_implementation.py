from __future__ import annotations

import pytest

import mutobj


class TestImplementationBridge:

    def test_implementation_api_and_method_bridge(self) -> None:
        class Loader(mutobj.Declaration):
            path: str

            def get(self) -> str: ...

        class LoaderImpl(mutobj.Implementation[Loader]):
            def __init__(self, path: str) -> None:
                owner = mutobj.implementation_owner(self)
                mutobj.impl_call_super(Loader.__init__, owner, path)
                self._loaded = f"loaded:{path}"

            def get(self) -> str:
                return self._loaded

        loader = Loader(path="/tmp/data")
        impl = mutobj.implementation_of(loader, LoaderImpl)

        assert mutobj.implementation_class(Loader) is LoaderImpl
        assert mutobj.implementation_owner(impl) is loader
        assert loader.path == "/tmp/data"
        assert loader.get() == "loaded:/tmp/data"

    def test_explicit_impl_can_wrap_implementation_bridge_in_same_module(self) -> None:
        class Counter(mutobj.Declaration):
            value: int

            def total(self) -> int: ...

        class CounterImpl(mutobj.Implementation[Counter]):
            def total(self) -> int:
                owner = mutobj.implementation_owner(self)
                return owner.value + 1

        @mutobj.impl(Counter.total)
        def total(self: Counter) -> int:
            return mutobj.impl_call_super(Counter.total, self) + 10

        assert Counter(value=2).total() == 13

    def test_unregister_module_removes_implementation_bridge(self) -> None:
        class Reader(mutobj.Declaration):
            value: int

            def read(self) -> int: ...

        class ReaderImpl(mutobj.Implementation[Reader]):
            def read(self) -> int:
                owner = mutobj.implementation_owner(self)
                return owner.value

        reader = Reader(value=7)
        assert reader.read() == 7

        removed = mutobj.unregister_module_impls(__name__)

        assert removed >= 1
        assert reader.read() is None

    def test_property_getter_and_setter_bridge(self) -> None:
        class Product(mutobj.Declaration):
            price: float

            @property
            def display_price(self) -> str:
                ...

            @display_price.setter
            def display_price(self, value: str) -> None:
                ...

        class ProductImpl(mutobj.Implementation[Product]):
            @property
            def display_price(self) -> str:
                owner = mutobj.implementation_owner(self)
                return f"${owner.price:.2f}"

            @display_price.setter
            def display_price(self, value: str) -> None:
                owner = mutobj.implementation_owner(self)
                owner.price = float(value.removeprefix("$"))

        product = Product(price=12.5)

        assert product.display_price == "$12.50"
        product.display_price = "$9.00"
        assert product.price == 9.0

    def test_property_accessor_can_call_super(self) -> None:
        class Product(mutobj.Declaration):
            price: float

            @property
            def label(self) -> str:
                return f"base:{self.price:.1f}"

        class ProductImpl(mutobj.Implementation[Product]):
            @property
            def label(self) -> str:
                owner = mutobj.implementation_owner(self)
                base = mutobj.impl_call_super(Product.label.getter, owner)
                return f"impl:{base}"

        product = Product(price=3.0)

        assert product.label == "impl:base:3.0"

    def test_explicit_impl_can_wrap_property_bridge_in_same_module(self) -> None:
        class Product(mutobj.Declaration):
            price: float

            @property
            def display_price(self) -> str:
                ...

        class ProductImpl(mutobj.Implementation[Product]):
            @property
            def display_price(self) -> str:
                owner = mutobj.implementation_owner(self)
                return f"${owner.price:.2f}"

        @mutobj.impl(Product.display_price.getter)
        def display_price(self: Product) -> str:
            return f"wrapped:{mutobj.impl_call_super(Product.display_price.getter, self)}"

        assert Product(price=2.5).display_price == "wrapped:$2.50"

    def test_unregister_module_removes_property_bridge(self) -> None:
        class Product(mutobj.Declaration):
            value: int

            @property
            def label(self) -> str:
                return f"default:{self.value}"

        class ProductImpl(mutobj.Implementation[Product]):
            @property
            def label(self) -> str:
                owner = mutobj.implementation_owner(self)
                return f"v={owner.value}"

        product = Product(value=5)
        assert product.label == "v=5"

        removed = mutobj.unregister_module_impls(__name__)

        assert removed >= 1
        assert product.label == "default:5"

    def test_undeclared_impl_property_stays_internal(self) -> None:
        class Product(mutobj.Declaration):
            value: int

        class ProductImpl(mutobj.Implementation[Product]):
            @property
            def internal_label(self) -> str:
                owner = mutobj.implementation_owner(self)
                return f"internal:{owner.value}"

        product = Product(value=7)
        impl = mutobj.implementation_of(product, ProductImpl)

        assert impl.internal_label == "internal:7"
        assert not hasattr(Product, "internal_label")
        with pytest.raises(AttributeError, match="internal_label"):
            _ = product.internal_label


class TestImplementationApiErrors:

    def test_public_api_raises_lookup_and_type_errors(self) -> None:
        class Loader(mutobj.Declaration):
            path: str

            def get(self) -> str: ...

        class LoaderImpl(mutobj.Implementation[Loader]):
            def get(self) -> str:
                owner = mutobj.implementation_owner(self)
                return owner.path

        class Reader(mutobj.Declaration):
            value: int

        class ReaderImpl(mutobj.Implementation[Reader]):
            pass

        class Plain(mutobj.Declaration):
            value: int

        loader = Loader(path="/tmp/data")
        plain = Plain(value=1)
        unbound_impl = LoaderImpl.__new__(LoaderImpl)
        loader_impl = mutobj.implementation_of(loader, LoaderImpl)

        assert mutobj.implementation_class(Loader) is LoaderImpl
        assert mutobj.implementation_owner(loader_impl) is loader

        with pytest.raises(LookupError, match="No Implementation class is registered for Plain"):
            mutobj.implementation_class(Plain)
        with pytest.raises(TypeError, match="expects a mutobj.Declaration class"):
            mutobj.implementation_class(loader)

        with pytest.raises(
            LookupError,
            match="Implementation instance for Loader is LoaderImpl, expected ReaderImpl",
        ):
            mutobj.implementation_of(loader, ReaderImpl)
        with pytest.raises(
            LookupError,
            match="No LoaderImpl instance is associated with Plain instance",
        ):
            mutobj.implementation_of(plain, LoaderImpl)
        with pytest.raises(TypeError, match="expects impl_cls to be an Implementation subclass"):
            mutobj.implementation_of(loader, object)  # type: ignore[arg-type]

        with pytest.raises(
            LookupError,
            match="No Declaration owner is associated with LoaderImpl instance",
        ):
            mutobj.implementation_owner(unbound_impl)
        with pytest.raises(TypeError, match="expects impl to be an Implementation instance"):
            mutobj.implementation_owner(object())  # type: ignore[arg-type]

        assert plain.value == 1


class TestImplementationInheritance:

    def test_child_without_own_impl_uses_parent_impl(self) -> None:
        class Base(mutobj.Declaration):
            name: str

            def describe(self) -> str: ...

        class BaseImpl(mutobj.Implementation[Base]):
            def describe(self) -> str:
                owner = mutobj.implementation_owner(self)
                return f"base:{owner.name}"

        class Child(Base):
            level: int = 1

        child = Child(name="demo", level=2)
        impl = mutobj.implementation_of(child, BaseImpl)

        assert isinstance(impl, BaseImpl)
        assert mutobj.implementation_class(Child) is BaseImpl
        assert child.describe() == "base:demo"

    def test_child_impl_must_inherit_parent_impl(self) -> None:
        class Base(mutobj.Declaration):
            def run(self) -> str: ...

        class BaseImpl(mutobj.Implementation[Base]):
            def run(self) -> str:
                return "base"

        class Child(Base):
            pass

        with pytest.raises(TypeError, match="must inherit from"):
            class BadChildImpl(mutobj.Implementation[Child]):
                def run(self) -> str:
                    return "bad"

            _ = BadChildImpl
