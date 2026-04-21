"""类级属性运行时赋值测试 — DeclarationMeta.__setattr__"""

import pytest

import mutobj
from mutobj import field
from mutobj.core import _attribute_registry, _ordered_fields_cache, AttributeDescriptor


class _SetAttrBase(mutobj.Declaration):
    name: str = "original"
    count: int = 0


class _SetAttrSub(_SetAttrBase):
    pass


class TestClassLevelAssignment:

    def test_base_runtime_assignment(self):
        _SetAttrBase.name = "updated"
        obj = _SetAttrBase()
        assert obj.name == "updated"
        _SetAttrBase.name = "original"

    def test_sub_runtime_assignment(self):
        _SetAttrSub.count = 99
        s = _SetAttrSub()
        assert s.count == 99
        b = _SetAttrBase()
        assert b.count == 0
        _SetAttrSub.count = 0

    def test_existing_instance_unaffected(self):
        obj = _SetAttrBase()
        assert obj.name == "original"
        _SetAttrBase.name = "changed"
        assert obj.name == "original"
        _SetAttrBase.name = "original"

    def test_field_assignment(self):
        _SetAttrBase.name = field(default="from_field")
        obj = _SetAttrBase()
        assert obj.name == "from_field"
        _SetAttrBase.name = "original"

    def test_field_factory_assignment(self):
        class WithFactory(mutobj.Declaration):
            items: list = field(default_factory=list)

        WithFactory.items = field(default_factory=lambda: [1, 2, 3])
        obj = WithFactory()
        assert obj.items == [1, 2, 3]

    def test_mutable_default_raises(self):
        with pytest.raises(TypeError, match="mutable default"):
            _SetAttrBase.name = []  # type: ignore

    def test_mutable_dict_raises(self):
        with pytest.raises(TypeError, match="mutable default"):
            _SetAttrBase.name = {}  # type: ignore

    def test_non_declared_attr_passthrough(self):
        class MyDecl(mutobj.Declaration):
            value: int = 1

        MyDecl._internal = 42
        assert MyDecl._internal == 42
        MyDecl.new_attr = "hello"
        assert MyDecl.new_attr == "hello"

    def test_descriptor_preserved(self):
        _SetAttrBase.name = "test_value"
        desc = _SetAttrBase.__dict__["name"]
        assert isinstance(desc, AttributeDescriptor)
        assert desc.default == "test_value"
        _SetAttrBase.name = "original"

    def test_attribute_registry_sync(self):
        class Parent(mutobj.Declaration):
            x: int = 10

        class Child(Parent):
            pass

        # 子类 registry 初始不含 x
        child_reg = _attribute_registry.get(Child, {})
        assert "x" not in child_reg

        Child.x = 20
        assert "x" in _attribute_registry[Child]

    def test_ordered_fields_cache_invalidated(self):
        class P(mutobj.Declaration):
            val: str = "a"

        class C(P):
            pass

        # 触发缓存
        C()
        had_cache = C in _ordered_fields_cache

        C.val = "b"
        if had_cache:
            assert C not in _ordered_fields_cache

    def test_descriptor_assignment_passthrough(self):
        desc = AttributeDescriptor("name", str, default="direct")
        _SetAttrBase.name = desc  # type: ignore
        assert _SetAttrBase.__dict__["name"] is desc
        _SetAttrBase.name = "original"
