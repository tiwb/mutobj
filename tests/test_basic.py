"""基础测试 - 验证包可以正常导入"""

import pytest


def test_import_mutobj():
    """测试 mutobj 包可以导入"""
    import mutobj
    assert hasattr(mutobj, "Declaration")
    assert hasattr(mutobj, "Extension")
    assert hasattr(mutobj, "impl")
    assert hasattr(mutobj, "register_module_impls")



def test_register_module_impls_is_noop():
    """测试 register_module_impls 为空操作，不抛出异常"""
    import types
    import mutobj
    dummy_module = types.ModuleType("dummy")
    mutobj.register_module_impls(dummy_module)
    mutobj.register_module_impls(None)
