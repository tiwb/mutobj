from __future__ import annotations

import importlib
from typing import TypeVar

T = TypeVar("T")

# ── 类注册表 ──────────────────────────────────────────────

class_registry: dict[tuple[str, str], type] = {}

registry_generation: int = 1


def bump_registry_generation() -> None:
    global registry_generation
    registry_generation += 1


def get_registry_generation() -> int:
    return registry_generation


# ── 注册表查询 ────────────────────────────────────────────

def discover_subclasses(base_cls: type[T]) -> list[type[T]]:
    return [
        cls
        for cls in class_registry.values()
        if cls is not base_cls and isinstance(cls, type) and issubclass(cls, base_cls)  # pyright: ignore[reportUnnecessaryIsInstance]
    ]


def resolve_class(class_path: str, base_cls: type[T]) -> type[T]:
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
