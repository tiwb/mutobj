"""
mutobj - Mutable Object Declaration

支持将类拆分到多个文件中编写（声明与实现分离）
"""

from mutobj.core import Declaration, Extension, impl, field, register_module_impls, unregister_module_impls, \
    discover_subclasses, get_registry_generation, resolve_class

__version__ = "0.2.999"
__all__ = ["Declaration", "Extension", "impl", "field", "register_module_impls", "unregister_module_impls",
           "discover_subclasses", "get_registry_generation", "resolve_class"]
