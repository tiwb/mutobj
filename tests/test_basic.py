"""基础测试 - 验证包可以正常导入"""

import pytest


def test_import_mutobj():
    """测试 mutobj 包可以导入"""
    import mutobj
    assert hasattr(mutobj, "Declaration")
    assert hasattr(mutobj, "Extension")
    assert hasattr(mutobj, "impl")




