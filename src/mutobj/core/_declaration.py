from __future__ import annotations

from typing import Any, Callable, ClassVar, Self, TypeVar, cast

from ._classmeta import DeclarationClassMeta, ImplChainEntry
from ._constants import (
    DECLARATION_CHAIN_HOOKS,
    MUTABLE_TYPES,
    MUTOBJ_RESERVED_DUNDERS,
)
from ._fields import (
    AttributeDescriptor,
    Field,
    format_field_names,
    get_attribute_descriptor,
    get_init_fields,
    get_missing_construction_fields,
    invalidate_ordered_fields_cache_for,
    process_field_annotations,
    validate_field_descriptor,
)
from ._reload import migrate_registries, update_class_inplace
from ._discovery import (
    bump_registry_generation,
    class_registry,
)
from ._typing_utils import is_classvar


T = TypeVar("T", bound="Declaration")


def _decl_meta(cls: type) -> DeclarationClassMeta:
    """Get the DeclarationClassMeta for a Declaration subclass."""
    return cast(DeclarationClassMeta, getattr(cls, "__mutobj_class_meta__"))


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

        declared_methods: set[str] = set()
        declared_classmethods: set[str] = set()
        declared_staticmethods: set[str] = set()

        # 强制所有 Declaration 子类拥有空 __slots__，禁止 Python 默认为子类加 __dict__。
        # 注意必须在 super().__new__ 之前写入 namespace。
        if name != "Declaration" and "__slots__" not in namespace:
            namespace["__slots__"] = ()

        cls = super().__new__(mcs, name, bases, namespace)

        if name == "Declaration" and not bases:
            cls.__mutobj_class_meta__ = DeclarationClassMeta()
            for hook_name in DECLARATION_CHAIN_HOOKS:
                hook = namespace.get(hook_name)
                if callable(hook):
                    hook.__mutobj_class__ = cls
                    _decl_meta(cls).impl_chains.setdefault(hook_name, []).append(ImplChainEntry(func=hook, source_module="__default__", seq=0))
                    _decl_meta(cls).methods.add(hook_name)
            return cls

        annotations = getattr(cls, "__annotations__", {})

        # 初始化 per-class 元数据容器
        cls.__mutobj_class_meta__ = DeclarationClassMeta()

        parent_classvars: set[str] = set()
        module = namespace.get("__module__", "")
        for base in cls.__mro__[1:]:
            base_meta = getattr(base, "__mutobj_class_meta__", None)
            if base_meta is not None:
                parent_classvars.update(base_meta.classvars)
            base_anns = getattr(base, "__annotations__", {})
            base_module = getattr(base, "__module__", "")
            for base_attr, base_type in base_anns.items():
                if is_classvar(base_type, base_module):
                    parent_classvars.add(base_attr)

        # 调用共享字段处理函数：Declaration / Extension / Implementation 都走这一步。
        descriptors, classvar_attrs, inherited_redeclared = process_field_annotations(
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
            elif isinstance(value, MUTABLE_TYPES):
                type_name = type(cast(object, value)).__name__
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
            validate_field_descriptor(name, descriptor)
            setattr(cls, attr_name, descriptor)
            attr_registry[attr_name] = parent_desc.annotation

        _decl_meta(cls).fields = attr_registry
        _decl_meta(cls).classvars = classvar_attrs

        mc = _decl_meta(cls)

        for prop_name, prop_value in namespace.items():
            if prop_name in MUTOBJ_RESERVED_DUNDERS:
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
                    mc.impl_chains.setdefault(f"{prop_name}.getter", []).append(
                        ImplChainEntry(func=prop_value.fget, source_module="__default__", seq=0)
                    )
                if prop_value.fset is not None:
                    prop_value.fset.__mutobj_class__ = cls
                    mc.impl_chains.setdefault(f"{prop_name}.setter", []).append(
                        ImplChainEntry(func=prop_value.fset, source_module="__default__", seq=0)
                    )

        for method_name, method_value in namespace.items():
            if method_name in MUTOBJ_RESERVED_DUNDERS:
                continue
            if isinstance(method_value, classmethod):
                func: Any = cast(Any, method_value).__func__
                declared_classmethods.add(method_name)
                mc.impl_chains.setdefault(method_name, []).append(ImplChainEntry(func=func, source_module="__default__", seq=0))
                func.__mutobj_class__ = cls

        for method_name, method_value in namespace.items():
            if method_name in MUTOBJ_RESERVED_DUNDERS:
                continue
            if isinstance(method_value, staticmethod):
                func: Any = cast(Any, method_value).__func__
                declared_staticmethods.add(method_name)
                mc.impl_chains.setdefault(method_name, []).append(ImplChainEntry(func=func, source_module="__default__", seq=0))
                func.__mutobj_class__ = cls

        for method_name, method_value in namespace.items():
            if method_name in MUTOBJ_RESERVED_DUNDERS:
                continue
            if callable(method_value) and not isinstance(method_value, (classmethod, staticmethod, property)):
                declared_methods.add(method_name)
                mc.impl_chains.setdefault(method_name, []).append(ImplChainEntry(func=method_value, source_module="__default__", seq=0))
                method_value.__mutobj_class__ = cls

        # 委托生成：父类声明的方法自动继承到子类
        for base in cls.__mro__[1:]:
            if base is object:
                continue
            base_meta = getattr(base, "__mutobj_class_meta__", None)
            if base_meta is None:
                continue

            for method_name in base_meta.methods:
                if method_name in declared_methods or method_name in mc.impl_chains:
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
                mc.impl_chains[method_name] = [ImplChainEntry(func=delegate, source_module="__default__", seq=0)]
                setattr(cls, method_name, delegate)
                declared_methods.add(method_name)

            for method_name in base_meta.classmethods:
                if method_name in declared_classmethods or method_name in mc.impl_chains:
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
                mc.impl_chains[method_name] = [ImplChainEntry(func=delegate, source_module="__default__", seq=0)]
                setattr(cls, method_name, classmethod(delegate))
                declared_classmethods.add(method_name)

            for method_name in base_meta.staticmethods:
                if method_name in declared_staticmethods or method_name in mc.impl_chains:
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
                mc.impl_chains[method_name] = [ImplChainEntry(func=delegate, source_module="__default__", seq=0)]
                setattr(cls, method_name, staticmethod(delegate))
                declared_staticmethods.add(method_name)

        mc.methods = declared_methods
        mc.classmethods = declared_classmethods
        mc.staticmethods = declared_staticmethods

        existing = class_registry.get(key)
        if existing is not None and existing is not cast(type, cls):
            update_class_inplace(existing, cls)
            migrate_registries(existing, cls)
            bump_registry_generation()
            return existing

        class_registry[key] = cls
        bump_registry_generation()
        return cls

    # pyright/mypy 元类 __call__ 的已知局限：cls: type[T] 在语义上完全正确
    # (T 是 Declaration 子类实例)，但类型检查器要求 cls 必须是 DeclarationMeta
    # 或其超类型。当前 typing 体系无法同时表达"cls 是元类实例"和"返回值是 T"。
    # 官方结论：只能用 # type: ignore[misc] 抑制。
    # 参见 https://github.com/microsoft/pyright/discussions/5561
    def __call__(cls: type[T], *args: Any, **kwargs: Any) -> T:  # type: ignore[misc]
        obj = cls.__new__(cls, *args, **kwargs)
        if isinstance(obj, cls):
            from ._implementation import prepare_implementation_instance

            impl = prepare_implementation_instance(obj)
            cls.__init__(obj, *args, **kwargs)
            obj.__post_init__()
            missing_fields = get_missing_construction_fields(obj)
            if missing_fields:
                raise TypeError(
                    f"{type(obj).__name__} missing field(s) after construction: "
                    f"{format_field_names(missing_fields)}. Either pass them to __init__ "
                    f"or assign in __post_init__."
                )
            # Implementation 字段完整性检查：与 Declaration 对标。
            if impl is not None:
                missing_impl_fields = get_missing_construction_fields(impl)
                if missing_impl_fields:
                    raise TypeError(
                        f"{type(impl).__name__} missing field(s) after construction: "
                        f"{format_field_names(missing_impl_fields)}. Either pass them "
                        f"through to Implementation.__init__ or provide default/default_factory."
                    )
        return obj

    def __setattr__(cls, name: str, value: Any) -> None:
        if isinstance(value, AttributeDescriptor):
            validate_field_descriptor(cls.__name__, value)
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

        if isinstance(value, MUTABLE_TYPES):
            type_name = type(cast(object, value)).__name__
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
        validate_field_descriptor(cls.__name__, new_desc)
        super().__setattr__(name, new_desc)

        if from_base and name not in _decl_meta(cls).fields:
            _decl_meta(cls).fields[name] = desc.annotation
        invalidate_ordered_fields_cache_for(cls)


class Declaration(metaclass=DeclarationMeta):
    """Base class for mutobj declarations."""

    # __weakref__：_implementation_instance_registry 是 WeakKeyDictionary，需要实例可弱引用。
    # __mutobj_storage__：存放所有字段值的内部 dict，替代原来的实例 __dict__。
    __slots__ = ("__weakref__", "__mutobj_storage__")
    __mutobj_storage__: dict[str, Any]
    __mutobj_class_meta__: ClassVar[DeclarationClassMeta]

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        obj = super().__new__(cls)
        # 字段值存储区；默认值不再热切预填，由 AttributeDescriptor._storage_get 首次访问时 lazy 求值。
        obj.__mutobj_storage__ = {}
        return obj

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if args:
            init_fields = get_init_fields(type(self))
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
            desc = get_attribute_descriptor(type(self), attr_name)
            if isinstance(desc, AttributeDescriptor) and not desc.init:
                raise TypeError(
                    f"{type(self).__name__}() got an unexpected keyword argument '{attr_name}'"
                )
            setattr(self, attr_name, value)

    def __post_init__(self) -> None:
        pass


def get_declaration_func(cls: type, method_name: str) -> Callable[..., Any] | None:
    """Return the default (declaration-site) implementation of a method."""
    for klass in cls.__mro__:
        meta = getattr(klass, "__mutobj_class_meta__", None)
        if meta is None:
            continue
        chain = meta.impl_chains.get(method_name)
        if not chain:
            continue
        for entry in chain:
            if entry.source_module == "__default__":
                return entry.func
    return None


def get_declaration_doc(cls: type, method_name: str) -> str | None:
    """Return the docstring of the declaration-site implementation of a method."""
    func = get_declaration_func(cls, method_name)
    if func is not None:
        return getattr(func, "__doc__", None)
    return None
