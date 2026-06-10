# pyright: reportPrivateUsage=false
from __future__ import annotations

import weakref
from typing import TYPE_CHECKING, Any, Generic, Self, TypeVar

from ._declaration import Declaration
from ._fields import (
    _format_field_names,
    _get_missing_construction_fields,
    _process_field_annotations,
)
from ._state import _attribute_registry, bump_registry_generation
from ._typing_utils import _is_classvar

T = TypeVar("T", bound=Declaration)

_extension_cache: weakref.WeakKeyDictionary[Declaration, dict[type, Any]] = weakref.WeakKeyDictionary()
_extension_registry: dict[type, list[type["Extension[Any]"]]] = {}


def _resolve_extension_target_class(cls: type) -> type | None:
    """从 Extension 子类的 __orig_bases__ 中解析 Extension[T] 的 T。"""
    # 延迟绑定——Extension 基类本身进入 ExtensionMeta.__new__ 时 Extension 还未赋值。
    extension_cls = globals().get("Extension")
    if extension_cls is None:
        return None
    for base in cls.__dict__.get("__orig_bases__", ()):
        origin = getattr(base, "__origin__", None)
        if origin is not None and isinstance(origin, type) and issubclass(origin, extension_cls):
            args = getattr(base, "__args__", None)
            if args:
                return args[0]  # pyright: ignore[reportUnknownVariableType]
    return None


class ExtensionMeta(type):
    """Extension 元类。

    职责：
    1. 注入 ``__slots__ = ()`` 防止子类自动获得 ``__dict__``——这是严格化的关键。
       Python 子类不显式写 ``__slots__`` 就会自动拥有 ``__dict__``，与基类 slots 无关；
       且 ``__init_subclass__`` 在类创建后才被调用，无法事后追加 ``__slots__``——
       必须在 ``super().__new__`` 之前写入 namespace。
    2. 扫描本类 annotations，过滤 ClassVar，为每个字段创建 ``AttributeDescriptor``
       并挂到类上（共享 ``_process_field_annotations``）。
    3. 解析 ``Extension[T]`` 的目标类并登记到 ``_extension_registry``。
    """

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
    ) -> ExtensionMeta:
        # Extension 基类自身不注入 slots（其 __slots__ 在类体里显式写明）。
        if name != "Extension" and "__slots__" not in namespace:
            namespace["__slots__"] = ()

        cls = super().__new__(mcs, name, bases, namespace)

        if name == "Extension" and not bases:
            return cls

        # 扫 annotations 创建字段描述符。
        # 注：Python 3.14 PEP 649 lazy annotations——namespace["__annotations__"] 可能为空，
        # 必须通过 getattr(cls, "__annotations__") 触发 __annotate_func__ 求值。
        annotations = getattr(cls, "__annotations__", {})
        module = namespace.get("__module__", "")
        # 父类 ClassVar 集合（Extension 没有 _classvar_registry，逐 base 扫 annotations）。
        parent_classvars: set[str] = set()
        for base in cls.__mro__[1:]:
            base_anns = getattr(base, "__annotations__", {})
            base_module = getattr(base, "__module__", "")
            for base_attr, base_type in base_anns.items():
                if _is_classvar(base_type, base_module):
                    parent_classvars.add(base_attr)

        descriptors, _classvar_attrs, inherited_redeclared = _process_field_annotations(
            annotations, namespace, module, cls, parent_classvars,
        )
        attr_registry: dict[str, Any] = {}
        for attr_name, descriptor in descriptors:
            type.__setattr__(cls, attr_name, descriptor)
            attr_registry[attr_name] = descriptor.annotation
        for attr_name, attr_type in inherited_redeclared:
            attr_registry[attr_name] = attr_type
        # 登记到 _attribute_registry，使 fields(cls) / _get_missing_construction_fields
        # 能看到 Extension 子类的字段。
        if attr_registry:
            _attribute_registry[cls] = attr_registry
            bump_registry_generation()

        # target_class 解析与注册。
        target_cls = _resolve_extension_target_class(cls)
        if target_cls is not None:
            cls._target_class = target_cls  # pyright: ignore[reportAttributeAccessIssue]
            _extension_registry.setdefault(target_cls, []).append(
                cls,  # pyright: ignore[reportArgumentType]
            )

        return cls


class Extension(Generic[T], metaclass=ExtensionMeta):
    # __slots__ 含 target 与 _mutobj_storage：禁止任意 setattr，字段统一进 storage。
    # _target_class 是类属性（在 ExtensionMeta.__new__ 中按 Extension[T] 解析后赋值），
    # 不能列入 __slots__——否则与同名类级默认值冲突，import 期 ValueError。
    # target / _mutobj_storage 也不能在类体里赋默认值（同样冲突）。
    # __weakref__ 不需要：_extension_cache 是 WeakKeyDictionary，弱引用的是 Declaration（key），
    # ext 实例本身只被 cache 的 value dict 强引用，无须支持弱引用。
    __slots__ = ("target", "_mutobj_storage")
    _target_class: type | None = None

    if TYPE_CHECKING:
        # 仅供类型检查器识别：run-time 不创建 annotation 默认值（避免与 __slots__ 冲突）。
        target: Declaration | None

    @classmethod
    def get_or_create(cls, instance: T) -> Self:
        if instance not in _extension_cache:
            _extension_cache[instance] = {}

        cache = _extension_cache[instance]
        if cls not in cache:
            ext = cls.__new__(cls)
            # 字段值存储区：与 Declaration 一致，由 AttributeDescriptor._storage_get 在
            # 首次访问时 lazy 求值默认值；显式赋值的字段直接进 storage。
            ext._mutobj_storage = {}  # pyright: ignore[reportAttributeAccessIssue]
            ext.target = instance
            ext.__init__()
            missing = _get_missing_construction_fields(ext)
            if missing:
                raise TypeError(
                    f"{cls.__name__} missing field(s) after construction: "
                    f"{_format_field_names(missing)}. Either provide default/default_factory "
                    f"or assign in __init__."
                )
            cache[cls] = ext

        return cache[cls]

    @classmethod
    def get(cls, instance: T) -> Self | None:
        cache = _extension_cache.get(instance)
        if cache is not None:
            return cache.get(cls)
        return None

    def __init__(self) -> None:
        pass


def extension_types(
    decl_class: type[Declaration],
    filter_type: type | None = None,
) -> list[type[Extension[Any]]]:
    result: list[type[Extension[Any]]] = []
    seen: set[type] = set()
    for klass in decl_class.__mro__:
        for ext_cls in _extension_registry.get(klass, []):
            if ext_cls not in seen:
                seen.add(ext_cls)
                if filter_type is None or issubclass(ext_cls, filter_type):
                    result.append(ext_cls)
    return result


def extensions(
    instance: Declaration,
    filter_type: type | None = None,
) -> list[Extension[Any]]:
    cache = _extension_cache.get(instance)
    if cache is None:
        return []
    if filter_type is None:
        return list(cache.values())
    return [ext for ext in cache.values() if isinstance(ext, filter_type)]
