from __future__ import annotations

import sys
import warnings
from types import FrameType
from typing import Any, Callable, TypeVar

from ._constants import (
    DECLARATION_USER_HOOKS,
    DECLARED_CLASSMETHODS,
    DECLARED_STATICMETHODS,
)
from ._fields import (
    AttributeDescriptor,
    AttributeGetterPlaceholder,
    AttributeSetterPlaceholder,
)
from ._state import (
    class_registry,
    impl_chain_registry,
    impl_metas,
    module_first_seq,
    bump_registry_generation,
    next_impl_seq,
)

_F = TypeVar("_F")


def _make_stub_method(name: str, cls: type) -> Callable[..., Any]:
    def stub(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            f"Method '{name}' is declared in {cls.__name__} but not implemented. "
            f"Use @mutobj.impl({cls.__name__}.{name}) to provide implementation."
        )

    stub.__name__ = name
    stub.__qualname__ = f"{cls.__name__}.{name}"
    stub.__mutobj_class__ = cls
    stub.__mutobj_is_stub__ = True
    return stub


def _make_stub_classmethod(name: str, cls: type) -> classmethod[Any, ..., Any]:
    def stub(cls_arg: type, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            f"Classmethod '{name}' is declared in {cls.__name__} but not implemented. "
            f"Use @mutobj.impl({cls.__name__}.{name}) to provide implementation."
        )

    stub.__name__ = name
    stub.__qualname__ = f"{cls.__name__}.{name}"
    stub.__mutobj_class__ = cls
    stub.__mutobj_is_classmethod__ = True
    stub.__mutobj_is_stub__ = True
    return classmethod(stub)


def _make_stub_staticmethod(name: str, cls: type) -> staticmethod[Any, Any]:
    def stub(*args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            f"Staticmethod '{name}' is declared in {cls.__name__} but not implemented. "
            f"Use @mutobj.impl({cls.__name__}.{name}) to provide implementation."
        )

    stub.__name__ = name
    stub.__qualname__ = f"{cls.__name__}.{name}"
    stub.__mutobj_class__ = cls
    stub.__mutobj_is_staticmethod__ = True
    stub.__mutobj_is_stub__ = True
    return staticmethod(stub)


def apply_impl(cls: type, impl_key: str, func: Callable[..., Any]) -> None:
    if impl_key.endswith(".getter"):
        prop_name = impl_key[:-7]
        desc = cls.__dict__.get(prop_name)
        if isinstance(desc, AttributeDescriptor):
            desc._fget = func  # pyright: ignore[reportPrivateUsage]
    elif impl_key.endswith(".setter"):
        prop_name = impl_key[:-7]
        desc = cls.__dict__.get(prop_name)
        if isinstance(desc, AttributeDescriptor):
            desc._fset = func  # pyright: ignore[reportPrivateUsage]
    else:
        declared_cm: set[str] = getattr(cls, DECLARED_CLASSMETHODS, set())
        declared_sm: set[str] = getattr(cls, DECLARED_STATICMETHODS, set())
        if impl_key in declared_cm:
            setattr(cls, impl_key, classmethod(func))
        elif impl_key in declared_sm:
            setattr(cls, impl_key, staticmethod(func))
        else:
            setattr(cls, impl_key, func)


def _restore_stub(cls: type, impl_key: str) -> None:
    if impl_key.endswith(".getter"):
        prop_name = impl_key[:-7]
        desc = cls.__dict__.get(prop_name)
        if isinstance(desc, AttributeDescriptor):
            desc.restore_default_getter()
    elif impl_key.endswith(".setter"):
        prop_name = impl_key[:-7]
        desc = cls.__dict__.get(prop_name)
        if isinstance(desc, AttributeDescriptor):
            desc.restore_default_setter()
    else:
        declared_cm: set[str] = getattr(cls, DECLARED_CLASSMETHODS, set())
        declared_sm: set[str] = getattr(cls, DECLARED_STATICMETHODS, set())
        if impl_key in declared_cm:
            setattr(cls, impl_key, _make_stub_classmethod(impl_key, cls))
        elif impl_key in declared_sm:
            setattr(cls, impl_key, _make_stub_staticmethod(impl_key, cls))
        else:
            setattr(cls, impl_key, _make_stub_method(impl_key, cls))


