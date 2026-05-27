from __future__ import annotations

from typing import Any, Callable


class Property:
    """Property descriptor that supports declaration/implementation split."""

    def __init__(self, name: str, owner_cls: type):
        self.name = name
        self.owner_cls = owner_cls
        self._fget: Callable[..., Any] | None = None
        self._fset: Callable[..., Any] | None = None

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        if self._fget is None:
            raise NotImplementedError(
                f"Property '{self.name}' getter is not implemented. "
                f"Use @mutobj.impl({self.owner_cls.__name__}.{self.name}.getter) to provide implementation."
            )
        return self._fget(obj)

    def __set__(self, obj: Any, value: Any) -> None:
        if self._fset is None:
            raise AttributeError(
                f"Property '{self.name}' is read-only or setter is not implemented. "
                f"Use @mutobj.impl({self.owner_cls.__name__}.{self.name}.setter) to provide implementation."
            )
        self._fset(obj, value)

    @property
    def getter(self) -> "_PropertyGetterPlaceholder":
        return _PropertyGetterPlaceholder(self)

    @property
    def setter(self) -> "_PropertySetterPlaceholder":
        return _PropertySetterPlaceholder(self)


class _PropertyGetterPlaceholder:
    def __init__(self, prop: Property):
        self._prop = prop


class _PropertySetterPlaceholder:
    def __init__(self, prop: Property):
        self._prop = prop
