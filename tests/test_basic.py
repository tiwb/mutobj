"""基础测试 - 验证包可以正常导入"""

import pytest


def test_import_pyic():
    """测试 pyic 包可以导入"""
    import pyic
    assert hasattr(pyic, "Object")
    assert hasattr(pyic, "Extension")
    assert hasattr(pyic, "impl")


def test_version():
    """测试版本号"""
    import pyic
    assert pyic.__version__ == "0.1.0"