def register_to_chain(
    target_cls: type,
    impl_key: str,
    func: Callable[..., Any],
    source_module: str,
    metas: tuple[object, ...] = (),
) -> bool:
    key = (target_cls, impl_key)
    chain = impl_chain_registry.setdefault(key, [])
    seq_key = (target_cls, impl_key, source_module)

    existing_idx = next(
        (i for i, (_, module_name, _) in enumerate(chain) if module_name == source_module),
        None,
    )
    if existing_idx is not None:
        old_seq = chain[existing_idx][2]
        chain[existing_idx] = (func, source_module, old_seq)
        _store_metas(target_cls, impl_key, old_seq, metas)
        bump_registry_generation()
        return existing_idx == len(chain) - 1

    if seq_key in module_first_seq:
        seq = module_first_seq[seq_key]
    else:
        seq = next_impl_seq()
        module_first_seq[seq_key] = seq

    chain.append((func, source_module, seq))
    chain.sort(key=lambda item: item[2])
    _store_metas(target_cls, impl_key, seq, metas)
    bump_registry_generation()
    return chain[-1][1] == source_module


def _resolve_source_key(func: Callable[..., Any]) -> str:
    source_key = getattr(func, "__mutobj_source_key__", None)
    if isinstance(source_key, str) and source_key:
        return source_key
    return getattr(func, "__module__", "") or ""


def _unwrap_descriptor(candidate: Any) -> Callable[..., Any] | None:
    if isinstance(candidate, (classmethod, staticmethod)):
        func = getattr(candidate, "__func__", None)  # pyright: ignore[reportUnknownArgumentType]
        return func if callable(func) else None
    return candidate if callable(candidate) else None


def _resolve_attribute_source_key(candidate: Any, frame: FrameType) -> str | None:
    if not isinstance(candidate, AttributeDescriptor):
        return None
    for accessor in (candidate._fget, candidate._fset):  # pyright: ignore[reportPrivateUsage]
        if accessor is not None and getattr(accessor, "__code__", None) is frame.f_code:
            return _resolve_source_key(accessor)
    return None


def _resolve_property_source_key(candidate: Any, frame: FrameType) -> str | None:
    if not isinstance(candidate, property):
        return None
    for accessor in (candidate.fget, candidate.fset, candidate.fdel):
        if accessor is not None and getattr(accessor, "__code__", None) is frame.f_code:
            return _resolve_source_key(accessor)
    return None


def _resolve_frame_source_key(frame: FrameType) -> str | None:
    locals_self = frame.f_locals.get("self")
    if locals_self is not None:
        method_name = frame.f_code.co_name
        for klass in type(locals_self).__mro__:
            raw_candidate = klass.__dict__.get(method_name)
            property_source_key = _resolve_property_source_key(raw_candidate, frame)
            if property_source_key is not None:
                return property_source_key
            descriptor_source_key = _resolve_attribute_source_key(raw_candidate, frame)
            if descriptor_source_key is not None:
                return descriptor_source_key
            candidate = _unwrap_descriptor(raw_candidate)
            if candidate is not None and getattr(candidate, "__code__", None) is frame.f_code:
                return _resolve_source_key(candidate)

    locals_cls = frame.f_locals.get("cls")
    if isinstance(locals_cls, type):
        method_name = frame.f_code.co_name
        for klass in locals_cls.__mro__:
            raw_candidate = klass.__dict__.get(method_name)
            property_source_key = _resolve_property_source_key(raw_candidate, frame)
            if property_source_key is not None:
                return property_source_key
            descriptor_source_key = _resolve_attribute_source_key(raw_candidate, frame)
            if descriptor_source_key is not None:
                return descriptor_source_key
            candidate = _unwrap_descriptor(raw_candidate)
            if candidate is not None and getattr(candidate, "__code__", None) is frame.f_code:
                return _resolve_source_key(candidate)

    globals_candidate = frame.f_globals.get(frame.f_code.co_name)
    func = _unwrap_descriptor(globals_candidate)
    if func is not None and getattr(func, "__code__", None) is frame.f_code:
        return _resolve_source_key(func)

    return None


def _source_matches_module(source_key: str, module_name: str) -> bool:
    return source_key == module_name or source_key.startswith(f"{module_name}::")


def _store_metas(
    target_cls: type, impl_key: str, seq: int, metas: tuple[object, ...]
) -> None:
    meta_key = (target_cls, impl_key, seq)
    if metas:
        impl_metas[meta_key] = metas
    else:
        impl_metas.pop(meta_key, None)


