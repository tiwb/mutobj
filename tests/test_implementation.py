from __future__ import annotations

import pytest

import mutobj


class TestImplementationBridge:

    def test_implementation_api_and_method_bridge(self) -> None:
        class Loader(mutobj.Declaration):
            path: str

            def get(self) -> str: ...

        class LoaderImpl(mutobj.Implementation[Loader]):
            _loaded: str

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

        removed = mutobj.impl_unregister(__name__)

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

        removed = mutobj.impl_unregister(__name__)

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
        with pytest.raises(AttributeError):
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
        # Passing object as impl_cls: isinstance(x, object) is always True,
        # so _lookup_implementation_instance finds any existing impl.
        assert mutobj.implementation_of(loader, object) is not None  # type: ignore[arg-type]

        with pytest.raises(
            LookupError,
            match="No Declaration owner is associated with LoaderImpl instance",
        ):
            mutobj.implementation_owner(unbound_impl)
        with pytest.raises(LookupError, match="No Declaration owner"):
            mutobj.implementation_owner(object())  # type: ignore[arg-type]

        assert plain.value == 1

    def test_impl_property_on_declared_field_raises(self) -> None:
        class Product(mutobj.Declaration):
            price: float

        with pytest.raises(TypeError, match="is a field"):
            class ProductImpl(mutobj.Implementation[Product]):
                @property
                def price(self) -> str:
                    return "x"

    def test_impl_method_on_declared_property_raises(self) -> None:
        class Product(mutobj.Declaration):
            @property
            def label(self) -> str:
                ...

        with pytest.raises(TypeError, match="is a property"):
            class ProductImpl(mutobj.Implementation[Product]):
                def label(self) -> str:
                    return "x"

    def test_impl_property_on_declared_method_raises(self) -> None:
        class Product(mutobj.Declaration):
            def label(self) -> str: ...

        with pytest.raises(TypeError, match="is a method"):
            class ProductImpl(mutobj.Implementation[Product]):
                @property
                def label(self) -> str:
                    return "x"


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


class TestImplementationFieldSystem:
    """验证 Implementation 与 Declaration 共享一致的字段描述符体系。"""

    def test_lazy_default_factory_evaluated_on_first_access(self) -> None:
        """default_factory 首次访问时 lazy 求值，多次访问返回同一对象。"""
        calls: list[int] = []

        def make_dict() -> dict[str, int]:
            calls.append(1)
            return {}

        class Service(mutobj.Declaration):
            def get_cache(self) -> dict[str, int]: ...

        class ServiceImpl(mutobj.Implementation[Service]):
            _cache: dict[str, int] = mutobj.field(default_factory=make_dict)

            def get_cache(self) -> dict[str, int]:
                return self._cache

        svc = Service()
        impl = mutobj.implementation_of(svc, ServiceImpl)
        assert calls == []
        first = impl._cache
        assert calls == [1]
        second = impl._cache
        assert calls == [1]
        assert first is second

    def test_required_field_missing_raises(self) -> None:
        """Impl 必填字段未在 __init__ 中赋值时报 TypeError。"""
        class Loader(mutobj.Declaration):
            path: str

        class LoaderImpl(mutobj.Implementation[Loader]):
            _required: str  # 必填，未在 __init__ 中赋值

        with pytest.raises(TypeError, match="missing field"):
            Loader(path="/x")

    def test_required_field_assigned_in_init_passes(self) -> None:
        """必填字段在 __init__ 中赋值后通过完整性检查。"""
        class Loader(mutobj.Declaration):
            path: str

            def get_loaded(self) -> str: ...

        class LoaderImpl(mutobj.Implementation[Loader]):
            _loaded: str

            def __init__(self, path: str) -> None:
                owner = mutobj.implementation_owner(self)
                mutobj.impl_call_super(Loader.__init__, owner, path)
                self._loaded = f"v:{path}"

            def get_loaded(self) -> str:
                return self._loaded

        loader = Loader(path="/x")
        assert loader.get_loaded() == "v:/x"

    def test_strict_mode_undeclared_setattr_raises(self) -> None:
        """严格模式下，未声明字段的 setattr 报 AttributeError。"""
        class Svc(mutobj.Declaration):
            pass

        class SvcImpl(mutobj.Implementation[Svc]):
            def __init__(self) -> None:
                self._undeclared = 1  # type: ignore[attr-defined]

        with pytest.raises(AttributeError):
            Svc()

    def test_escape_hatch_allows_arbitrary_setattr(self) -> None:
        """无 annotation 时 __slots__ = ("__dict__",) 保留完全自由的 setattr。"""
        class Svc(mutobj.Declaration):
            def get_state(self) -> str: ...

        class SvcImpl(mutobj.Implementation[Svc]):
            __slots__ = ("__dict__",)

            def __init__(self) -> None:
                self._anything = "ok"  # type: ignore[attr-defined]
                self._another = 42  # type: ignore[attr-defined]

            def get_state(self) -> str:
                return f"{self._anything}-{self._another}"  # type: ignore[attr-defined]

        svc = Svc()
        assert svc.get_state() == "ok-42"

    def test_escape_hatch_annotations_still_enforced(self) -> None:
        """有 annotation 时即使带 __dict__，必填字段未赋值仍报错。"""
        class Svc(mutobj.Declaration):
            pass

        class SvcImpl(mutobj.Implementation[Svc]):
            __slots__ = ("__dict__",)
            _required: str  # 声明了 annotation，被处理为 descriptor，未赋值 → missing

        with pytest.raises(TypeError, match="missing field"):
            Svc()

    def test_escape_hatch_hybrid_declared_and_undeclared(self) -> None:
        """声明字段走 descriptor，未声明走 __dict__，两者共存。"""
        class Svc(mutobj.Declaration):
            def get_state(self) -> str: ...

        class SvcImpl(mutobj.Implementation[Svc]):
            __slots__ = ("__dict__",)
            _declared: str = "default"  # 声明字段 → descriptor → __mutobj_storage__

            def __init__(self) -> None:
                self._undeclared = "dynamic"  # 未声明 → __dict__
                self._declared = "override"    # 声明字段 → descriptor

            def get_state(self) -> str:
                return f"{self._declared}-{self._undeclared}"  # type: ignore[attr-defined]

        svc = Svc()
        assert svc.get_state() == "override-dynamic"
