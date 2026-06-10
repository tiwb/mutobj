from __future__ import annotations

from typing import Any, Callable

from ._fields import AttributeDescriptor, invalidate_ordered_fields_cache_for
from ._impls import apply_impl
from ._state import (
    attribute_registry,
    class_registry,
    classvar_registry,
    impl_chain_registry,
    module_first_seq,
)


def update_class_inplace(existing: type, new_cls: type) -> None:
    _skip = frozenset({
        "__dict__",
        "__weakref__",
        "__class__",
        "__mro__",
        "__subclasses__",
        "__bases__",
        "__name__",
        "__qualname__",
        "__module__",
    })

    old_attrs = set(existing.__dict__.keys())
    new_attrs = set(new_cls.__dict__.keys())

    for attr in old_attrs - new_attrs - _skip:
        try:
            delattr(existing, attr)
        except (AttributeError, TypeError):
            pass

    for attr in new_attrs - _skip:
        val = new_cls.__dict__[attr]
        try:
            old_val = existing.__dict__.get(attr)
            if isinstance(old_val, AttributeDescriptor) and not isinstance(val, AttributeDescriptor):
                type.__setattr__(existing, attr, val)
            else:
                setattr(existing, attr, val)
        except (AttributeError, TypeError):
            pass

        if callable(val) and hasattr(val, "__mutobj_class__"):
            val.__mutobj_class__ = existing
        if isinstance(val, (classmethod, staticmethod)):
            inner: Callable[..., Any] = val.__func__  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            if hasattr(inner, "__mutobj_class__"):
                inner.__mutobj_class__ = existing
        if isinstance(val, AttributeDescriptor):
            val.owner_cls = existing

    if "__annotations__" in new_cls.__dict__:
        existing.__annotations__ = dict(new_cls.__dict__["__annotations__"])


def migrate_registries(existing: type, new_cls: type) -> None:
    for key in list(impl_chain_registry):
        cls, impl_key = key
        if cls is not new_cls:
            continue

        new_chain = impl_chain_registry.pop(key)
        existing_key = (existing, impl_key)
        existing_chain = impl_chain_registry.get(existing_key, [])

        new_default = next(
            ((func, mod, seq) for func, mod, seq in new_chain if mod == "__default__"),
            None,
        )

        if existing_chain:
            for index, (_func, mod, _seq) in enumerate(existing_chain):
                if mod == "__default__":
                    if new_default is not None:
                        existing_chain[index] = new_default
                    break
        else:
            existing_chain = new_chain

        impl_chain_registry[existing_key] = existing_chain
        if existing_chain:
            apply_impl(existing, impl_key, existing_chain[-1][0])

    keys_to_migrate = [key for key in module_first_seq if key[0] is new_cls]
    for key in keys_to_migrate:
        module_first_seq[(existing, key[1], key[2])] = module_first_seq.pop(key)

    if new_cls in attribute_registry:
        attribute_registry[existing] = attribute_registry.pop(new_cls)

    if new_cls in classvar_registry:
        classvar_registry[existing] = classvar_registry.pop(new_cls)

    invalidate_ordered_fields_cache_for(existing)

    key = (new_cls.__module__, new_cls.__qualname__)
    if class_registry.get(key) is new_cls:
        class_registry[key] = existing
