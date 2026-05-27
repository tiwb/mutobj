# pyright: reportPrivateUsage=false
from __future__ import annotations

from typing import Any, Self, TypeVar

from ._constants import (
    _DECLARATION_USER_HOOKS,
    _DECLARED_CLASSMETHODS,
    _DECLARED_METHODS,
    _DECLARED_PROPERTIES,
    _DECLARED_STATICMETHODS,
    _MUTABLE_TYPES,
    _MUTOBJ_RESERVED_DUNDERS,
)
from ._fields import (
    AttributeDescriptor,
    Field,
    _get_attribute_descriptor,
    _get_init_fields,
    _invalidate_ordered_fields_cache_for,
)
from ._properties import Property
from ._reload import _migrate_registries, _update_class_inplace
from ._state import (
    _attribute_registry,
    _class_registry,
    _classvar_registry,
    _impl_chain,
    _property_registry,
    bump_registry_generation,
)
from ._typing_utils import _is_classvar

T = TypeVar("T", bound="Declaration")


class DeclarationMeta(type):
    """mutobj.Declaration metaclass."""

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
    ) -> DeclarationMeta:
        module = namespace.get("__module__", "")
        qualname = namespace.get("__qualname__", name)
        key = (module, qualname)
        existing = _class_registry.get(key)

        declared_methods: set[str] = set()
        declared_properties: set[str] = set()
        declared_classmethods: set[str] = set()
        declared_staticmethods: set[str] = set()

        cls = super().__new__(mcs, name, bases, namespace)

        if name == "Declaration" and not bases:
            declared: set[str] = set()
            for hook_name in _DECLARATION_USER_HOOKS:
                hook = namespace.get(hook_name)
                if callable(hook):
                    hook.__mutobj_class__ = cls
                    _impl_chain.setdefault((cls, hook_name), []).append((hook, "__default__", 0))
                    declared.add(hook_name)
            setattr(cls, _DECLARED_METHODS, declared)
            return cls

        annotations = getattr(cls, "__annotations__", {})

        parent_classvars: set[str] = set()
        module = namespace.get("__module__", "")
        for base in cls.__mro__[1:]:
            parent_classvars.update(_classvar_registry.get(base, set()))
            base_anns = getattr(base, "__annotations__", {})
            base_module = getattr(base, "__module__", "")
            for base_attr, base_type in base_anns.items():
                if _is_classvar(base_type, base_module):
                    parent_classvars.add(base_attr)

        attr_registry: dict[str, Any] = {}
        classvar_attrs: set[str] = set()
        for attr_name, attr_type in annotations.items():
            if _is_classvar(attr_type, module) or attr_name in parent_classvars:
                classvar_attrs.add(attr_name)
                value = namespace.get(attr_name)
                if isinstance(value, Field):
                    raise TypeError(
                        f"Declaration '{name}' attribute '{attr_name}' is ClassVar "
                        f"and does not support field(default_factory=...). "
                        f"Use a plain default value or a module-level constant instead."
                    )
                continue

            value = namespace.get(attr_name)
            if isinstance(value, Field):
                descriptor = AttributeDescriptor(
                    attr_name,
                    attr_type,
                    default=value.default,
                    default_factory=value.default_factory,
                    init=value.init,
                )
            elif attr_name in namespace and not isinstance(value, AttributeDescriptor):
                if callable(value) or isinstance(value, property):
                    continue
                if isinstance(value, _MUTABLE_TYPES):
                    type_name = type(value).__name__  # pyright: ignore[reportUnknownArgumentType]
                    raise TypeError(
                        f"Declaration '{name}' attribute '{attr_name}' uses mutable default "
                        f"value {type_name}. "
                        f"Use field(default_factory={type_name}) instead."
                    )
                descriptor = AttributeDescriptor(attr_name, attr_type, default=value)
            elif not hasattr(cls, attr_name) or not isinstance(getattr(cls, attr_name), AttributeDescriptor):
                descriptor = AttributeDescriptor(attr_name, attr_type)
            else:
                attr_registry[attr_name] = attr_type
                continue

            setattr(cls, attr_name, descriptor)
            attr_registry[attr_name] = attr_type

        own_annotations = namespace.get("__annotations__", {})
        for attr_name, value in namespace.items():
            if attr_name in own_annotations:
                continue
            if attr_name in parent_classvars:
                classvar_attrs.add(attr_name)
                if isinstance(value, Field):
                    raise TypeError(
                        f"Declaration '{name}' attribute '{attr_name}' is ClassVar "
                        f"and does not support field(default_factory=...). "
                        f"Use a plain default value or a module-level constant instead."
                    )
                continue
            if attr_name.startswith("_"):
                continue
            if callable(value) or isinstance(value, (property, classmethod, staticmethod)):
                continue
            if isinstance(value, AttributeDescriptor):
                continue

            parent_desc: AttributeDescriptor | None = None
            for base in cls.__mro__[1:]:
                base_val = base.__dict__.get(attr_name)
                if isinstance(base_val, AttributeDescriptor):
                    parent_desc = base_val
                    break
            if parent_desc is None:
                continue

            if isinstance(value, Field):
                descriptor = AttributeDescriptor(
                    attr_name,
                    parent_desc.annotation,
                    default=value.default,
                    default_factory=value.default_factory,
                    init=value.init,
                )
            elif isinstance(value, _MUTABLE_TYPES):
                type_name = type(value).__name__  # pyright: ignore[reportUnknownArgumentType]
                raise TypeError(
                    f"Declaration '{name}' attribute '{attr_name}' uses mutable default "
                    f"value {type_name}. "
                    f"Use field(default_factory={type_name}) instead."
                )
            else:
                descriptor = AttributeDescriptor(attr_name, parent_desc.annotation, default=value)
            setattr(cls, attr_name, descriptor)
            attr_registry[attr_name] = parent_desc.annotation

        _attribute_registry[cls] = attr_registry
        _classvar_registry[cls] = classvar_attrs

        prop_registry: dict[str, Property] = {}
        for prop_name, prop_value in namespace.items():
            if prop_name in _MUTOBJ_RESERVED_DUNDERS:
                continue
            if isinstance(prop_value, property):
                declared_properties.add(prop_name)
                mutobj_prop = Property(prop_name, cls)
                setattr(cls, prop_name, mutobj_prop)
                prop_registry[prop_name] = mutobj_prop
                if prop_value.fget is not None:
                    _impl_chain.setdefault((cls, f"{prop_name}.getter"), []).append(
                        (prop_value.fget, "__default__", 0)
                    )
                    mutobj_prop._fget = prop_value.fget  # pyright: ignore[reportPrivateUsage]
                if prop_value.fset is not None:
                    _impl_chain.setdefault((cls, f"{prop_name}.setter"), []).append(
                        (prop_value.fset, "__default__", 0)
                    )
                    mutobj_prop._fset = prop_value.fset  # pyright: ignore[reportPrivateUsage]

        _property_registry[cls] = prop_registry
        setattr(cls, _DECLARED_PROPERTIES, declared_properties)

        for method_name, method_value in namespace.items():
            if method_name in _MUTOBJ_RESERVED_DUNDERS:
                continue
            if isinstance(method_value, classmethod):
                func: Any = method_value.__func__  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                declared_classmethods.add(method_name)
                _impl_chain.setdefault((cls, method_name), []).append((func, "__default__", 0))
                func.__mutobj_class__ = cls

        setattr(cls, _DECLARED_CLASSMETHODS, declared_classmethods)

        for method_name, method_value in namespace.items():
            if method_name in _MUTOBJ_RESERVED_DUNDERS:
                continue
            if isinstance(method_value, staticmethod):
                func: Any = method_value.__func__  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                declared_staticmethods.add(method_name)
                _impl_chain.setdefault((cls, method_name), []).append((func, "__default__", 0))
                func.__mutobj_class__ = cls

        setattr(cls, _DECLARED_STATICMETHODS, declared_staticmethods)

        for method_name, method_value in namespace.items():
            if method_name in _MUTOBJ_RESERVED_DUNDERS:
                continue
            if callable(method_value) and not isinstance(method_value, (classmethod, staticmethod, property)):
                declared_methods.add(method_name)
                _impl_chain.setdefault((cls, method_name), []).append((method_value, "__default__", 0))
                method_value.__mutobj_class__ = cls

        setattr(cls, _DECLARED_METHODS, declared_methods)

        for base in cls.__mro__[1:]:
            if base is cls or base is object:  # pyright: ignore[reportUnnecessaryComparison]
                continue

            for method_name in getattr(base, _DECLARED_METHODS, set[str]()):
                if method_name in declared_methods or (cls, method_name) in _impl_chain:
                    continue

                def _make_delegate(b: type, mn: str):
                    def delegate(self: Any, *args: Any, **kwargs: Any) -> Any:
                        return getattr(b, mn)(self, *args, **kwargs)

                    delegate.__name__ = mn
                    delegate.__qualname__ = f"{cls.__name__}.{mn}"
                    delegate.__mutobj_class__ = cls
                    delegate.__mutobj_is_delegate__ = True
                    delegate.__mutobj_delegate_base__ = b
                    delegate.__mutobj_delegate_name__ = mn
                    return delegate

                delegate = _make_delegate(base, method_name)
                _impl_chain[(cls, method_name)] = [(delegate, "__default__", 0)]
                setattr(cls, method_name, delegate)
                declared_methods.add(method_name)

            for method_name in getattr(base, _DECLARED_CLASSMETHODS, set[str]()):
                if method_name in declared_classmethods or (cls, method_name) in _impl_chain:
                    continue

                def _make_cm_delegate(b: type, mn: str):
                    def delegate(cls_arg: type, *args: Any, **kwargs: Any) -> Any:
                        base_cm = b.__dict__.get(mn)
                        if base_cm is not None:
                            func = base_cm.__func__ if hasattr(base_cm, "__func__") else base_cm
                            return func(cls_arg, *args, **kwargs)
                        return getattr(b, mn)(*args, **kwargs)

                    delegate.__name__ = mn
                    delegate.__qualname__ = f"{cls.__name__}.{mn}"
                    delegate.__mutobj_class__ = cls
                    delegate.__mutobj_is_classmethod__ = True
                    delegate.__mutobj_is_delegate__ = True
                    delegate.__mutobj_delegate_base__ = b
                    delegate.__mutobj_delegate_name__ = mn
                    return delegate

                delegate = _make_cm_delegate(base, method_name)
                _impl_chain[(cls, method_name)] = [(delegate, "__default__", 0)]
                setattr(cls, method_name, classmethod(delegate))
                declared_classmethods.add(method_name)

            for method_name in getattr(base, _DECLARED_STATICMETHODS, set[str]()):
                if method_name in declared_staticmethods or (cls, method_name) in _impl_chain:
                    continue

                def _make_sm_delegate(b: type, mn: str):
                    def delegate(*args: Any, **kwargs: Any) -> Any:
                        return getattr(b, mn)(*args, **kwargs)

                    delegate.__name__ = mn
                    delegate.__qualname__ = f"{cls.__name__}.{mn}"
                    delegate.__mutobj_class__ = cls
                    delegate.__mutobj_is_staticmethod__ = True
                    delegate.__mutobj_is_delegate__ = True
                    delegate.__mutobj_delegate_base__ = b
                    delegate.__mutobj_delegate_name__ = mn
                    return delegate

                delegate = _make_sm_delegate(base, method_name)
                _impl_chain[(cls, method_name)] = [(delegate, "__default__", 0)]
                setattr(cls, method_name, staticmethod(delegate))
                declared_staticmethods.add(method_name)

        setattr(cls, _DECLARED_METHODS, declared_methods)
        setattr(cls, _DECLARED_CLASSMETHODS, declared_classmethods)
        setattr(cls, _DECLARED_STATICMETHODS, declared_staticmethods)

        if existing is not None and existing is not cls:  # pyright: ignore[reportUnnecessaryComparison]
            _update_class_inplace(existing, cls)
            _migrate_registries(existing, cls)
            bump_registry_generation()
            return existing

        _class_registry[key] = cls
        bump_registry_generation()
        return cls

    def __call__(cls: type[T], *args: Any, **kwargs: Any) -> T:  # type: ignore[misc]
        obj = cls.__new__(cls, *args, **kwargs)
        if isinstance(obj, cls):
            cls.__init__(obj, *args, **kwargs)
            obj.__post_init__()  # type: ignore[attr-defined]
        return obj

    def __setattr__(cls, name: str, value: Any) -> None:
        if isinstance(value, AttributeDescriptor):
            super().__setattr__(name, value)
            return

        desc: AttributeDescriptor | None = None
        from_base = False
        own = cls.__dict__.get(name)
        if isinstance(own, AttributeDescriptor):
            desc = own
        else:
            for base in cls.__mro__[1:]:
                base_val = base.__dict__.get(name)
                if isinstance(base_val, AttributeDescriptor):
                    desc = base_val
                    from_base = True
                    break

        if desc is None:
            super().__setattr__(name, value)
            return

        if isinstance(value, _MUTABLE_TYPES):
            type_name = type(value).__name__  # pyright: ignore[reportUnknownArgumentType]
            raise TypeError(
                f"Declaration '{cls.__name__}' attribute '{name}' uses mutable default "
                f"value {type_name}. "
                f"Use field(default_factory={type_name}) instead."
            )
        if isinstance(value, Field):
            new_desc = AttributeDescriptor(
                name,
                desc.annotation,
                default=value.default,
                default_factory=value.default_factory,
                init=value.init,
            )
        else:
            new_desc = AttributeDescriptor(name, desc.annotation, default=value)
        super().__setattr__(name, new_desc)

        if from_base and cls in _attribute_registry and name not in _attribute_registry[cls]:  # pyright: ignore[reportUnnecessaryContains]
            _attribute_registry[cls][name] = desc.annotation
        _invalidate_ordered_fields_cache_for(cls)


