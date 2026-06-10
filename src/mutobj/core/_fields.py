from __future__ import annotations

from typing import Any, Callable, Mapping, TypeVar

from ._constants import MUTABLE_TYPES
from ._typing_utils import is_classvar

_F = TypeVar("_F")


class _MissingSentinel:
    """Default-value sentinel used to distinguish unset from None."""

    _instance: _MissingSentinel | None = None

    def __new__(cls) -> _MissingSentinel:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING: Any = _MissingSentinel()


class Field:
    """Attribute default-value descriptor, created by field()."""

    __slots__ = ("default", "default_factory", "init")

    def __init__(
        self,
        default: Any = MISSING,
        default_factory: Callable[[], Any] | None = None,
        init: bool = True,
    ) -> None:
        if default is not MISSING and default_factory is not None:
            raise TypeError("cannot specify both default and default_factory")
        self.default = default
        self.default_factory = default_factory
        self.init = init


def field(
    *,
    default: Any = MISSING,
    default_factory: Callable[[], Any] | None = None,
    init: bool = True,
) -> Any:
    return Field(default=default, default_factory=default_factory, init=init)


class AttributeDescriptor:
    """Attribute descriptor used for declaration fields."""

    __slots__ = (
        "name",
        "annotation",
        "default",
        "default_factory",
        "init",
        "owner_cls",
        "readonly",
        "_has_storage",
        "_fget",
        "_fset",
        "_default_fget",
        "_default_fset",
    )

    def __init__(
        self,
        name: str,
        annotation: Any,
        default: Any = MISSING,
        default_factory: Callable[[], Any] | None = None,
        init: bool = True,
        *,
        owner_cls: type[Any] | None = None,
        readonly: bool = False,
        has_storage: bool = True,
        fget: Callable[..., Any] | None = None,
        fset: Callable[..., Any] | None = None,
    ) -> None:
        self.name = name
        self.annotation = annotation
        self.default = default
        self.default_factory = default_factory
        self.init = init
        self.owner_cls = owner_cls
        self._has_storage = has_storage
        self.readonly = readonly
        if has_storage:
            self._default_fget = self._storage_get
            self._default_fset = None if readonly else self._storage_set
        else:
            self._default_fget = fget
            self._default_fset = fset
        self._fget = self._default_fget
        self._fset = self._default_fset

    @property
    def has_default(self) -> bool:
        return self.default is not MISSING or self.default_factory is not None

    @property
    def has_storage(self) -> bool:
        return self._has_storage

    @property
    def getter(self) -> "AttributeGetterPlaceholder":
        return AttributeGetterPlaceholder(self)

    @property
    def setter(self) -> "AttributeSetterPlaceholder":
        return AttributeSetterPlaceholder(self)

    def get_default(self) -> Any:
        if self.default is not MISSING:
            return self.default
        if self.default_factory is not None:
            return self.default_factory
        raise ValueError(f"Attribute '{self.name}' has no default")

    def make_default(self) -> Any:
        if self.default_factory is not None:
            return self.default_factory()
        if self.default is not MISSING:
            return self.default
        raise ValueError(f"Attribute '{self.name}' has no default")

    def _storage_get(self, obj: Any) -> Any:
        # 字段值统一存放在 obj.__mutobj_storage__（dict），lazy 求值默认值：
        # - 已显式赋值：直接命中
        # - default_factory：首次访问求值并缓存（保证多次访问拿到同一对象）
        # - default（不可变）：每次返回 self.default，不写入 storage（节省内存）
        # - 无默认值：抛 AttributeError
        storage: dict[str, Any] = obj.__mutobj_storage__
        try:
            return storage[self.name]
        except KeyError:
            if self.default_factory is not None:
                value = self.default_factory()
                storage[self.name] = value
                return value
            if self.default is not MISSING:
                return self.default
            raise AttributeError(
                f"'{type(obj).__name__}' object has no attribute '{self.name}'"
            ) from None

    def _storage_set(self, obj: Any, value: Any) -> None:
        obj.__mutobj_storage__[self.name] = value

    def restore_default_getter(self) -> None:
        self._fget = self._default_fget

    def restore_default_setter(self) -> None:
        self._fset = self._default_fset

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        if self._fget is None:
            owner_name = self.owner_cls.__name__ if self.owner_cls is not None else "<unknown>"
            raise NotImplementedError(
                f"Property '{self.name}' getter is not implemented. "
                f"Use @mutobj.impl({owner_name}.{self.name}.getter) to provide implementation."
            )
        return self._fget(obj)

    def __set__(self, obj: Any, value: Any) -> None:
        if self._fset is None:
            owner_name = self.owner_cls.__name__ if self.owner_cls is not None else "<unknown>"
            raise AttributeError(
                f"Property '{self.name}' is read-only or setter is not implemented. "
                f"Use @mutobj.impl({owner_name}.{self.name}.setter) to provide implementation."
            )
        self._fset(obj, value)

    def __delete__(self, obj: Any) -> None:
        try:
            del obj.__mutobj_storage__[self.name]
        except KeyError as exc:
            raise AttributeError(
                f"'{type(obj).__name__}' object has no attribute '{self.name}'"
            ) from exc


