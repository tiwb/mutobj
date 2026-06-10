# pyright: reportPrivateUsage=false, reportUnusedFunction=false
from __future__ import annotations

from typing import Any, Callable, Mapping, TypeVar

from ._state import _attribute_registry

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
_MISSING: Any = MISSING


class Field:
    """Attribute default-value descriptor, created by field()."""

    __slots__ = ("default", "default_factory", "init")

    def __init__(
        self,
        default: Any = _MISSING,
        default_factory: Callable[[], Any] | None = None,
        init: bool = True,
    ) -> None:
        if default is not _MISSING and default_factory is not None:
            raise TypeError("cannot specify both default and default_factory")
        self.default = default
        self.default_factory = default_factory
        self.init = init


def field(
    *,
    default: Any = _MISSING,
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
        default: Any = _MISSING,
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
        return self.default is not _MISSING or self.default_factory is not None

    @property
    def has_storage(self) -> bool:
        return self._has_storage

    @property
    def getter(self) -> "_AttributeGetterPlaceholder":
        return _AttributeGetterPlaceholder(self)

    @property
    def setter(self) -> "_AttributeSetterPlaceholder":
        return _AttributeSetterPlaceholder(self)

    def get_default(self) -> Any:
        if self.default is not _MISSING:
            return self.default
        if self.default_factory is not None:
            return self.default_factory
        raise ValueError(f"Attribute '{self.name}' has no default")

    def make_default(self) -> Any:
        if self.default_factory is not None:
            return self.default_factory()
        if self.default is not _MISSING:
            return self.default
        raise ValueError(f"Attribute '{self.name}' has no default")

    def _storage_get(self, obj: Any) -> Any:
        # 字段值统一存放在 obj._mutobj_storage（dict），lazy 求值默认值：
        # - 已显式赋值：直接命中
        # - default_factory：首次访问求值并缓存（保证多次访问拿到同一对象）
        # - default（不可变）：每次返回 self.default，不写入 storage（节省内存）
        # - 无默认值：抛 AttributeError
        storage: dict[str, Any] = obj._mutobj_storage
        try:
            return storage[self.name]
        except KeyError:
            if self.default_factory is not None:
                value = self.default_factory()
                storage[self.name] = value
                return value
            if self.default is not _MISSING:
                return self.default
            raise AttributeError(
                f"'{type(obj).__name__}' object has no attribute '{self.name}'"
            ) from None

    def _storage_set(self, obj: Any, value: Any) -> None:
        obj._mutobj_storage[self.name] = value

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
            del obj._mutobj_storage[self.name]
        except KeyError as exc:
            raise AttributeError(
                f"'{type(obj).__name__}' object has no attribute '{self.name}'"
            ) from exc


class _AttributeGetterPlaceholder:
    def __init__(self, descriptor: AttributeDescriptor):
        self._descriptor = descriptor


class _AttributeSetterPlaceholder:
    def __init__(self, descriptor: AttributeDescriptor):
        self._descriptor = descriptor


_ordered_fields_cache: dict[type, list[str]] = {}


def _invalidate_ordered_fields_cache_for(cls: type) -> None:
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
        if klass in _attribute_registry:
            for attr_name in _attribute_registry[klass]:
                if attr_name not in seen:
                    seen.add(attr_name)
                    ordered.append(attr_name)

    if cls in _attribute_registry:
        for attr_name in _attribute_registry[cls]:
            if attr_name not in seen:
                seen.add(attr_name)
                ordered.append(attr_name)

    _ordered_fields_cache[cls] = ordered
    return ordered


def _get_attribute_descriptor(cls: type, attr_name: str) -> AttributeDescriptor | None:
    for klass in cls.__mro__:
        desc = klass.__dict__.get(attr_name)
        if isinstance(desc, AttributeDescriptor):
            return desc
    return None


def _get_init_fields(cls: type) -> list[str]:
    return [
        attr_name
        for attr_name in _get_ordered_fields(cls)
        if (desc := _get_attribute_descriptor(cls, attr_name)) is not None and desc.init
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
        desc = _get_attribute_descriptor(cls, name)
        if desc is not None:
            result[name] = desc
    return result
