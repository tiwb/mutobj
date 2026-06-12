"""Tests for DeclarationMeta in-place class redefinition (reload)."""

import pytest
import mutobj
from mutobj._testing import is_registered

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
        assert mutobj.impl_is_own(cls.alpha)

        g2 = _exec_class(
            "class Svc(mutobj.Declaration):\n"
            "    def beta(self) -> str: ...\n"
        )
        cls2 = g2["Svc"]
        assert cls is cls2

        assert mutobj.impl_is_own(cls.beta)

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

    @pytest.mark.l2("首次定义后类被注册")
    def test_first_definition_registers(self):
        g = _exec_class("class Fresh(mutobj.Declaration):\n    pass", "test_fresh_mod")
        cls = g["Fresh"]
        assert is_registered(cls)

        # 端到端验证：注册后类能正常构造实例
        assert isinstance(cls(), cls)

    def test_registries_migrated(self):
        g1 = _exec_class(
            "class Migr(mutobj.Declaration):\n"
            "    x: int\n"
            "    def process(self) -> str: ...\n"
        )
        cls = g1["Migr"]
        assert len(mutobj.impl_chain(cls.process)) > 0

        # Redefine
        g2 = _exec_class(
            "class Migr(mutobj.Declaration):\n"
            "    x: int\n"
            "    y: str\n"
            "    def process(self) -> str: ...\n"
        )
        cls2 = g2["Migr"]
        assert cls is cls2

        # 行为验证：reload 后构造实例并调用方法正常
        assert cls(x=0, y="test").process() is None

    # ———————————————————————— classmethod / staticmethod reload ————————————————————————

    def test_classmethod_stub_survives_reload(self):
        """Reload 后 @classmethod stub 描述符完整，可正常调用和 impl"""
        import types

        g1 = _exec_class(
            "class Svc(mutobj.Declaration):\n"
            "    @classmethod\n"
            "    def factory(cls) -> 'Svc': ...\n"
        )
        cls = g1["Svc"]
        # L1：classmethod 描述符存在 → cls.factory 是 bound method，不是裸函数
        assert isinstance(cls.factory, types.MethodType)

        # Redefine with new method
        g2 = _exec_class(
            "class Svc(mutobj.Declaration):\n"
            "    @classmethod\n"
            "    def factory(cls) -> 'Svc': ...\n"
            "    def extra(self) -> int: ...\n"
        )
        cls2 = g2["Svc"]
        assert cls is cls2
        # L1：reload 后 classmethod 描述符未被解包为裸函数
        assert isinstance(cls.factory, types.MethodType)
        # L1：stub 默认返回 None（类上和实例上均可调用）
        assert cls.factory() is None
        assert cls().factory() is None

        # L1：reload 后仍可注册 impl，验证 __mutobj_class__ 指向正确
        @mutobj.impl(cls.factory)
        def factory_impl(cls_arg: type) -> str:
            return "built"
        assert cls.factory() == "built"

    def test_staticmethod_stub_survives_reload(self):
        """Reload 后 @staticmethod stub 描述符完整，可正常调用"""
        g1 = _exec_class(
            "class Util(mutobj.Declaration):\n"
            "    @staticmethod\n"
            "    def helper(x: int) -> int: ...\n"
        )
        cls = g1["Util"]
        # L1：staticmethod 描述符存在 → 类上直接拿到函数
        assert callable(cls.helper)

        g2 = _exec_class(
            "class Util(mutobj.Declaration):\n"
            "    @staticmethod\n"
            "    def helper(x: int) -> int: ...\n"
            "    def extra(self) -> str: ...\n"
        )
        cls2 = g2["Util"]
        assert cls is cls2
        # L1：reload 后 staticmethod 仍可调用（stub 默认返回 None）
        assert callable(cls.helper)
        assert cls.helper(1) is None

    # ———————————————————————— 字段 descriptor reload ————————————————————————

    def test_reload_updates_field_descriptor_owner(self):
        """Reload 时字段 descriptor 的 owner_cls 更新，字段增删生效"""
        g1 = _exec_class(
            "class Item(mutobj.Declaration):\n"
            "    name: str\n"
            "    count: int\n"
        )
        cls = g1["Item"]
        fields1 = mutobj.fields(cls)
        assert "name" in fields1
        assert "count" in fields1

        g2 = _exec_class(
            "class Item(mutobj.Declaration):\n"
            "    name: str\n"
            "    price: float\n"
        )
        cls2 = g2["Item"]
        assert cls is cls2
        fields2 = mutobj.fields(cls)
        assert "name" in fields2
        assert "price" in fields2
        assert "count" not in fields2
        # 端到端：新字段可正常赋值
        obj = cls(name="test", price=3.14)
        assert obj.price == 3.14

    # ———————————————————————— impl chain 合并 ————————————————————————

    def test_reload_adds_new_stub_method(self):
        """旧类无某 stub，新类新增 stub → old chain 接管 new chain"""
        g1 = _exec_class(
            "class Svc(mutobj.Declaration):\n"
            "    def old(self) -> str: ...\n"
        )
        cls = g1["Svc"]

        g2 = _exec_class(
            "class Svc(mutobj.Declaration):\n"
            "    def old(self) -> str: ...\n"
            "    def new_stub(self) -> int: ...\n"
        )
        cls2 = g2["Svc"]
        assert cls is cls2
        # L2 验证：新 stub 的 impl chain 已接管
        chain = mutobj.impl_chain(cls.new_stub)
        assert len(chain) > 0
        # 端到端：默认实现返回 None
        assert cls().new_stub() is None

    # ———————————————————————— 注册表 ————————————————————————

    def test_reload_class_still_registered(self):
        """Reload 后类仍在注册表中，且能正常构造"""
        g1 = _exec_class(
            "class Reg(mutobj.Declaration):\n    x: int",
            "test_reg_mod",
        )
        cls = g1["Reg"]

        g2 = _exec_class(
            "class Reg(mutobj.Declaration):\n    x: int\n    y: str",
            "test_reg_mod",
        )
        cls2 = g2["Reg"]
        assert cls is cls2
        # 端到端：构造实例正常
        obj = cls(x=1, y="ok")
        assert isinstance(obj, cls)
