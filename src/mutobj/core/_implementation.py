from __future__ import annotations

import weakref
from typing import Any, ClassVar, Generic, TypeVar, cast

from ._constants import (
    DECLARATION_CHAIN_HOOKS,
    MUTOBJ_INFRA_ATTRS,
)
from ._classmeta import ImplementationClassMeta
from ._declaration import Declaration
from ._fields import get_attribute_descriptor, process_field_annotations
from ._impls import apply_impl, register_to_chain
from ._discovery import (
    bump_registry_generation,
)
from ._typing_utils import is_classvar

T = TypeVar("T", bound=Declaration)
IT = TypeVar("IT", bound="Implementation[Any]")


def _impl_meta(cls: type) -> ImplementationClassMeta:
    """Get the ImplementationClassMeta for an Implementation subclass."""
    return cast(ImplementationClassMeta, getattr(cls, "__mutobj_class_meta__"))


def _implementation_source_key(impl_cls: type) -> str:
    return f"{impl_cls.__module__}::implementation::{impl_cls.__qualname__}"


def _bind_implementation_instance(decl: Declaration, impl: Implementation[Any]) -> None:
    """Bind an Implementation instance to a Declaration instance."""
    decl.__mutobj_storage__["__impl__"] = impl
    impl.__mutobj_storage__["__owner__"] = weakref.ref(decl)


def _resolve_target_class(impl_cls: type) -> type[Declaration] | None:
    # 延迟绑定——Implementation 基类本身进入元类 __new__ 时 Implementation 还未赋值。
    impl_base = globals().get("Implementation")
    for base in impl_cls.__dict__.get("__orig_bases__", ()):
        origin = getattr(base, "__origin__", None)
        if not isinstance(origin, type):
            continue
        if impl_base is None:
            # 初次定义 Implementation 本身时跳过。
            continue
        if origin is not impl_base and not issubclass(origin, impl_base):
            continue
        args = getattr(base, "__args__", ())
        if not args:
            continue
        target_cls = args[0]
        if not isinstance(target_cls, type) or not issubclass(target_cls, Declaration):
            raise TypeError("Implementation[T] requires a mutobj.Declaration subclass")
        return target_cls
    return None


def _lookup_implementation_class(
    decl_cls: type[T],
) -> type["Implementation[T]"] | None:
    for klass in decl_cls.__mro__:
        meta = getattr(klass, "__mutobj_class_meta__", None)
        if meta is None:
            continue
        impl_cls = meta.impl_class
        if impl_cls is not None:
            return cast(type[Implementation[T]], impl_cls)
    return None


def _lookup_implementation_instance(decl: Declaration, impl_cls: type[IT]) -> IT | None:
    impl = decl.__mutobj_storage__.get("__impl__")
    if impl is None or not isinstance(impl, impl_cls):
        return None
    return impl


def _lookup_implementation_owner(impl: Implementation[Any]) -> Declaration | None:
    try:
        storage = impl.__mutobj_storage__
    except AttributeError:
        return None
    owner_ref = storage.get("__owner__")
    if owner_ref is None:
        return None
    return cast(weakref.ReferenceType[Declaration], owner_ref)()



def _implementation_bridge(
    target_cls: type[Declaration],
    impl_cls: type,
    method_name: str,
    impl_method: Any,
    source_key: str,
) -> Any:
    def bridge(decl: Declaration, *args: Any, **kwargs: Any) -> Any:
        impl = decl.__mutobj_storage__.get("__impl__")
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
    became_top = register_to_chain(target_cls, impl_key, bridge, source_key)
    if became_top:
        apply_impl(target_cls, impl_key, bridge)


def _register_implementation_methods(
    impl_cls: type,
    target_cls: type[Declaration],
) -> None:
    source_key = _implementation_source_key(impl_cls)
    declared_methods: set[str] = target_cls.__mutobj_class_meta__.methods
    bridged_methods = declared_methods | DECLARATION_CHAIN_HOOKS

    for method_name, method_value in impl_cls.__dict__.items():
        target_desc = get_attribute_descriptor(target_cls, method_name)
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
            and method_name not in DECLARATION_CHAIN_HOOKS
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
        became_top = register_to_chain(target_cls, method_name, bridge, source_key)
        if became_top:
            apply_impl(target_cls, method_name, bridge)


def _register_implementation_class(
    impl_cls: type,
    target_cls: type[Declaration],
) -> None:
    existing_impl = target_cls.__mutobj_class_meta__.impl_class
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
        base_meta = getattr(base, "__mutobj_class_meta__", None)
        if base_meta is None:
            continue
        parent_impl = base_meta.impl_class
        if parent_impl is not None:
            break
    if parent_impl is not None and not issubclass(impl_cls, parent_impl):
        raise TypeError(
            f"{impl_cls.__name__} must inherit from {parent_impl.__name__} "
            f"because {target_cls.__name__} inherits its Declaration methods"
        )

    _impl_meta(impl_cls).target_class = target_cls
    target_cls.__mutobj_class_meta__.impl_class = impl_cls
    _register_implementation_methods(impl_cls, target_cls)
    bump_registry_generation()


