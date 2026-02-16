"""
mutobj - Mutable Object Declaration

支持将类拆分到多个文件中编写（声明与实现分离）
"""

from mutobj.core import Declaration, Extension, impl, unregister_module_impls

__version__ = "0.2.0"
__all__ = ["Declaration", "Extension", "impl", "unregister_module_impls"]
