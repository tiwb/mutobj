"""Pyright fixture for field reflection API: type pass-through.

mutobj.field_default(Cls.field) must infer the field's declared type
(via TypeVar pass-through), letting consumers drop `# pyright: ignore`
on `Cls.field.make_default()` style call sites.
"""
from __future__ import annotations

from typing import assert_type

import mutobj


class Action(mutobj.Declaration):
    categories: tuple[str, ...] = ()
    order: int | None = None
    label: str = "x"


def use_field_default() -> None:
    cats = mutobj.field_default(Action.categories)
    assert_type(cats, tuple[str, ...])

    order = mutobj.field_default(Action.order)
    assert_type(order, int | None)

    label = mutobj.field_default(Action.label)
    assert_type(label, str)

    # Reproduces the mutgui consumer pattern that previously needed `# pyright: ignore`.
    if "x" in mutobj.field_default(Action.categories):
        pass


def use_fields() -> None:
    descriptors = mutobj.fields(Action)
    info = descriptors["categories"]
    # info has class FieldInfo, returned as a Mapping value.
    info.make_default()


def use_field_info() -> None:
    info = mutobj.field_info(Action.categories)
    info.make_default()
    _ = info.has_default