def prepare_implementation_instance(decl: Declaration) -> Any | None:
    if "__impl__" in decl.__mutobj_storage__:
        return decl.__mutobj_storage__["__impl__"]

    impl_cls = _lookup_implementation_class(type(decl))
    if impl_cls is None:
        return None

    impl = impl_cls.__new__(impl_cls)
    if not isinstance(impl, impl_cls):
        raise TypeError(
            f"{impl_cls.__name__}.__new__ returned {type(impl).__name__}, "
            f"expected {impl_cls.__name__}"
        )
    # 始终初始化 __mutobj_storage__：基类 __slots__ 保证了它的存在。
    # 声明字段赋值时 AttributeDescriptor 写入此处；未声明（有 __dict__ 时）走 __dict__。
    impl.__mutobj_storage__ = {}
    _bind_implementation_instance(decl, impl)
    return impl


class ImplementationMeta(type):
    """Implementation 元类。与 ExtensionMeta 对称。

    职责：
    1. 默认注入 ``__slots__ = ()``，避免子类默认获得 ``__dict__``。
    2. 扫描 annotations 创建 AttributeDescriptor（调共享 ``process_field_annotations``）。
    3. 解析 ``Implementation[T]`` 的 T 并调 ``_register_implementation_class``。

    子类可显式 ``__slots__ = ("__dict__",)`` 附加 ``__dict__``：annotations 仍处理为
    descriptor（声明字段走 ``__mutobj_storage__``），未声明字段自然走 ``__dict__``。
    """

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
    ) -> ImplementationMeta:
        # 子类若已显式 __slots__ 含 __dict__，则不注入 __slots__ = ()——
        # 否则 __slots__ = () 会覆盖用户的声明（Python 子类 __slots__ 只增不减）。
        user_slots = namespace.get("__slots__")
        user_has_dict = (
            user_slots is not None
            and "__dict__" in (user_slots if isinstance(user_slots, (tuple, list)) else (user_slots,))
        )

        if name != "Implementation" and "__slots__" not in namespace and not user_has_dict:
            namespace["__slots__"] = ()

        cls = super().__new__(mcs, name, bases, namespace)

        if name == "Implementation" and not bases:
            return cls

        # Python 3.14 PEP 649 lazy annotations 下 namespace["__annotations__"] 可能为空，
        # 必须走 getattr(cls, "__annotations__")。
        annotations = getattr(cls, "__annotations__", {})
        module = namespace.get("__module__", "")
        parent_classvars: set[str] = set()
        for base in cls.__mro__[1:]:
            base_anns = getattr(base, "__annotations__", {})
            base_module = getattr(base, "__module__", "")
            for base_attr, base_type in base_anns.items():
                if is_classvar(base_type, base_module):
                    parent_classvars.add(base_attr)

        descriptors, _classvar_attrs, inherited_redeclared = process_field_annotations(
            annotations, namespace, module, cls, parent_classvars, skip=MUTOBJ_INFRA_ATTRS,
        )
        attr_registry: dict[str, Any] = {}
        for attr_name, descriptor in descriptors:
            type.__setattr__(cls, attr_name, descriptor)
            attr_registry[attr_name] = descriptor.annotation
        for attr_name, attr_type in inherited_redeclared:
            attr_registry[attr_name] = attr_type
        if attr_registry:
            cast(Any, cls).__mutobj_class_meta__ = ImplementationClassMeta(fields=attr_registry)
            bump_registry_generation()
        else:
            cast(Any, cls).__mutobj_class_meta__ = ImplementationClassMeta()

        # target_class 解析与注册（原 __init_subclass__ 逻辑平移）。
        target_cls = _resolve_target_class(cls)
        if target_cls is not None:
            _register_implementation_class(cls, target_cls)

        return cls


class Implementation(Generic[T], metaclass=ImplementationMeta):
    # 字段走 __mutobj_storage__ + descriptor。
    # 子类可 __slots__ = ("__dict__",) 附加 __dict__：声明字段 → descriptor，未声明 → __dict__。
    # __weakref__ 不需要：owner 信息通过 __mutobj_storage__ 上的 weakref 追溯 decl。
    __slots__ = ("__mutobj_storage__",)
    __mutobj_storage__: dict[str, Any]
    __mutobj_class_meta__: ClassVar[ImplementationClassMeta]


def implementation_class(
    decl_cls: type[T],
) -> type[Implementation[T]]:
    impl_cls = _lookup_implementation_class(decl_cls)
    if impl_cls is None:
        raise LookupError(
            f"No Implementation class is registered for {decl_cls.__name__}"
        )
    return impl_cls


def implementation_of(decl: Declaration, impl_cls: type[IT]) -> IT:
    impl = _lookup_implementation_instance(decl, impl_cls)
    if impl is not None:
        return impl

    actual_impl = decl.__mutobj_storage__.get("__impl__")
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
    owner = _lookup_implementation_owner(impl)
    if owner is None:
        raise LookupError(
            f"No Declaration owner is associated with {type(impl).__name__} instance"
        )
    return cast(T, owner)
