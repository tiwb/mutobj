"""Reverse fixture: type errors that pyright must catch on Declaration subclasses.
"""
from __future__ import annotations

import mutobj


class BadDefault(mutobj.Declaration):
    # pyright-expected: reportAssignmentType "Literal[123]"
    name: str = 123


class BadFieldAssign(mutobj.Declaration):
    count: int = 0
    label: str = "x"


# ── 类属性赋值 ──

def check_class_assign_wrong_type() -> None:
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "count"
    BadFieldAssign.count = "not_an_int"
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "label"
    BadFieldAssign.label = 999


def check_class_assign_nonexistent() -> None:
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "nonexistent"
    BadFieldAssign.nonexistent = 1
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "_app"
    BadFieldAssign._app = object()


# ── 实例属性赋值 ──

def check_instance_assign() -> None:
    obj = BadFieldAssign()
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "count"
    obj.count = "wrong"
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "label"
    obj.label = 999
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "nonexistent"
    obj.nonexistent = 1