def _resolve_impl_key(method: Any) -> tuple[type, str]:
    if isinstance(method, AttributeGetterPlaceholder):
        desc = method.descriptor
        if desc.owner_cls is None:
            raise ValueError(f"Cannot determine class for descriptor {desc.name}")
        return desc.owner_cls, f"{desc.name}.getter"

    if isinstance(method, AttributeSetterPlaceholder):
        desc = method.descriptor
        if desc.owner_cls is None:
            raise ValueError(f"Cannot determine class for descriptor {desc.name}")
        return desc.owner_cls, f"{desc.name}.setter"

    if not callable(method):
        raise TypeError(f"Expected a callable or descriptor accessor, got {type(method)}")

    method_name = getattr(method, "__name__", "")
    target_cls = getattr(method, "__mutobj_class__", None)

    if target_cls is None:
        qualname = getattr(method, "__qualname__", "")
        if "." in qualname:
            class_name = qualname.rsplit(".", 1)[0]
        else:
            raise ValueError(f"Cannot determine class for method {method}")

        candidates = [
            cls for cls in class_registry.values() if cls.__name__ == class_name
        ]
        if len(candidates) > 1:
            paths = [f"{cls.__module__}.{cls.__qualname__}" for cls in candidates]
            raise ValueError(
                f"@impl({method_name!r}): ambiguous target — multiple "
                f"Declaration classes named {class_name!r} are registered: "
                f"{paths}. This usually means the method does not have "
                f"__mutobj_class__ set; if it's a dunder method declared "
                f"by the user, ensure it's defined in the class body "
                f"(mutobj should auto-tag it)."
            )
        if len(candidates) == 1:
            target_cls = candidates[0]

        if target_cls is None:
            from ._declaration import Declaration

            candidate = (
                method.__globals__.get(class_name)
                if hasattr(method, "__globals__")
                else None
            )
            if isinstance(candidate, type):
                if issubclass(candidate, Declaration) or candidate is Declaration:
                    target_cls = candidate
                else:
                    raise TypeError(
                        f"@impl({candidate.__name__}.{method_name}): "
                        f"{candidate.__name__} is not a mutobj.Declaration subclass. "
                        f"@impl only supports Declaration subclasses.\nTo fix:\n"
                        f"  - Make {candidate.__name__} inherit from mutobj.Declaration, or\n"
                        f"  - Write the implementation directly in the class body (no @impl)"
                    )
            else:
                parts = [part for part in class_name.split(".") if part and part != "<locals>"]
                cls_display = parts[-1] if parts else "<unknown>"
                raise TypeError(
                    f"@impl({cls_display}.{method_name}): {cls_display} "
                    f"is not a mutobj.Declaration subclass. "
                    f"@impl only supports Declaration subclasses.\nTo fix:\n"
                    f"  - Make {cls_display} inherit from mutobj.Declaration, or\n"
                    f"  - Write the implementation directly in the class body (no @impl)"
                )

    if target_cls is None:
        raise ValueError(f"Cannot find class for method {method_name}")

    return target_cls, method_name


def impl_has(method: Any) -> bool:
    warnings.warn(
        "mutobj.impl_has() is deprecated; use mutobj.impl_has_override() / "
        "mutobj.impl_is_own() / mutobj.impl_is_inherited() instead. "
        "The old bytecode-based 'real implementation' detection has been removed.",
        DeprecationWarning,
        stacklevel=2,
    )
    return impl_has_override(method)


def impl_has_override(method: Any) -> bool:
    cls, key = _resolve_impl_key(method)
    chain = impl_chain_registry.get((cls, key), [])
    return any(source_module != "__default__" for _func, source_module, _seq in chain)


def impl_is_own(method: Any) -> bool:
    cls, key = _resolve_impl_key(method)
    chain = impl_chain_registry.get((cls, key), [])
    if not chain:
        return False
    return not getattr(chain[0][0], "__mutobj_is_delegate__", False)


def impl_is_inherited(method: Any) -> bool:
    cls, key = _resolve_impl_key(method)
    chain = impl_chain_registry.get((cls, key), [])
    if not chain:
        return False
    return bool(getattr(chain[0][0], "__mutobj_is_delegate__", False))


def impl_chain(method: Any) -> list[tuple[Callable[..., Any], str, int]]:
    cls, key = _resolve_impl_key(method)
    return list(impl_chain_registry.get((cls, key), []))


def _resolve_chain_top_meta_key(
    target_cls: type, impl_key: str, _visited: set[tuple[type, str]] | None = None
) -> tuple[type, str, int] | None:
    if _visited is None:
        _visited = set()
    pair = (target_cls, impl_key)
    if pair in _visited:
        return None
    _visited.add(pair)

    chain = impl_chain_registry.get(pair)
    if not chain:
        return None

    top_func, _mod, seq = chain[-1]
    if getattr(top_func, "__mutobj_is_delegate__", False):
        base = getattr(top_func, "__mutobj_delegate_base__", None)
        delegate_name = getattr(top_func, "__mutobj_delegate_name__", impl_key)
        if isinstance(base, type):
            resolved = _resolve_chain_top_meta_key(base, delegate_name, _visited)
            if resolved is not None:
                return resolved
    return (target_cls, impl_key, seq)


def impl_meta(method: Any) -> tuple[object, ...]:
    cls, key = _resolve_impl_key(method)
    resolved = _resolve_chain_top_meta_key(cls, key)
    if resolved is None:
        return ()
    return impl_metas.get(resolved, ())


