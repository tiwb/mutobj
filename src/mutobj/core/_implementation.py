from __future__ import annotations

# pyright: reportPrivateUsage=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportInvalidTypeVarUse=false, reportCallIssue=false, reportUnusedFunction=false, reportUnnecessaryIsInstance=false

import weakref
from typing import Any, Generic, TypeVar, cast

from ._constants import (
    _DECLARATION_CHAIN_HOOKS,
    _DECLARED_METHODS,
)
from ._declaration import Declaration
from ._fields import _get_attribute_descriptor
from ._impls import _apply_impl, _register_to_chain
from ._state import (
    _implementation_class_registry,
    _implementation_instance_registry,
    _implementation_owner_registry,
    bump_registry_generation,
)

T = TypeVar("T", bound=Declaration)
IT = TypeVar("IT", bound="Implementation[Any]")


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


def _lookup_implementation_class(
    decl_cls: type[Declaration],
) -> type["Implementation[Any]"] | None:
    for klass in decl_cls.__mro__:
        impl_cls = _implementation_class_registry.get(klass)
        if impl_cls is not None:
            return cast(type[Implementation[Any]], impl_cls)
    return None


def _lookup_implementation_instance(decl: Declaration, impl_cls: type[IT]) -> IT | None:
    impl = _implementation_instance_registry.get(decl)
    if impl is None or not isinstance(impl, impl_cls):
        return None
    return impl


def _lookup_implementation_owner(impl: object) -> Declaration | None:
    entry = _implementation_owner_registry.get(id(impl))
    if entry is None:
        return None
    decl_ref, _finalizer = entry
    decl = decl_ref()
    if decl is None:
        _implementation_owner_registry.pop(id(impl), None)
    return decl


def _describe_value(value: object) -> str:
    if isinstance(value, type):
        return value.__name__
    return f"{type(value).__name__} instance"


def _implementation_bridge(
    target_cls: type[Declaration],
    impl_cls: type,
    method_name: str,
    impl_method: Any,
    source_key: str,
) -> Any:
    def bridge(decl: Declaration, *args: Any, **kwargs: Any) -> Any:
        impl = _implementation_instance_registry.get(decl)
        if impl is None:
            raise RuntimeError(
                f"Implementation instance for {target_cls.__name__} -> "
                f"{impl_cls.__name__} is not available"
            )
        if not isinstance(impl, impl_cls):
            raise RuntimeError(
                f"Implementation instance for {target_cls.__name__} is "
                f"{type(impl).__name__}, expected {impl_cls.__name__}"
            )
        return impl_method(impl, *args, **kwargs)

    bridge.__name__ = method_name
    bridge.__qualname__ = f"{target_cls.__name__}.{method_name}"
    bridge.__module__ = impl_cls.__module__
    bridge.__mutobj_class__ = target_cls
    bridge.__mutobj_source_key__ = source_key
    return bridge


def _register_implementation_property_accessor(
    target_cls: type[Declaration],
    impl_cls: type,
    prop_name: str,
    accessor_kind: str,
    accessor_func: Any,
    source_key: str,
) -> None:
    accessor_func.__mutobj_source_key__ = source_key
    impl_key = f"{prop_name}.{accessor_kind}"
    bridge = _implementation_bridge(
        target_cls,
        impl_cls,
        impl_key,
        accessor_func,
        source_key,
    )
    became_top = _register_to_chain(target_cls, impl_key, bridge, source_key)
    if became_top:
        _apply_impl(target_cls, impl_key, bridge)


