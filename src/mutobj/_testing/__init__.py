# 本模块导出仅供测试 / lint / reload 等内省工具使用的内部接口。
# 所有导出均非 SemVer 保护，随时可能变更。终端用户代码不应依赖此模块。
"""mutobj internal testing / introspection APIs.

Exports in this module are **NOT SemVer protected**. They exist solely for
L2 contract testing and internal tooling (lint, reload, unregister).
End-user code MUST NOT import from here.
"""

from ..core._discovery import class_registry
from ..core._fields import AttributeDescriptor

__all__ = [
    "clear_mutobj_class",
    "cls_has_own_descriptor",
    "is_registered",
    "unregister_class",
]


def cls_has_own_descriptor(cls: type, name: str) -> bool:
    """True if cls.__dict__[name] is an AttributeDescriptor (not inherited).

    Unlike ``fields()`` which walks the MRO, this checks only the class's own
    ``__dict__``.  Exists solely for L2 tests that need to distinguish "this
    class created its own descriptor" from "this class inherited one".
    """
    return isinstance(cls.__dict__.get(name), AttributeDescriptor)


def is_registered(cls: type) -> bool:
    """True if *cls* is present in the global class registry under its
    ``(__module__, __qualname__)`` key.
    """
    key = (cls.__module__, cls.__qualname__)
    return class_registry.get(key) is cls


def clear_mutobj_class(method: object) -> None:
    """Delete ``__mutobj_class__`` from *method*, simulating a corrupted
    stub that triggers the fallback resolution path.

    Exists solely for L2 tests that verify ambiguous-target error handling
    when ``__mutobj_class__`` is missing.
    """
    try:
        delattr(method, "__mutobj_class__")
    except AttributeError:
        pass


def unregister_class(cls: type) -> None:
    """Remove *cls* from the global class registry.

    Simulates module unload for L2 discovery / resolve tests.
    Safe to call even if *cls* is not registered.
    """
    key = (cls.__module__, cls.__qualname__)
    class_registry.pop(key, None)