class AttributeGetterPlaceholder:
    def __init__(self, descriptor: AttributeDescriptor):
        self.descriptor = descriptor


class AttributeSetterPlaceholder:
    def __init__(self, descriptor: AttributeDescriptor):
        self.descriptor = descriptor


_ordered_fields_cache: dict[type, list[str]] = {}


def invalidate_ordered_fields_cache_for(cls: type) -> None:
    for cached_cls in list(_ordered_fields_cache):
        try:
            if issubclass(cached_cls, cls):
                _ordered_fields_cache.pop(cached_cls, None)
        except TypeError:
            _ordered_fields_cache.pop(cached_cls, None)


def _get_ordered_fields(cls: type) -> list[str]:
    cached = _ordered_fields_cache.get(cls)
    if cached is not None:
        return cached

    seen: set[str] = set()
    ordered: list[str] = []
    for klass in cls.__mro__[1:]:
        meta = getattr(klass, "__mutobj_class_meta__", None)
        if meta is not None:
            for attr_name in meta.fields:
                if attr_name not in seen:
                    seen.add(attr_name)
                    ordered.append(attr_name)

    own_meta = getattr(cls, "__mutobj_class_meta__", None)
    if own_meta is not None:
        for attr_name in own_meta.fields:
            if attr_name not in seen:
                seen.add(attr_name)
                ordered.append(attr_name)

    _ordered_fields_cache[cls] = ordered
    return ordered


def get_attribute_descriptor(cls: type, attr_name: str) -> AttributeDescriptor | None:
    for klass in cls.__mro__:
        desc = klass.__dict__.get(attr_name)
        if isinstance(desc, AttributeDescriptor):
            return desc
    return None


def get_init_fields(cls: type) -> list[str]:
    return [
        attr_name
        for attr_name in _get_ordered_fields(cls)
        if (desc := get_attribute_descriptor(cls, attr_name)) is not None and desc.init
    ]


def field_default(field: _F, /) -> _F:
    if not isinstance(field, AttributeDescriptor):
        raise TypeError(
            f"field_default(field) expects a class-level field token (e.g. Cls.field_name), "
            f"got {type(field).__name__!r}. Use mutobj.fields(cls)[name].make_default() "
            f"for dynamic field-name access."
        )
    return field.make_default()


def field_info(field: object, /) -> AttributeDescriptor:
    if not isinstance(field, AttributeDescriptor):
        raise TypeError(
            f"field_info(field) expects a class-level field token (e.g. Cls.field_name), "
            f"got {type(field).__name__!r}."
        )
    return field


def fields(cls: type, /) -> Mapping[str, AttributeDescriptor]:
    result: dict[str, AttributeDescriptor] = {}
    for name in _get_ordered_fields(cls):
        desc = get_attribute_descriptor(cls, name)
        if desc is not None:
            result[name] = desc
    return result


def format_field_names(field_names: list[str]) -> str:
    """将字段名列表格式化为 "'a', 'b', 'c'" 形式，用于错误信息。"""
    return ", ".join(f"'{name}'" for name in field_names)


def validate_field_descriptor(owner_name: str, descriptor: AttributeDescriptor) -> None:
    """校验字段描述符合法性：has_storage + init=False 必须带 default。

    供 Declaration / Extension / Implementation 三套元类共享。错误文案不再带
    类别前缀（"Declaration" / "Extension" 等），只用 owner_name 标识所属类。
    """
    if descriptor.has_storage and not descriptor.init and not descriptor.has_default:
        raise TypeError(
            f"'{owner_name}' field '{descriptor.name}' is init=False but has no "
            f"default; provide default/default_factory or set init=True."
        )


