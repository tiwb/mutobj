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

    def __init__(
        self,
        name: str,
        annotation: Any,
        default: Any = _MISSING,
        default_factory: Callable[[], Any] | None = None,
        init: bool = True,
    ):
        self.name = name
        self.annotation = annotation
        self.storage_name = f"_mutobj_attr_{name}"
        self.default = default
        self.default_factory = default_factory
        self.init = init

    @property
    def has_default(self) -> bool:
        return self.default is not _MISSING or self.default_factory is not None

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

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        try:
            return getattr(obj, self.storage_name)
        except AttributeError as exc:
            raise AttributeError(
                f"'{type(obj).__name__}' object has no attribute '{self.name}'"
            ) from exc

    def __set__(self, obj: Any, value: Any) -> None:
        setattr(obj, self.storage_name, value)

    def __delete__(self, obj: Any) -> None:
        try:
            delattr(obj, self.storage_name)
        except AttributeError as exc:
            raise AttributeError(
                f"'{type(obj).__name__}' object has no attribute '{self.name}'"
            ) from exc


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
