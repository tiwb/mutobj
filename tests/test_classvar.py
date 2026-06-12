"""ClassVar 属性支持测试"""

import sys
import types

import pytest
from typing import ClassVar

import mutobj
from mutobj import FieldInfo


def _exec_module(source: str, module_name: str, *, keep: bool = False) -> dict:
    """Exec source in a real sys.modules module so string aliases can resolve."""
    mod = types.ModuleType(module_name)
    sys.modules[module_name] = mod
    try:
        exec(source, mod.__dict__)
        return mod.__dict__
    finally:
        if not keep:
            sys.modules.pop(module_name, None)


class TestClassVarBasic:
    """ClassVar 基本行为：不被包成描述符"""

    def test_classvar_is_plain_class_attr(self):
        class Foo(mutobj.Declaration):
            _app: ClassVar[str | None] = None
            name: str = "foo"

        # ClassVar 字段：类级读直接返回值，不是描述符
        assert Foo._app is None
        assert "_app" not in mutobj.fields(Foo)

        # 正常字段：类级读仍是描述符
        assert isinstance(Foo.name, FieldInfo)

    def test_classvar_instance_falls_back_to_class(self):
        class Foo(mutobj.Declaration):
            _app: ClassVar[str | None] = None

        f = Foo()
        assert f._app is None

    def test_classvar_not_inattribute_registry(self):
        class Foo(mutobj.Declaration):
            _app: ClassVar[int] = 0
            name: str = "foo"

        assert "_app" not in mutobj.fields(Foo)
        assert "name" in mutobj.fields(Foo)

    def test_classvar_without_default(self):
        class Foo(mutobj.Declaration):
            _app: ClassVar[int | None]

        assert not hasattr(Foo, "app")

    def test_classvar_default_factory_not_allowed(self):
        with pytest.raises(TypeError):
            class Foo(mutobj.Declaration):  # type: ignore[call-arg]
                _items: ClassVar[list] = mutobj.field(default_factory=list)

    def test_classvar_without_type_argument(self):
        """直接 ClassVar 不带类型参数"""
        class Foo(mutobj.Declaration):
            _tag: ClassVar = "v1"  # type: ignore[valid-type]

        assert Foo._tag == "v1"
        assert "_tag" not in mutobj.fields(Foo)


class TestClassVarClassLevelAssignment:
    """ClassVar 类级赋值：所有实例看到新值"""

    def test_assign_propagates_to_all_instances(self):
        class Foo(mutobj.Declaration):
            _config: ClassVar[dict | None] = None

        f1 = Foo()
        f2 = Foo()

        Foo._config = {"key": "value"}

        assert Foo._config == {"key": "value"}
        assert f1._config == {"key": "value"}
        assert f2._config == {"key": "value"}

    def test_assign_before_instance_creation(self):
        class Foo(mutobj.Declaration):
            _app: ClassVar[str | None] = None

        Foo._app = "injected"
        f = Foo()
        assert f._app == "injected"

    def test_assign_to_none_classvar_that_had_no_default(self):
        class Foo(mutobj.Declaration):
            _app: ClassVar[str | None]

        Foo._app = "set_after_creation"
        assert Foo._app == "set_after_creation"
        f = Foo()
        assert f._app == "set_after_creation"


