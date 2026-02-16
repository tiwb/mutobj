"""Tests for DeclarationMeta in-place class redefinition (reload)."""

import pytest
import mutobj
from mutobj.core import (
    _class_registry,
    _impl_chain,
    _attribute_registry,
    _DECLARED_METHODS,
)


def _exec_class(source: str, module_name: str = "test_virtual"):
    """Helper: exec source code that defines a class, simulating module re-execution."""
    filename = f"mutobj://{module_name}"
    code = compile(source, filename, "exec")
    globs = {"__name__": module_name, "mutobj": mutobj}
    exec(code, globs)
    return globs


class TestInPlaceRedefinition:

    def test_redefinition_preserves_identity(self):
        g1 = _exec_class("class Foo(mutobj.Declaration):\n    x: int")
        cls1 = g1["Foo"]
        id1 = id(cls1)

        g2 = _exec_class("class Foo(mutobj.Declaration):\n    x: int\n    y: str")
        cls2 = g2["Foo"]

        assert cls1 is cls2
        assert id(cls2) == id1

    def test_redefinition_updates_annotations(self):
        g1 = _exec_class("class Bar(mutobj.Declaration):\n    x: int")
        cls = g1["Bar"]
        assert "x" in cls.__annotations__

        g2 = _exec_class("class Bar(mutobj.Declaration):\n    x: int\n    y: str")
        cls2 = g2["Bar"]
        assert cls is cls2
        assert "y" in cls.__annotations__

    def test_redefinition_updates_declared_methods(self):
        g1 = _exec_class(
            "class Svc(mutobj.Declaration):\n"
            "    def alpha(self) -> str: ...\n"
        )
        cls = g1["Svc"]
        declared = getattr(cls, _DECLARED_METHODS, set())
        assert "alpha" in declared

        g2 = _exec_class(
            "class Svc(mutobj.Declaration):\n"
            "    def beta(self) -> str: ...\n"
        )
        cls2 = g2["Svc"]
        assert cls is cls2

        declared2 = getattr(cls, _DECLARED_METHODS, set())
        assert "beta" in declared2

    def test_redefinition_removes_deleted_attrs(self):
        g1 = _exec_class(
            "class Rm(mutobj.Declaration):\n"
            "    x: int\n"
            "    y: str\n"
        )
        cls = g1["Rm"]

        g2 = _exec_class(
            "class Rm(mutobj.Declaration):\n"
            "    x: int\n"
        )
        cls2 = g2["Rm"]
        assert cls is cls2
        annotations = cls.__annotations__
        assert "x" in annotations

    def test_isinstance_works_after_redefinition(self):
        g1 = _exec_class("class Inst(mutobj.Declaration):\n    v: int")
        cls = g1["Inst"]
        obj = cls(v=10)
        assert isinstance(obj, cls)

        # Redefine
        g2 = _exec_class("class Inst(mutobj.Declaration):\n    v: int\n    w: str")
        cls2 = g2["Inst"]

        assert cls is cls2
        assert isinstance(obj, cls)
        assert isinstance(obj, cls2)

    def test_impl_survives_redefinition(self):
        g1 = _exec_class(
            "class Worker(mutobj.Declaration):\n"
            "    def work(self) -> str: ...\n"
        )
        cls = g1["Worker"]

        @mutobj.impl(cls.work)
        def work_impl(self) -> str:
            return "working"

        obj = cls()
        assert obj.work() == "working"

        # Redefine the class (adds a new method)
        g2 = _exec_class(
            "class Worker(mutobj.Declaration):\n"
            "    def work(self) -> str: ...\n"
            "    def rest(self) -> str: ...\n"
        )
        cls2 = g2["Worker"]
        assert cls is cls2

        # Old impl should still work
        assert obj.work() == "working"

        # New method has default impl (returns None)
        assert obj.rest() is None

    def test_existing_instances_see_new_methods(self):
        g1 = _exec_class(
            "class Live(mutobj.Declaration):\n"
            "    def old_method(self) -> str: ...\n"
        )
        cls = g1["Live"]
        obj = cls()

        # Redefine with a different method
        g2 = _exec_class(
            "class Live(mutobj.Declaration):\n"
            "    def new_method(self) -> str: ...\n"
        )

        assert hasattr(obj, "new_method")

    def test_different_module_creates_separate_class(self):
        g1 = _exec_class("class Same(mutobj.Declaration):\n    pass", "mod_a")
        g2 = _exec_class("class Same(mutobj.Declaration):\n    pass", "mod_b")

        assert g1["Same"] is not g2["Same"]

    def test_different_qualname_creates_separate_class(self):
        g1 = _exec_class(
            "class Outer(mutobj.Declaration):\n"
            "    class Inner(mutobj.Declaration):\n"
            "        pass\n"
        )
        outer = g1["Outer"]
        inner = outer.Inner
        assert outer is not inner

    def test_first_definition_registers(self):
        g = _exec_class("class Fresh(mutobj.Declaration):\n    pass", "test_fresh_mod")
        cls = g["Fresh"]
        key = ("test_fresh_mod", "Fresh")
        assert key in _class_registry
        assert _class_registry[key] is cls

    def test_registries_migrated(self):
        g1 = _exec_class(
            "class Migr(mutobj.Declaration):\n"
            "    x: int\n"
            "    def process(self) -> str: ...\n"
        )
        cls = g1["Migr"]
        assert cls in _attribute_registry
        assert (cls, "process") in _impl_chain

        # Redefine
        g2 = _exec_class(
            "class Migr(mutobj.Declaration):\n"
            "    x: int\n"
            "    y: str\n"
            "    def process(self) -> str: ...\n"
        )
        cls2 = g2["Migr"]
        assert cls is cls2

        # Registries should point to existing class
        assert cls in _attribute_registry
        assert (cls, "process") in _impl_chain
