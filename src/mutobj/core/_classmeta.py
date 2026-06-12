from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ._declaration import Declaration
    from ._extensions import Extension
    from ._fields import AttributeDescriptor
    from ._implementation import Implementation


@dataclass(slots=True)
class ImplChainEntry:
    """A single entry in a Declaration's impl chain."""

    func: Callable[..., Any]
    source_module: str
    seq: int
    metas: tuple[object, ...] = ()


@dataclass(slots=True)
class MutobjClassMeta:
    """Base per-class metadata shared by Declaration / Extension / Implementation."""

    fields: dict[str, AttributeDescriptor] = field(default_factory=dict[str, Any])
    classvars: set[str] = field(default_factory=set[str])
    ordered_descriptors: dict[str, AttributeDescriptor] | None = None


@dataclass(slots=True)
class ExtensionClassMeta(MutobjClassMeta):
    """Per-class metadata for Extension subclasses."""

    extension_base: type[Declaration] | None = None


@dataclass(slots=True)
class ImplementationClassMeta(MutobjClassMeta):
    """Per-class metadata for Implementation subclasses."""

    target_class: type[Declaration] | None = None


@dataclass(slots=True)
class DeclarationClassMeta(MutobjClassMeta):
    """Per-class metadata for Declaration subclasses."""

    methods: set[str] = field(default_factory=set[str])
    classmethods: set[str] = field(default_factory=set[str])
    staticmethods: set[str] = field(default_factory=set[str])
    impl_chains: dict[str, list[ImplChainEntry]] = field(default_factory=dict[str, list[ImplChainEntry]])
    impl_class: type[Implementation[Any]] | None = None
    extensions: list[type[Extension[Any]]] = field(default_factory=list[Any])


# ---------------------------------------------------------------------------
# 全局 per-class 元数据注册表
# 按 meta 类型分四个 dict：前三个强类型，mutobj_meta_cache 冗余存储供 MRO 遍历统一查询。
# ---------------------------------------------------------------------------

decl_meta_cache: dict[type, DeclarationClassMeta] = {}
ext_meta_cache: dict[type, ExtensionClassMeta] = {}
impl_meta_cache: dict[type, ImplementationClassMeta] = {}
mutobj_meta_cache: dict[type, MutobjClassMeta] = {}
