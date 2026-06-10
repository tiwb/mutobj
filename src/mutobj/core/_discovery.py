from __future__ import annotations

import importlib
from typing import Any, Callable, TypeVar

from ._declaration import Declaration
from ._state import class_registry, impl_chain_registry, get_registry_generation as _get_registry_generation

T = TypeVar("T")


def discover_subclasses(base_cls: type[T]) -> list[type[T]]:
    return [
        cls
        for cls in class_registry.values()
        if cls is not base_cls and isinstance(cls, type) and issubclass(cls, base_cls)  # pyright: ignore[reportUnnecessaryIsInstance]
    ]


def resolve_class(class_path: str, base_cls: type[T] = Declaration) -> type[T]:
    for (module_name, qualname), cls in class_registry.items():
        if class_path in (qualname, cls.__name__, f"{module_name}.{qualname}"):
            if not issubclass(cls, base_cls):
                raise ValueError(
                    f"Class {class_path} is not a subclass of {base_cls.__name__}"
                )
            return cls

    if "." in class_path:
        module_path, class_name = class_path.rsplit(".", 1)
        try:
            importlib.import_module(module_path)
        except ImportError as exc:
            raise ValueError(f"Cannot import module for {class_path}: {exc}") from exc

        key = (module_path, class_name)
        if key in class_registry:
            cls = class_registry[key]
            if not issubclass(cls, base_cls):
                raise ValueError(
                    f"Class {class_path} is not a subclass of {base_cls.__name__}"
                )
            return cls

    raise ValueError(f"Cannot resolve class: {class_path}")


def get_declaration_func(cls: type, method_name: str) -> Callable[..., Any] | None:
    for klass in cls.__mro__:
        chain = impl_chain_registry.get((klass, method_name))
        if not chain:
            continue
        for func, source_module, _seq in chain:
            if source_module == "__default__":
                return func
    return None


def get_declaration_doc(cls: type, method_name: str) -> str | None:
    func = get_declaration_func(cls, method_name)
    if func is not None:
        return getattr(func, "__doc__", None)
    return None


def get_registry_generation() -> int:
    return _get_registry_generation()
