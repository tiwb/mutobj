from __future__ import annotations

import weakref
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ._declaration import Declaration

impl_chain_registry: dict[tuple[type, str], list[tuple[Callable[..., Any], str, int]]] = {}
impl_seq: int = 0
module_first_seq: dict[tuple[type, str, str], int] = {}
impl_metas: dict[tuple[type, str, int], tuple[object, ...]] = {}

implementation_class_registry: dict[type[Declaration], type] = {}
implementation_instance_registry: weakref.WeakKeyDictionary[Declaration, object] = (
    weakref.WeakKeyDictionary()
)
implementation_owner_registry: dict[
    int,
    tuple[weakref.ReferenceType[Declaration], Any],
] = {}

attribute_registry: dict[type, dict[str, Any]] = {}
classvar_registry: dict[type, set[str]] = {}
class_registry: dict[tuple[str, str], type] = {}

registry_generation: int = 1


def next_impl_seq() -> int:
    global impl_seq
    impl_seq += 1
    return impl_seq


def bump_registry_generation() -> None:
    global registry_generation
    registry_generation += 1


def get_registry_generation() -> int:
    return registry_generation
