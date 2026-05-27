from __future__ import annotations

# pyright: reportPrivateUsage=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportInvalidTypeVarUse=false, reportCallIssue=false, reportUnusedFunction=false, reportUnnecessaryIsInstance=false

import weakref
from typing import Any, Generic, TypeVar, cast

from ._constants import _DECLARATION_CHAIN_HOOKS, _DECLARED_METHODS
from ._declaration import Declaration
from ._impls import _apply_impl, _register_to_chain
from ._state import (
    _implementation_class_registry,
    _implementation_instance_registry,
    _implementation_owner_registry,
    bump_registry_generation,
)

T = TypeVar("T", bound=Declaration)


def _implementation_source_key(impl_cls: type) -> str:
    return f"{impl_cls.__module__}::implementation::{impl_cls.__qualname__}"


def _cleanup_implementation_owner(impl_id: int) -> None:
    _implementation_owner_registry.pop(impl_id, None)


def _resolve_target_class(impl_cls: type) -> type[Declaration] | None:
    for base in impl_cls.__dict__.get("__orig_bases__", ()):
        origin = getattr(base, "__origin__", None)
        if not isinstance(origin, type):
            continue
        if origin is not Implementation and not issubclass(origin, Implementation):
            continue
        args = getattr(base, "__args__", ())
        if not args:
            continue
        target_cls = args[0]
        if not isinstance(target_cls, type) or not issubclass(target_cls, Declaration):
            raise TypeError("Implementation[T] requires a mutobj.Declaration subclass")
        return target_cls
    return None


def _bind_implementation_instance(decl: Declaration, impl: object) -> None:
    previous_impl = _implementation_instance_registry.get(decl)
    if previous_impl is not None:
        _implementation_owner_registry.pop(id(previous_impl), None)

    _implementation_instance_registry[decl] = impl
    _implementation_owner_registry[id(impl)] = (
        weakref.ref(decl),
        weakref.finalize(decl, _cleanup_implementation_owner, id(impl)),
    )


def _implementation_bridge(
    target_cls: type[Declaration],
    impl_cls: type,
    method_name: str,
    impl_method: Any,
    source_key: str,
) -> Any:
    def bridge(decl: Declaration, *args: Any, **kwargs: Any) -> Any:
        impl = implementation_of(decl, impl_cls)
        if impl is None:
            raise RuntimeError(
                f"Implementation instance for {target_cls.__name__} -> "
                f"{impl_cls.__name__} is not available"
            )
        return impl_method(impl, *args, **kwargs)

    bridge.__name__ = method_name
    bridge.__qualname__ = f"{target_cls.__name__}.{method_name}"
    bridge.__module__ = impl_cls.__module__
    bridge.__mutobj_class__ = target_cls
    bridge.__mutobj_source_key__ = source_key
    return bridge


def _register_implementation_methods(
    impl_cls: type,
    target_cls: type[Declaration],
) -> None:
    source_key = _implementation_source_key(impl_cls)
    declared_methods: set[str] = getattr(target_cls, _DECLARED_METHODS, set())
    bridged_methods = declared_methods | _DECLARATION_CHAIN_HOOKS

    for method_name, method_value in impl_cls.__dict__.items():
        if not callable(method_value):
            continue
        method_value.__mutobj_source_key__ = source_key
        if (
            method_name.startswith("__")
            and method_name.endswith("__")
            and method_name not in _DECLARATION_CHAIN_HOOKS
        ):
            continue
        if method_name not in bridged_methods:
            continue
        if not hasattr(target_cls, method_name):
            continue

        bridge = _implementation_bridge(
            target_cls,
            impl_cls,
            method_name,
            method_value,
            source_key,
        )
        became_top = _register_to_chain(target_cls, method_name, bridge, source_key)
        if became_top:
            _apply_impl(target_cls, method_name, bridge)


def _register_implementation_class(
    impl_cls: type,
    target_cls: type[Declaration],
) -> None:
    existing_impl = _implementation_class_registry.get(target_cls)
    if existing_impl is not None and existing_impl is not impl_cls:
        if (
            existing_impl.__module__ != impl_cls.__module__
            or existing_impl.__qualname__ != impl_cls.__qualname__
        ):
            raise TypeError(
                f"{target_cls.__name__} already has an implementation class "
                f"{existing_impl.__module__}.{existing_impl.__qualname__}"
            )

    parent_impl: type | None = None
    for base in target_cls.__mro__[1:]:
        parent_impl = _implementation_class_registry.get(base)
        if parent_impl is not None:
            break
    if parent_impl is not None and not issubclass(impl_cls, parent_impl):
        raise TypeError(
            f"{impl_cls.__name__} must inherit from {parent_impl.__name__} "
            f"because {target_cls.__name__} inherits its Declaration methods"
        )

    impl_cls._target_class = target_cls
    _implementation_class_registry[target_cls] = impl_cls
    _register_implementation_methods(impl_cls, target_cls)
    bump_registry_generation()


def _prepare_implementation_instance(decl: Declaration) -> Any | None:
    if decl in _implementation_instance_registry:
        return _implementation_instance_registry[decl]

    impl_cls = implementation_class(type(decl))
    if impl_cls is None:
        return None

    impl = cast(Any, impl_cls).__new__(impl_cls)
    if not isinstance(impl, impl_cls):
        raise TypeError(
            f"{impl_cls.__name__}.__new__ returned {type(impl).__name__}, "
            f"expected {impl_cls.__name__}"
        )
    _bind_implementation_instance(decl, impl)
    return impl


class Implementation(Generic[T]):
    _target_class: type[T] | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        target_cls = _resolve_target_class(cls)
        if target_cls is None:
            return
        _register_implementation_class(cls, target_cls)


def implementation_class(
    decl_or_cls: Declaration | type[Declaration],
) -> type | None:
    decl_cls: type[Declaration]
    if isinstance(decl_or_cls, Declaration):
        decl_cls = type(decl_or_cls)
    elif isinstance(decl_or_cls, type) and issubclass(decl_or_cls, Declaration):
        decl_cls = decl_or_cls
    else:
        raise TypeError("implementation_class() expects a Declaration instance or class")

    for klass in decl_cls.__mro__:
        impl_cls = _implementation_class_registry.get(klass)
        if impl_cls is not None:
            return impl_cls
    return None


def implementation_of(decl: Declaration, impl_cls: type | None = None) -> Any | None:
    impl = _implementation_instance_registry.get(decl)
    if impl is None:
        return None
    if impl_cls is not None and not isinstance(impl, impl_cls):
        return None
    return impl


def implementation_owner(impl: object) -> Declaration | None:
    entry = _implementation_owner_registry.get(id(impl))
    if entry is None:
        return None
    decl_ref, _finalizer = entry
    decl = decl_ref()
    if decl is None:
        _implementation_owner_registry.pop(id(impl), None)
    return decl
