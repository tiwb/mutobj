# pyright: reportPrivateUsage=false
from __future__ import annotations

from typing import Any, Self, TypeVar

from ._constants import (
    _DECLARATION_CHAIN_HOOKS,
    _DECLARED_CLASSMETHODS,
    _DECLARED_METHODS,
    _DECLARED_STATICMETHODS,
    _MUTABLE_TYPES,
    _MUTOBJ_RESERVED_DUNDERS,
)
from ._fields import (
    AttributeDescriptor,
    Field,
    _format_field_names,
    _get_attribute_descriptor,
    _get_init_fields,
    _get_missing_construction_fields,
    _invalidate_ordered_fields_cache_for,
    _process_field_annotations,
    _validate_field_descriptor,
)
from ._reload import _migrate_registries, _update_class_inplace
from ._state import (
    _attribute_registry,
    _class_registry,
    _classvar_registry,
    _impl_chain,
    bump_registry_generation,
)
from ._typing_utils import _is_classvar

T = TypeVar("T", bound="Declaration")


def _property_return_annotation(prop: property) -> Any:
    if prop.fget is None:
        return Any
    return getattr(prop.fget, "__annotations__", {}).get("return", Any)


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
        declared_classmethods: set[str] = set()
        declared_staticmethods: set[str] = set()

        # 强制所有 Declaration 子类拥有空 __slots__，禁止 Python 默认为子类加 __dict__。
        # 注意必须在 super().__new__ 之前写入 namespace。
        if name != "Declaration" and "__slots__" not in namespace:
            namespace["__slots__"] = ()

        cls = super().__new__(mcs, name, bases, namespace)

        if name == "Declaration" and not bases:
            declared: set[str] = set()
            for hook_name in _DECLARATION_CHAIN_HOOKS:
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

        # 调用共享字段处理函数：Declaration / Extension / Implementation 都走这一步。
        descriptors, classvar_attrs, inherited_redeclared = _process_field_annotations(
            annotations, namespace, module, cls, parent_classvars,
        )
        attr_registry: dict[str, Any] = {}
        for attr_name, descriptor in descriptors:
            setattr(cls, attr_name, descriptor)
            attr_registry[attr_name] = descriptor.annotation
        # 父类已有描述符、本类仅重复声明 annotation 的字段：
        # 记入本类 registry 以保持字段顺序（与原逻辑一致）。
        for attr_name, attr_type in inherited_redeclared:
            attr_registry[attr_name] = attr_type

        own_annotations = getattr(cls, "__annotations__", {})
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
                    owner_cls=cls,
                )
            elif isinstance(value, _MUTABLE_TYPES):
                type_name = type(value).__name__  # pyright: ignore[reportUnknownArgumentType]
                raise TypeError(
                    f"Declaration '{name}' attribute '{attr_name}' uses mutable default "
                    f"value {type_name}. "
                    f"Use field(default_factory={type_name}) instead."
                )
            else:
                descriptor = AttributeDescriptor(
                    attr_name,
                    parent_desc.annotation,
                    default=value,
                    owner_cls=cls,
                )
            _validate_field_descriptor(name, descriptor)
            setattr(cls, attr_name, descriptor)
            attr_registry[attr_name] = parent_desc.annotation

        _attribute_registry[cls] = attr_registry
        _classvar_registry[cls] = classvar_attrs

        for prop_name, prop_value in namespace.items():
            if prop_name in _MUTOBJ_RESERVED_DUNDERS:
                continue
            if isinstance(prop_value, property):
                descriptor = AttributeDescriptor(
                    prop_name,
                    _property_return_annotation(prop_value),
                    init=False,
                    owner_cls=cls,
                    readonly=prop_value.fset is None,
                    has_storage=False,
                    fget=prop_value.fget,
                    fset=prop_value.fset,
                )
                setattr(cls, prop_name, descriptor)
                if prop_value.fget is not None:
                    prop_value.fget.__mutobj_class__ = cls
                    _impl_chain.setdefault((cls, f"{prop_name}.getter"), []).append(
                        (prop_value.fget, "__default__", 0)
                    )
                if prop_value.fset is not None:
                    prop_value.fset.__mutobj_class__ = cls
                    _impl_chain.setdefault((cls, f"{prop_name}.setter"), []).append(
                        (prop_value.fset, "__default__", 0)
                    )

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
                    delegate.__doc__ = getattr(b, mn).__doc__
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
                    delegate.__doc__ = getattr(b.__dict__[mn].__func__, "__doc__", None) if mn in b.__dict__ and hasattr(b.__dict__[mn], "__func__") else None
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
                    delegate.__doc__ = getattr(b.__dict__[mn].__func__, "__doc__", None) if mn in b.__dict__ and hasattr(b.__dict__[mn], "__func__") else None
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
            from ._implementation import _prepare_implementation_instance

            impl = _prepare_implementation_instance(obj)
            cls.__init__(obj, *args, **kwargs)
            obj.__post_init__()  # type: ignore[attr-defined]
            missing_fields = _get_missing_construction_fields(obj)
            if missing_fields:
                raise TypeError(
                    f"{type(obj).__name__} missing field(s) after construction: "
                    f"{_format_field_names(missing_fields)}. Either pass them to __init__ "
                    f"or assign in __post_init__."
                )
            # Implementation 字段完整性检查：与 Declaration 对标。
            if impl is not None:
                missing_impl_fields = _get_missing_construction_fields(impl)
                if missing_impl_fields:
                    raise TypeError(
                        f"{type(impl).__name__} missing field(s) after construction: "
                        f"{_format_field_names(missing_impl_fields)}. Either pass them "
                        f"through to Implementation.__init__ or provide default/default_factory."
                    )
        return obj

    def __setattr__(cls, name: str, value: Any) -> None:
        if isinstance(value, AttributeDescriptor):
            _validate_field_descriptor(cls.__name__, value)
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
                owner_cls=cls,
                readonly=desc.readonly,
                has_storage=desc.has_storage,
            )
        else:
            new_desc = AttributeDescriptor(
                name,
                desc.annotation,
                default=value,
                owner_cls=cls,
                readonly=desc.readonly,
                has_storage=desc.has_storage,
            )
        _validate_field_descriptor(cls.__name__, new_desc)
        super().__setattr__(name, new_desc)

        if from_base and cls in _attribute_registry and name not in _attribute_registry[cls]:  # pyright: ignore[reportUnnecessaryContains]
            _attribute_registry[cls][name] = desc.annotation
        _invalidate_ordered_fields_cache_for(cls)


class Declaration(metaclass=DeclarationMeta):
    """Base class for mutobj declarations."""

    # __weakref__：_implementation_instance_registry 是 WeakKeyDictionary，需要实例可弱引用。
    # _mutobj_storage：存放所有字段值的内部 dict，替代原来的实例 __dict__。
    # 使用单下划线而非双下划线：避免 Python name mangling 在跨类访问（AttributeDescriptor / 模块级函数）中失效。
    __slots__ = ("__weakref__", "_mutobj_storage")

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        obj = super().__new__(cls)
        # 字段值存储区；默认值不再热切预填，由 AttributeDescriptor._storage_get 首次访问时 lazy 求值。
        obj._mutobj_storage = {}
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
