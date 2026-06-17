"""Reverse fixture: type errors that pyright must catch on Extension subclasses.
"""
from __future__ import annotations

import mutobj


class Host(mutobj.Declaration):
    name: str = ""


class BadDefault(mutobj.Extension[Host]):
    # pyright-expected: reportAssignmentType int
    count: int = "not_an_int"


class BadFieldAssign(mutobj.Extension[Host]):
    size: int = 0
    label: str = "x"


# ── 类属性赋值 ──

def check_class_assign_wrong_type() -> None:
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "size"
    BadFieldAssign.size = "wrong"
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "label"
    BadFieldAssign.label = 999


def check_class_assign_nonexistent() -> None:
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "nonexistent"
    BadFieldAssign.nonexistent = 1
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "_secret"
    BadFieldAssign._secret = object()


# ── 实例属性赋值 ──

def check_instance_assign() -> None:
    host = Host()
    ext = BadFieldAssign.get_or_create(host)
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "size"
    ext.size = "wrong"
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "label"
    ext.label = 999
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "nonexistent"
    ext.nonexistent = 1