class TestClassVarStringAnnotation:
    """from __future__ import annotations 场景 — 字符串形态 ClassVar"""

    def test_unqualified_classvar_string(self):
        ns = _exec_module(
            "from __future__ import annotations\n"
            "from typing import ClassVar\n"
            "import mutobj\n"
            "class Foo(mutobj.Declaration):\n"
            "    _key: ClassVar[str | None] = None\n"
            "    name: str = 'f'\n",
            "test_classvar_unqualified",
        )
        Foo = ns["Foo"]
        assert Foo._key is None
        assert "_key" not in mutobj.fields(Foo)
        assert isinstance(Foo.name, FieldInfo)

    def test_qualified_typing_classvar_string(self):
        ns = _exec_module(
            "from __future__ import annotations\n"
            "import typing\n"
            "import mutobj\n"
            "class Foo(mutobj.Declaration):\n"
            "    _key: typing.ClassVar[str | None] = None\n",
            "test_classvar_typing_qualified",
        )
        Foo = ns["Foo"]
        assert Foo._key is None
        assert "_key" not in mutobj.fields(Foo)

    def test_qualified_typing_classvar_string_without_import(self):
        ns = _exec_module(
            "from __future__ import annotations\n"
            "import mutobj\n"
            "class Foo(mutobj.Declaration):\n"
            "    _key: typing.ClassVar[str | None] = None\n",
            "test_classvar_typing_not_bound",
        )
        Foo = ns["Foo"]
        assert Foo._key is None
        assert "_key" not in mutobj.fields(Foo)

    def test_module_alias_classvar_string(self):
        ns = _exec_module(
            "from __future__ import annotations\n"
            "import typing as t\n"
            "import mutobj\n"
            "class Foo(mutobj.Declaration):\n"
            "    _key: t.ClassVar[str | None] = None\n",
            "test_classvar_module_alias",
        )
        Foo = ns["Foo"]
        assert Foo._key is None
        assert "_key" not in mutobj.fields(Foo)

    def test_classvar_alias(self):
        """别名（如 from typing import ClassVar as CV）— 非 string 形态可识别"""
        from typing import ClassVar as _CV

        class Foo(mutobj.Declaration):
            _key: _CV[int] = 0  # type: ignore[name-defined, valid-type]

        assert Foo._key == 0
        assert "_key" not in mutobj.fields(Foo)

    def test_classvar_alias_string(self):
        ns = _exec_module(
            "from __future__ import annotations\n"
            "from typing import ClassVar as CV\n"
            "import mutobj\n"
            "class Foo(mutobj.Declaration):\n"
            "    _key: CV[int] = 0\n",
            "test_classvar_alias_string",
        )
        Foo = ns["Foo"]
        assert Foo._key == 0
        assert "_key" not in mutobj.fields(Foo)


class TestClassVarInheritance:
    """ClassVar 继承行为：子类不降级"""

    def test_subclass_inherits_classvar_as_is(self):
        class Parent(mutobj.Declaration):
            _app: ClassVar[str | None] = None
            name: str = "parent"

        class Child(Parent):
            pass

        # 子类继承 ClassVar — 仍是普通类属性
        assert Child._app is None
        assert "_app" not in mutobj.fields(Child)

        # 赋值传播
        Child._app = "child_val"
        c = Child()
        assert c._app == "child_val"
        assert Parent._app is None  # 不影响父类

    def test_subclass_unannotated_override_keeps_classvar(self):
        """子类用无注解赋值覆盖父类 ClassVar — 不降级为描述符"""
        class Parent(mutobj.Declaration):
            _app: ClassVar[str | None] = None
            name: str = "parent"

        class Child(Parent):
            _app = "child_default"  # 无注解覆盖

        assert Child._app == "child_default"
        assert "_app" not in mutobj.fields(Child)

    def test_subclass_annotated_but_not_classvar_not_downgraded(self):
        """子类用注解但非 ClassVar 覆盖父 ClassVar — 仍保持 ClassVar"""
        class Parent(mutobj.Declaration):
            _app: ClassVar[str | None] = None

        class Child(Parent):
            _app: str = "child"  # 意图覆盖但忘了写 ClassVar

        assert Child._app == "child"
        assert "_app" not in mutobj.fields(Child)

    def test_subclass_explicit_classvar_override(self):
        """子类显式标注 ClassVar 覆盖 — 正常"""
        class Parent(mutobj.Declaration):
            _app: ClassVar[int] = 0

        class Child(Parent):
            _app: ClassVar[int] = 42

        assert Child._app == 42
        assert "_app" not in mutobj.fields(Child)

    def test_subclass_value_override_propagates(self):
        class Parent(mutobj.Declaration):
            _ready: ClassVar[bool] = False

        class Child(Parent):
            _ready: ClassVar[bool] = True

        p = Parent()
        c = Child()
        Parent._ready = False
        Child._ready = False

        Parent._ready = True
        assert p._ready is True
        assert c._ready is False  # 子类独立

    def test_cross_module_string_alias_parent_not_downgraded(self):
        parent_ns = _exec_module(
            "from __future__ import annotations\n"
            "from typing import ClassVar as CV\n"
            "import mutobj\n"
            "class Parent(mutobj.Declaration):\n"
            "    app: CV[str | None] = None\n",
            "test_classvar_parent_mod",
            keep=True,
        )
        try:
            Parent = parent_ns["Parent"]

            child_ns = _exec_module(
                "import mutobj\n"
                "from test_classvar_parent_mod import Parent\n"
                "class Child(Parent):\n"
                "    app: str = 'child'\n",
                "test_classvar_child_mod",
            )
            Child = child_ns["Child"]
            assert Child.app == "child"
            assert "app" not in mutobj.fields(Child)
        finally:
            sys.modules.pop("test_classvar_parent_mod", None)


