"""类级别声明严格化测试 — Declaration / Extension / Implementation"""

import pytest
from typing import ClassVar

import mutobj
from mutobj import field


# ─────────────────────────────────────────────────────────────
# Declaration: 渠道 A — 类体内无 annotation 赋值
# ─────────────────────────────────────────────────────────────

def test_decl_undeclared_data_in_body_raises():
    """Declaration 类体内无 annotation 的数据赋值应抛出 TypeError。"""
    with pytest.raises(TypeError, match="ClassVar"):
        class BadDecl(mutobj.Declaration):  # type: ignore
            value: int = 1
            _cache = {}   # 无 annotation，应拒绝


def test_decl_classvar_in_body_allowed():
    """Declaration 类体内 ClassVar 赋值应正常创建。"""
    class GoodDecl(mutobj.Declaration):
        value: int = 1
        _cache: ClassVar[dict] = {}

    assert GoodDecl._cache == {}
    GoodDecl._cache = {"a": 1}
    assert GoodDecl._cache == {"a": 1}


def test_decl_method_in_body_allowed():
    """Declaration 类体内方法定义应正常。"""
    class WithMethod(mutobj.Declaration):
        value: int = 1

        def helper(self) -> str:
            return f"v={self.value}"

    obj = WithMethod(value=5)
    assert obj.helper() == "v=5"


def test_decl_property_in_body_allowed():
    """Declaration 类体内 @property 应正常。"""
    class WithProp(mutobj.Declaration):
        x: int = 1

        @property
        def doubled(self) -> int:
            return self.x * 2

    obj = WithProp()
    assert obj.doubled == 2


def test_decl_only_annotation_no_value_allowed():
    """Declaration 仅 annotation 无默认值应正常（归入 descriptors）。"""
    class OnlyAnn(mutobj.Declaration):
        name: str

    obj = OnlyAnn(name="hello")
    assert obj.name == "hello"


def test_decl_classvar_without_default_allowed():
    """Declaration ClassVar 无默认值应正常。"""
    class NoDefaultClassVar(mutobj.Declaration):
        _config: ClassVar[dict | None] = None

    assert NoDefaultClassVar._config is None


# ─────────────────────────────────────────────────────────────
# Declaration: 渠道 B — __setattr__ 白名单
# ─────────────────────────────────────────────────────────────

def test_decl_setattr_undeclared_raises():
    """Declaration 类创建后任意 setattr 应拒绝。"""
    class MyDecl(mutobj.Declaration):
        value: int = 1

    with pytest.raises(TypeError, match="ClassVar"):
        MyDecl.oops = 42


def test_decl_setattr_classvar_allowed():
    """Declaration setattr ClassVar 声明的属性应放行。"""
    class MyDecl(mutobj.Declaration):
        value: int = 1
        _state: ClassVar[str] = "init"

    MyDecl._state = "updated"
    assert MyDecl._state == "updated"


def test_decl_setattr_callable_allowed():
    """Declaration setattr 方法/函数应放行。"""
    class MyDecl(mutobj.Declaration):
        value: int = 1

    def new_method(self):
        return self.value * 2

    MyDecl.new_method = new_method
    obj = MyDecl(value=10)
    assert obj.new_method() == 20


def test_decl_setattr_classmethod_allowed():
    """Declaration setattr classmethod 应放行。"""
    class MyDecl(mutobj.Declaration):
        value: int = 1

    @classmethod
    def cm(cls):
        return cls.__name__

    MyDecl.cm = cm
    assert MyDecl.cm() == "MyDecl"


def test_decl_setattr_staticmethod_allowed():
    """Declaration setattr staticmethod 应放行。"""
    class MyDecl(mutobj.Declaration):
        value: int = 1

    @staticmethod
    def sm():
        return 42

    MyDecl.sm = sm
    assert MyDecl.sm() == 42


def test_decl_setattr_property_allowed():
    """Declaration setattr property 应放行。"""
    class MyDecl(mutobj.Declaration):
        value: int = 1

    MyDecl.computed = property(lambda self: self.value + 1)
    obj = MyDecl(value=5)
    assert obj.computed == 6


def test_decl_setattr_overwrite_existing():
    """Declaration setattr 覆盖已有 ClassVar/方法应放行。"""
    class MyDecl(mutobj.Declaration):
        value: int = 1
        _mode: ClassVar[str] = "a"

    MyDecl._mode = "b"
    assert MyDecl._mode == "b"


