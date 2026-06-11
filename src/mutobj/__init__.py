"""
mutobj - Mutable Object Declaration

支持将类拆分到多个文件中编写（声明与实现分离）
"""

from .core._fields import (
    FieldInfo,
    MISSING,
    field,
    field_default,
    field_info,
    fields,
)
from .core._declaration import (
    Declaration,
    get_declaration_doc,
    get_declaration_func,
)
from .core._extensions import (
    Extension,
    extension_types,
    extensions,
)
from .core._implementation import (
    Implementation,
    implementation_class,
    implementation_of,
    implementation_owner,
)
from .core._discovery import (
    discover_subclasses,
    resolve_class,
    get_registry_generation,
)
from .core._impls import (
    call_super_impl,
    impl,
    impl_call_super,
    impl_chain,
    impl_has,
    impl_has_override,
    impl_is_inherited,
    impl_is_own,
    impl_meta,
    impl_meta_of,
    register_module_impls,
    unregister_module_impls,
)

__version__ = "0.9.999"
__all__ = [
    "Declaration",
    "Extension",
    "Implementation",
    "impl",
    "impl_call_super",
    "call_super_impl",
    "impl_has",
    "impl_has_override",
    "impl_is_own",
    "impl_is_inherited",
    "impl_chain",
    "impl_meta",
    "impl_meta_of",
    "field",
    "MISSING",
    "FieldInfo",
    "register_module_impls",
    "unregister_module_impls",
    "discover_subclasses",
    "get_registry_generation",
    "resolve_class",
    "extensions",
    "extension_types",
    "implementation_class",
    "implementation_of",
    "implementation_owner",
    "get_declaration_func",
    "get_declaration_doc",
    "field_default",
    "field_info",
    "fields",
]