class TestClassVarCoexistWithFields:
    """ClassVar 与普通字段共存"""

    def test_coexist_in_same_class(self):
        class App(mutobj.Declaration):
            config_file: ClassVar[str] = "/etc/app.conf"
            name: str = "default"
            port: int = 8080
            debug: ClassVar[bool] = False

        # ClassVar 字段不是描述符
        assert App.config_file == "/etc/app.conf"
        assert App.debug is False
        assert "config_file" not in mutobj.fields(App)
        assert "debug" not in mutobj.fields(App)

        # 普通字段是描述符
        assert isinstance(App.name, FieldInfo)
        assert isinstance(App.port, FieldInfo)

    def test_classvar_assignment_does_not_cause_descriptor_rebuild(self):
        """ClassVar 赋值走正常 Python __setattr__，不触发描述符重建"""
        class App(mutobj.Declaration):
            _ready: ClassVar[bool] = False

        # 类级赋值应该直接设置，不经过 DeclarationMeta.__setattr__ 的描述符路径
        App._ready = True
        assert App._ready is True
        assert "_ready" not in mutobj.fields(App)


class TestClassVarReload:
    """ClassVar 与 in-place reload/redefinition 的兼容性"""

    def _redefine(self, source: str, module_name: str) -> dict:
        globs = {"__name__": module_name, "mutobj": mutobj}
        exec(compile(source, f"mutobj://{module_name}", "exec"), globs)
        return globs

    def test_redefinition_field_to_classvar_removes_descriptor(self):
        g1 = self._redefine(
            "class ReloadClassVar(mutobj.Declaration):\n"
            "    x: int = 1\n",
            "test_classvar_reload_field_to_classvar",
        )
        cls = g1["ReloadClassVar"]
        assert isinstance(cls.x, FieldInfo)

        g2 = self._redefine(
            "from typing import ClassVar\n"
            "class ReloadClassVar(mutobj.Declaration):\n"
            "    x: ClassVar[int] = 2\n",
            "test_classvar_reload_field_to_classvar",
        )
        cls2 = g2["ReloadClassVar"]
        assert cls2 is cls
        assert cls.x == 2
        assert "x" not in mutobj.fields(cls)
        assert cls().x == 2

    def test_redefinition_classvar_to_field_creates_descriptor(self):
        g1 = self._redefine(
            "from typing import ClassVar\n"
            "class ReloadField(mutobj.Declaration):\n"
            "    x: ClassVar[int] = 1\n",
            "test_classvar_reload_classvar_to_field",
        )
        cls = g1["ReloadField"]
        assert cls.x == 1
        assert "x" not in mutobj.fields(cls)

        g2 = self._redefine(
            "class ReloadField(mutobj.Declaration):\n"
            "    x: int = 2\n",
            "test_classvar_reload_classvar_to_field",
        )
        cls2 = g2["ReloadField"]
        assert cls2 is cls
        assert isinstance(cls.x, FieldInfo)
        assert "x" in mutobj.fields(cls)
        assert cls().x == 2

    def test_redefinition_classvar_default_updates_plain_value(self):
        g1 = self._redefine(
            "from typing import ClassVar\n"
            "class ReloadClassAttr(mutobj.Declaration):\n"
            "    x: ClassVar[int] = 1\n",
            "test_classvar_reload_default",
        )
        cls = g1["ReloadClassAttr"]

        g2 = self._redefine(
            "from typing import ClassVar\n"
            "class ReloadClassAttr(mutobj.Declaration):\n"
            "    x: ClassVar[int] = 3\n",
            "test_classvar_reload_default",
        )
        cls2 = g2["ReloadClassAttr"]
        assert cls2 is cls
        assert cls.x == 3
        assert cls().x == 3
