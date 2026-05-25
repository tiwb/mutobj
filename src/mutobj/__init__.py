"""
mutobj - Mutable Object Declaration

支持将类拆分到多个文件中编写（声明与实现分离）
"""

from mutobj.core import Declaration, Extension, impl, impl_call_super, call_super_impl, impl_has, impl_has_override, \
    impl_is_own, impl_is_inherited, impl_chain, impl_meta, impl_meta_of, field, MISSING, \
    register_module_impls, unregister_module_impls, \
    discover_subclasses, get_registry_generation, resolve_class, extensions, extension_types, get_declaration_func, get_declaration_doc, \
    field_default, field_info, fields

__version__ = "0.9.999"
__all__ = ["Declaration", "Extension", "impl", "impl_call_super", "call_super_impl", "impl_has", "impl_has_override",
            "impl_is_own", "impl_is_inherited", "impl_chain", "impl_meta", "impl_meta_of",
            "field", "MISSING", "register_module_impls",
            "unregister_module_impls", "discover_subclasses", "get_registry_generation", "resolve_class",
            "extensions", "extension_types", "get_declaration_func", "get_declaration_doc", "field_default", "field_info", "fields"]