class Declaration(metaclass=DeclarationMeta):
    """Base class for mutobj declarations."""

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        obj = super().__new__(cls)
        applied: set[str] = set()
        for klass in cls.__mro__:
            if klass in _attribute_registry:
                for attr_name in _attribute_registry[klass]:
                    if attr_name in applied:
                        continue
                    desc = klass.__dict__.get(attr_name)
                    if isinstance(desc, AttributeDescriptor) and desc.has_default:
                        if desc.default_factory is not None:
                            setattr(obj, attr_name, desc.default_factory())
                        else:
                            setattr(obj, attr_name, desc.default)
                        applied.add(attr_name)
        return obj

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if args:
            init_fields = _get_init_fields(type(self))
            if len(args) > len(init_fields):
                raise TypeError(
                    f"{type(self).__name__}() takes {len(init_fields)} positional "
                    f"arguments but {len(args)} were given"
                )
            for index, value in enumerate(args):
                name = init_fields[index]
                if name in kwargs:
                    raise TypeError(
                        f"{type(self).__name__}() got multiple values "
                        f"for argument '{name}'"
                    )
                kwargs[name] = value

        for attr_name, value in kwargs.items():
            desc = _get_attribute_descriptor(type(self), attr_name)
            if isinstance(desc, AttributeDescriptor) and not desc.init:
                raise TypeError(
                    f"{type(self).__name__}() got an unexpected keyword argument '{attr_name}'"
                )
            setattr(self, attr_name, value)

    def __post_init__(self) -> None:
        ...
