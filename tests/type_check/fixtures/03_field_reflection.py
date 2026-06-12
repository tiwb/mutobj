"""Pyright fixture for field reflection API.

``Cls.field`` returns a ``FieldInfo`` at runtime, but pyright sees the
annotation type (e.g. ``tuple[str, ...]``).  Two pyright-clean ways to
access ``FieldInfo`` methods:

    # 1. field_info — TypeVar 透传，返回 FieldInfo[_F]，保留字段值类型
    info = mutobj.field_info(Action.categories)
    cats = info.make_default()  # pyright 推断为 tuple[str, ...]

    # 2. fields — 动态字段名遍历（返回 FieldInfo[Any]）
    info = mutobj.fields(Action)["categories"]
    cats = info.make_default()  # pyright 推断为 Any
"""
from __future__ import annotations

import mutobj


class Action(mutobj.Declaration):
    categories: tuple[str, ...] = ()
    order: int | None = None
    label: str = "x"


def use_make_default_via_fields() -> None:
    """fields(cls)[name].make_default() — pyright-clean way to get a default."""
    cats: tuple[str, ...] = mutobj.fields(Action)["categories"].make_default()
    order: int | None = mutobj.fields(Action)["order"].make_default()
    label: str = mutobj.fields(Action)["label"].make_default()

    # Consumer pattern from mutgui
    if "x" in mutobj.fields(Action)["categories"].make_default():
        pass

    assert cats == ()
    assert order is None
    assert label == "x"


def use_cls_field_via_fields() -> None:
    """fields(cls) returns FieldInfo objects with full metadata."""
    descriptors = mutobj.fields(Action)
    info = descriptors["categories"]
    # info is FieldInfo[Any] (dynamic key), make_default / has_default are available
    info.make_default()
    _ = info.has_default


def use_field_info() -> None:
    """field_info(Cls.field) — TypeVar 透传，保留字段值类型。"""
    info = mutobj.field_info(Action.categories)
    # info is FieldInfo[tuple[str, ...]]
    cats: tuple[str, ...] = info.make_default()
    assert cats == ()
    _ = info.has_default

    # Consumer pattern from mutgui
    if "x" in mutobj.field_info(Action.categories).make_default():
        pass


def use_field_info_order() -> None:
    info = mutobj.field_info(Action.order)
    # info is FieldInfo[int | None]
    order: int | None = info.make_default()
    assert order is None
