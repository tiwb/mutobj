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
                assert owner is not None
                mutobj.impl_call_super(Loader.__init__, owner, path)
                self._loaded = f"loaded:{path}"

            def get(self) -> str:
                return self._loaded

        loader = Loader(path="/tmp/data")
        impl = mutobj.implementation_of(loader, LoaderImpl)

        assert mutobj.implementation_class(Loader) is LoaderImpl
        assert mutobj.implementation_class(loader) is LoaderImpl
        assert impl is not None
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
                assert owner is not None
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
                assert owner is not None
                return owner.value

        reader = Reader(value=7)
        assert reader.read() == 7

        removed = mutobj.unregister_module_impls(__name__)

        assert removed >= 1
        assert reader.read() is None


class TestImplementationInheritance:

    def test_child_without_own_impl_uses_parent_impl(self) -> None:
        class Base(mutobj.Declaration):
            name: str

            def describe(self) -> str: ...

        class BaseImpl(mutobj.Implementation[Base]):
            def describe(self) -> str:
                owner = mutobj.implementation_owner(self)
                assert owner is not None
                return f"base:{owner.name}"

        class Child(Base):
            level: int = 1

        child = Child(name="demo", level=2)
        impl = mutobj.implementation_of(child)

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