def _register_implementation_methods(
    impl_cls: type,
    target_cls: type[Declaration],
) -> None:
    source_key = _implementation_source_key(impl_cls)
    declared_methods: set[str] = getattr(target_cls, _DECLARED_METHODS, set())
    bridged_methods = declared_methods | _DECLARATION_CHAIN_HOOKS

    for method_name, method_value in impl_cls.__dict__.items():
        target_desc = _get_attribute_descriptor(target_cls, method_name)
        if isinstance(method_value, property):
            if target_desc is None:
                if method_name in bridged_methods and hasattr(target_cls, method_name):
                    raise TypeError(
                        f"Implementation '{impl_cls.__name__}.{method_name}' uses @property, "
                        f"but Declaration '{target_cls.__name__}.{method_name}' is a method."
                    )
                continue
            if target_desc.has_storage:
                raise TypeError(
                    f"Implementation '{impl_cls.__name__}.{method_name}' uses @property, "
                    f"but Declaration '{target_cls.__name__}.{method_name}' is a field."
                )
            if method_value.fget is None and method_value.fset is None:
                continue
            if method_value.fget is not None:
                _register_implementation_property_accessor(
                    target_cls,
                    impl_cls,
                    method_name,
                    "getter",
                    method_value.fget,
                    source_key,
                )
            if method_value.fset is not None:
                _register_implementation_property_accessor(
                    target_cls,
                    impl_cls,
                    method_name,
                    "setter",
                    method_value.fset,
                    source_key,
                )
            continue
        if not callable(method_value):
            continue
        method_value.__mutobj_source_key__ = source_key
        if (
            method_name.startswith("__")
            and method_name.endswith("__")
            and method_name not in _DECLARATION_CHAIN_HOOKS
        ):
            continue
        if target_desc is not None:
            member_kind = "field" if target_desc.has_storage else "property"
            raise TypeError(
                f"Implementation '{impl_cls.__name__}.{method_name}' defines a method, "
                f"but Declaration '{target_cls.__name__}.{method_name}' is a {member_kind}."
            )
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

    impl_cls = _lookup_implementation_class(type(decl))
    if impl_cls is None:
        return None

    impl = cast(object, cast(Any, impl_cls).__new__(impl_cls))
    if not isinstance(impl, impl_cls):
        raise TypeError(
            f"{impl_cls.__name__}.__new__ returned {type(impl).__name__}, "
            f"expected {impl_cls.__name__}"
        )
    _bind_implementation_instance(decl, cast(object, impl))
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
    decl_cls: type[T],
) -> type[Implementation[T]]:
    if not isinstance(decl_cls, type) or not issubclass(decl_cls, Declaration):
        raise TypeError(
            "implementation_class() expects a mutobj.Declaration class, "
            f"got {_describe_value(decl_cls)}"
        )

    impl_cls = _lookup_implementation_class(decl_cls)
    if impl_cls is None:
        raise LookupError(
            f"No Implementation class is registered for {decl_cls.__name__}"
        )
    return cast(type[Implementation[T]], impl_cls)


def implementation_of(decl: T, impl_cls: type[IT]) -> IT:
    if not isinstance(decl, Declaration):
        raise TypeError(
            "implementation_of() expects decl to be a mutobj.Declaration instance"
        )
    if not isinstance(impl_cls, type) or not issubclass(impl_cls, Implementation):
        raise TypeError(
            "implementation_of() expects impl_cls to be an Implementation subclass"
        )

    impl = _lookup_implementation_instance(decl, impl_cls)
    if impl is not None:
        return impl

    actual_impl = _implementation_instance_registry.get(decl)
    if actual_impl is None:
        raise LookupError(
            f"No {impl_cls.__name__} instance is associated with "
            f"{type(decl).__name__} instance"
        )
    raise LookupError(
        f"Implementation instance for {type(decl).__name__} is "
        f"{type(actual_impl).__name__}, expected {impl_cls.__name__}"
    )


def implementation_owner(impl: Implementation[T]) -> T:
    if not isinstance(impl, Implementation):
        raise TypeError(
            "implementation_owner() expects impl to be an Implementation instance"
        )

    owner = _lookup_implementation_owner(impl)
    if owner is None:
        raise LookupError(
            f"No Declaration owner is associated with {type(impl).__name__} instance"
        )
    return cast(T, owner)
