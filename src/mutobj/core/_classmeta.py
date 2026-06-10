from dataclasses import dataclass, field
from typing import Any, Callable


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

    fields: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(slots=True)
class ExtensionClassMeta(MutobjClassMeta):
    """Per-class metadata for Extension subclasses."""

    target_class: type[Any] | None = None


@dataclass(slots=True)
class ImplementationClassMeta(MutobjClassMeta):
    """Per-class metadata for Implementation subclasses."""

    target_class: type[Any] | None = None


@dataclass(slots=True)
class DeclarationClassMeta(MutobjClassMeta):
    """Per-class metadata for Declaration subclasses."""

    classvars: set[str] = field(default_factory=set[str])
    methods: set[str] = field(default_factory=set[str])
    classmethods: set[str] = field(default_factory=set[str])
    staticmethods: set[str] = field(default_factory=set[str])
    impl_chains: dict[str, list[ImplChainEntry]] = field(default_factory=dict[str, list[ImplChainEntry]])
    impl_class: type[Any] | None = None
    extensions: list[type[Any]] = field(default_factory=list[type[Any]])
