"""
mutobj - Mutable Object Declaration

支持将类拆分到多个文件中编写（声明与实现分离）
"""

from .core._fields import (
    FieldInfo,
    field,
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
    extension_base,
    extensions,
    extension_types,
)
from .core._implementation import (
    Implementation,
    implementation_class,
    implementation_of,
    implementation_owner,
)
from .core._impls import (
    ImplChainInfo,
    impl,
    impl_call_super,
    impl_chain,
    impl_has_override,
    impl_is_inherited,
    impl_is_own,
    impl_meta,
    impl_meta_of,
    impl_unregister,
)
from .core._discovery import (
    discover_subclasses,
    get_registry_generation,
    resolve_class,
)
from .core._typing_utils import (
    annotation_match,
    annotation_resolve,
)

__version__ = "0.9.999"
__all__ = [
    "FieldInfo",
    "field",
    "field_info",
    "fields",
    "Declaration",
    "get_declaration_doc",
    "get_declaration_func",
    "Extension",
    "extension_base",
    "extensions",
    "extension_types",
    "Implementation",
    "implementation_class",
    "implementation_of",
    "implementation_owner",
    "ImplChainInfo",
    "impl",
    "impl_call_super",
    "impl_has_override",
    "impl_is_own",
    "impl_is_inherited",
    "impl_chain",
    "impl_meta",
    "impl_meta_of",
    "impl_unregister",
    "discover_subclasses",
    "get_registry_generation",
    "resolve_class",
    "annotation_match",
    "annotation_resolve",
]