def impl_meta_of(method: Any, meta_type: type[_F]) -> _F | None:
    for meta in impl_meta(method):
        if isinstance(meta, meta_type):
            return meta
    return None


def impl_call_super(
    method: Any,
    *args: Any,
    _frame_depth: int = 1,
    **kwargs: Any,
) -> Any:
    cls, key = _resolve_impl_key(method)
    frame = sys._getframe(_frame_depth)  # pyright: ignore[reportPrivateUsage]
    caller_module = _resolve_frame_source_key(frame) or frame.f_globals.get("__name__", "")
    chain = impl_chain_registry.get((cls, key), [])
    for index, (_fn, module_name, _seq) in enumerate(chain):
        if module_name == caller_module:
            if index == 0:
                raise NotImplementedError(
                    f"No super implementation for {cls.__name__}.{key} "
                    f"below module {module_name!r}"
                )
            prev_func, _prev_module, _prev_seq = chain[index - 1]
            return prev_func(*args, **kwargs)
    raise RuntimeError(
        f"impl_call_super({cls.__name__}.{key}) must be called from within "
        f"an @impl function for that method (caller module: {caller_module!r})"
    )


def call_super_impl(method: Any, *args: Any, **kwargs: Any) -> Any:
    warnings.warn(
        "mutobj.call_super_impl() is deprecated; use mutobj.impl_call_super() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return impl_call_super(method, *args, _frame_depth=2, **kwargs)


def impl(
    method: Callable[..., Any] | AttributeGetterPlaceholder | AttributeSetterPlaceholder,
    *metas: object,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        source_module = _resolve_source_key(func)
        func.__mutobj_source_key__ = source_module

        if isinstance(method, AttributeGetterPlaceholder):
            target_cls, impl_key = _resolve_impl_key(method)
            desc = method.descriptor
            became_top = register_to_chain(target_cls, impl_key, func, source_module, metas)
            if became_top:
                desc._fget = func  # pyright: ignore[reportPrivateUsage]
            return func

        if isinstance(method, AttributeSetterPlaceholder):
            target_cls, impl_key = _resolve_impl_key(method)
            desc = method.descriptor
            became_top = register_to_chain(target_cls, impl_key, func, source_module, metas)
            if became_top:
                desc._fset = func  # pyright: ignore[reportPrivateUsage]
            return func

        target_cls, method_name = _resolve_impl_key(method)

        from ._declaration import Declaration

        if target_cls is Declaration and method_name not in DECLARATION_USER_HOOKS:
            raise ValueError(
                f"@impl({method_name!r}): refusing to register on Declaration base "
                f"class. The method was resolved to Declaration because the "
                f"subclass does not declare its own {method_name!r}. Add a stub "
                f"on the subclass first, e.g.\n"
                f"    class MySubclass(mutobj.Declaration):\n"
                f"        def {method_name}(self, ...) -> ...: ...\n"
                f"then re-run @impl(MySubclass.{method_name})."
            )

        if not hasattr(target_cls, method_name):
            raise ValueError(
                f"Method '{method_name}' does not exist in {target_cls.__name__}"
            )

        existing = target_cls.__dict__.get(method_name)
        is_classmethod = isinstance(existing, classmethod)
        is_staticmethod = isinstance(existing, staticmethod)

        became_top = register_to_chain(
            target_cls, method_name, func, source_module, metas
        )

        func.__mutobj_class__ = target_cls
        func.__name__ = method_name
        func.__qualname__ = f"{target_cls.__name__}.{method_name}"

        if became_top:
            if is_classmethod:
                setattr(target_cls, method_name, classmethod(func))
            elif is_staticmethod:
                setattr(target_cls, method_name, staticmethod(func))
            else:
                setattr(target_cls, method_name, func)

        return func

    return decorator


def unregister_module_impls(module_name: str) -> int:
    removed = 0

    for key in list(impl_chain_registry):
        cls, impl_key = key
        chain = impl_chain_registry[key]
        was_top_module = _source_matches_module(chain[-1][1], module_name) if chain else False
        removed_seqs = [
            seq for _func, mod, seq in chain if _source_matches_module(mod, module_name)
        ]

        before = len(chain)
        chain[:] = [
            (func, mod, seq)
            for func, mod, seq in chain
            if not _source_matches_module(mod, module_name)
        ]
        removed += before - len(chain)

        for seq in removed_seqs:
            impl_metas.pop((cls, impl_key, seq), None)

        if not chain:
            _restore_stub(cls, impl_key)
            del impl_chain_registry[key]
        elif was_top_module:
            apply_impl(cls, impl_key, chain[-1][0])

    if removed > 0:
        bump_registry_generation()

    return removed


def register_module_impls(*modules: Any) -> None:
    return None
