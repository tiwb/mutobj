from __future__ import annotations

from typing import Any, Callable, cast

from ._fields import AttributeDescriptor, invalidate_ordered_fields_cache_for
from ._discovery import class_registry
from ._impls import apply_impl, migrate_module_first_seq_for_class


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
        "__mutobj_class_meta__",
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
            inner: Callable[..., Any] = cast(Any, val).__func__
            if hasattr(inner, "__mutobj_class__"):
                inner.__mutobj_class__ = existing
        if isinstance(val, AttributeDescriptor):
            val.owner_cls = existing

    if "__annotations__" in new_cls.__dict__:
        existing.__annotations__ = dict(new_cls.__dict__["__annotations__"])


def migrate_registries(existing: type, new_cls: type) -> None:
    new_meta = getattr(new_cls, "__mutobj_class_meta__", None)
    if new_meta is None:
        return

    existing_meta = getattr(existing, "__mutobj_class_meta__", None)
    if existing_meta is not None:
        # 合并 impl_chains
        for impl_key, new_chain in new_meta.impl_chains.items():
            existing_chain = existing_meta.impl_chains.get(impl_key, [])
            new_default = next(
                (entry for entry in new_chain if entry.source_module == "__default__"),
                None,
            )

            if existing_chain:
                for index, entry in enumerate(existing_chain):
                    if entry.source_module == "__default__":
                        if new_default is not None:
                            existing_chain[index] = new_default
                        break
            else:
                existing_chain = new_chain

            existing_meta.impl_chains[impl_key] = existing_chain
            if existing_chain:
                apply_impl(existing, impl_key, existing_chain[-1].func)

        # 合并 fields
        existing_meta.fields = new_meta.fields
        existing_meta.classvars = new_meta.classvars
        existing_meta.methods = new_meta.methods
        existing_meta.classmethods = new_meta.classmethods
        existing_meta.staticmethods = new_meta.staticmethods
        existing_meta.impl_class = new_meta.impl_class
        existing_meta.extensions = new_meta.extensions

    migrate_module_first_seq_for_class(new_cls, existing)

    invalidate_ordered_fields_cache_for(existing)

    key = (new_cls.__module__, new_cls.__qualname__)
    if class_registry.get(key) is new_cls:
        class_registry[key] = existing