def test_decl_setattr_descriptor_allowed():
    """Declaration setattr AttributeDescriptor 应放行（字段覆盖）。"""
    class MyDecl(mutobj.Declaration):
        value: int = 1

    MyDecl.value = field(default=99)
    assert MyDecl().value == 99


def test_decl_setattr_dunder_allowed():
    """Declaration setattr 基础设施 dunder 应放行。"""
    class MyDecl(mutobj.Declaration):
        value: int = 1

    MyDecl.__doc__ = "updated doc"
    assert MyDecl.__doc__ == "updated doc"


# ─────────────────────────────────────────────────────────────
# Extension: 渠道 A + 渠道 B
# ─────────────────────────────────────────────────────────────

class _ExtDeclA(mutobj.Declaration):
    name: str = "base"

class _ExtDeclB(mutobj.Declaration):
    name: str = "base"

class _ExtDeclC(mutobj.Declaration):
    name: str = "base"

class _ExtDeclD(mutobj.Declaration):
    name: str = "base"

class _ExtDeclE(mutobj.Declaration):
    name: str = "base"


def test_ext_undeclared_data_in_body_raises():
    """Extension 类体内无 annotation 数据应拒绝。"""
    with pytest.raises(TypeError, match="ClassVar"):
        class BadExt(mutobj.Extension[_ExtDeclA]):  # type: ignore
            extra: int = 1
            _bad = "no annotation"  # 应拒绝


def test_ext_classvar_in_body_allowed():
    """Extension 类体内 ClassVar 数据应正常。"""
    class GoodExt(mutobj.Extension[_ExtDeclB]):
        extra: int = 1
        _config: ClassVar[str] = "default"

    assert GoodExt._config == "default"


def test_ext_setattr_undeclared_raises():
    """Extension 类创建后任意 setattr 应拒绝。"""
    class MyExt(mutobj.Extension[_ExtDeclC]):
        extra: int = 1

    with pytest.raises(TypeError, match="ClassVar"):
        MyExt.oops = 99


def test_ext_setattr_classvar_allowed():
    """Extension setattr ClassVar 应放行。"""
    class MyExt(mutobj.Extension[_ExtDeclD]):
        extra: int = 1
        _state: ClassVar[int] = 0

    MyExt._state = 42
    assert MyExt._state == 42


def test_ext_method_allowed():
    """Extension 类体内方法应正常。"""
    class MyExt(mutobj.Extension[_ExtDeclE]):
        extra: int = 1

        def helper(self) -> str:
            return self.extra * "x"

    decl = _ExtDeclE(name="test")
    ext = MyExt.get_or_create(decl)
    ext.extra = 3
    assert ext.helper() == "xxx"


# ─────────────────────────────────────────────────────────────
# Implementation: 渠道 A + 渠道 B
# ─────────────────────────────────────────────────────────────

class _ImplDeclA(mutobj.Declaration):
    pass

class _ImplDeclB(mutobj.Declaration):
    pass

class _ImplDeclC(mutobj.Declaration):
    pass

class _ImplDeclD(mutobj.Declaration):
    pass


def test_impl_undeclared_data_in_body_raises():
    """Implementation 类体内无 annotation 数据应拒绝。"""
    with pytest.raises(TypeError, match="ClassVar"):
        class BadImpl(mutobj.Implementation[_ImplDeclA]):  # type: ignore
            _bad = "no annotation"


def test_impl_classvar_in_body_allowed():
    """Implementation 类体内 ClassVar 数据应正常。"""
    class GoodImpl(mutobj.Implementation[_ImplDeclB]):
        _config: ClassVar[str] = "impl_default"

    assert GoodImpl._config == "impl_default"


def test_impl_setattr_undeclared_raises():
    """Implementation 类创建后任意 setattr 应拒绝。"""
    class MyImpl(mutobj.Implementation[_ImplDeclC]):
        pass

    with pytest.raises(TypeError, match="ClassVar"):
        MyImpl.oops = "bad"


def test_impl_setattr_classvar_allowed():
    """Implementation setattr ClassVar 应放行。"""
    class MyImpl(mutobj.Implementation[_ImplDeclD]):
        _mode: ClassVar[str] = "a"

    MyImpl._mode = "b"
    assert MyImpl._mode == "b"