def get_missing_construction_fields(obj: Any) -> list[str]:
    """返回 obj 中所有「必填且尚未赋值」的字段名（按字段声明顺序）。

    duck-typing 依赖 obj.__mutobj_storage__（dict[str, Any]）。供 Declaration /
    Extension / Implementation 三处构造完成后的字段完整性检查共用。
    """
    missing: list[str] = []
    storage: dict[str, Any] = obj.__mutobj_storage__
    cls: type[Any] = obj.__class__
    for attr_name, desc in fields(cls).items():
        # has_default 的字段不需要出现在 storage（lazy default 不写入）；
        # 只有必填字段（无默认值且 has_storage）才需检查是否被赋值。
        if desc.has_storage and not desc.has_default and desc.name not in storage:
            missing.append(attr_name)
    return missing


def process_field_annotations(
    annotations: dict[str, Any],
    namespace: dict[str, Any],
    module: str,
    owner_cls: type,
    parent_classvars: set[str] | None = None,
    skip: frozenset[str] = frozenset(),
) -> tuple[list[tuple[str, AttributeDescriptor]], set[str], list[tuple[str, Any]]]:
    """扫描本类 annotations，过滤 ClassVar，为每个字段创建 AttributeDescriptor。

    skip: 内部基础设施属性名集合，不进 field 系统。

    返回:
        (field_descriptors, classvar_attrs, inherited_redeclared)
        - field_descriptors: [(attr_name, descriptor), ...]，调用方负责挂载到 cls 上
          及更新 _attribute_registry
        - classvar_attrs: 本类 annotations 中识别为 ClassVar 的字段名集合
        - inherited_redeclared: 父类已有 AttributeDescriptor、本类仅重复声明 annotation
          但未提供新值的字段 [(attr_name, attr_type), ...]。Declaration 需要将其
          记入自身 attr_registry 以保持字段顺序；Extension/Implementation 可忽略。

    注意：此函数只处理本类 annotations，不处理父类字段覆写（Declaration 独有逻辑）。
    Extension / Implementation 的简单字段声明走这一条路即可。
    """
    if parent_classvars is None:
        parent_classvars = set()
    classvar_attrs: set[str] = set()
    descriptors: list[tuple[str, AttributeDescriptor]] = []
    inherited_redeclared: list[tuple[str, Any]] = []
    owner_name = owner_cls.__name__

    for attr_name, attr_type in annotations.items():
        if attr_name in skip:
            continue
        if is_classvar(attr_type, module) or attr_name in parent_classvars:
            classvar_attrs.add(attr_name)
            value = namespace.get(attr_name)
            if isinstance(value, Field):
                raise TypeError(
                    f"'{owner_name}' attribute '{attr_name}' is ClassVar "
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
                owner_cls=owner_cls,
            )
        elif attr_name in namespace and not isinstance(value, AttributeDescriptor):
            if callable(value) or isinstance(value, property):
                continue
            if isinstance(value, MUTABLE_TYPES):
                type_name = type(value).__name__  # pyright: ignore[reportUnknownArgumentType]
                raise TypeError(
                    f"'{owner_name}' attribute '{attr_name}' uses mutable default "
                    f"value {type_name}. "
                    f"Use field(default_factory={type_name}) instead."
                )
            descriptor = AttributeDescriptor(
                attr_name,
                attr_type,
                default=value,
                owner_cls=owner_cls,
            )
        elif not hasattr(owner_cls, attr_name) or not isinstance(
            getattr(owner_cls, attr_name), AttributeDescriptor
        ):
            descriptor = AttributeDescriptor(attr_name, attr_type, owner_cls=owner_cls)
        else:
            # 父类已是 AttributeDescriptor、本类无新值：仅重复声明 annotation。
            # Declaration 需要记入自身 attr_registry，Extension/Implementation 不需。
            inherited_redeclared.append((attr_name, attr_type))
            continue

        validate_field_descriptor(owner_name, descriptor)
        descriptors.append((attr_name, descriptor))

    return descriptors, classvar_attrs, inherited_redeclared
