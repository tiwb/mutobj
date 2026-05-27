from __future__ import annotations

from typing import Any, Callable

_impl_chain: dict[tuple[type, str], list[tuple[Callable[..., Any], str, int]]] = {}
_impl_seq: int = 0
_module_first_seq: dict[tuple[type, str, str], int] = {}
_impl_metas: dict[tuple[type, str, int], tuple[object, ...]] = {}

_attribute_registry: dict[type, dict[str, Any]] = {}
_classvar_registry: dict[type, set[str]] = {}
_property_registry: dict[type, dict[str, Any]] = {}
_class_registry: dict[tuple[str, str], type] = {}

_registry_generation: int = 0


def next_impl_seq() -> int:
    global _impl_seq
    _impl_seq += 1
    return _impl_seq


def bump_registry_generation() -> None:
    global _registry_generation
    _registry_generation += 1


def get_registry_generation() -> int:
    return _registry_generation
