# pyright: reportPrivateUsage=false
from __future__ import annotations

import weakref
from typing import Any, Generic, Self, TypeVar

from ._declaration import Declaration
from ._fields import Field, _MISSING

T = TypeVar("T", bound=Declaration)

_extension_cache: weakref.WeakKeyDictionary[Declaration, dict[type, Any]] = weakref.WeakKeyDictionary()
_extension_registry: dict[type, list[type["Extension[Any]"]]] = {}


class Extension(Generic[T]):
    _target_class: type | None = None
    target: Declaration | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for base in cls.__dict__.get("__orig_bases__", ()):
            origin = getattr(base, "__origin__", None)
            if origin is not None and issubclass(origin, Extension):
                args = getattr(base, "__args__", None)
                if args:
                    cls._target_class = args[0]
                    _extension_registry.setdefault(args[0], []).append(cls)
                return

    @classmethod
    def get_or_create(cls, instance: T) -> Self:
        if instance not in _extension_cache:
            _extension_cache[instance] = {}

        cache = _extension_cache[instance]
        if cls not in cache:
            ext = cls.__new__(cls)
            ext.target = instance
            processed: set[str] = set()
            for klass in cls.__mro__:
                for attr_name in getattr(klass, "__annotations__", {}):
                    if attr_name in processed:
                        continue
                    processed.add(attr_name)
                    attr_value = getattr(klass, attr_name, _MISSING)
                    if isinstance(attr_value, Field):
                        if attr_value.default_factory is not None:
                            setattr(ext, attr_name, attr_value.default_factory())
                        elif attr_value.default is not _MISSING:
                            setattr(ext, attr_name, attr_value.default)
            ext.__init__()
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
