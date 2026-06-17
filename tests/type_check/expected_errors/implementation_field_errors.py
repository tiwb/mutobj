"""Reverse fixture: type errors that pyright must catch on Implementation subclasses.
"""
from __future__ import annotations

import mutobj


class Worker(mutobj.Declaration):
    task: str

    def run(self) -> str: ...


class BadDefault(mutobj.Implementation[Worker]):
    # pyright-expected: reportAssignmentType int
    retries: int = "not_an_int"


class BadFieldAssign(mutobj.Implementation[Worker]):
    timeout: float = 0.0
    label: str = "x"

    def run(self) -> str:
        return "ok"


# ── 类属性赋值 ──

def check_class_assign_wrong_type() -> None:
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "timeout"
    BadFieldAssign.timeout = "wrong"
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "label"
    BadFieldAssign.label = 999


def check_class_assign_nonexistent() -> None:
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "nonexistent"
    BadFieldAssign.nonexistent = 1
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "_cache"
    BadFieldAssign._cache = {}


# ── 实例属性赋值 ──

def check_instance_assign() -> None:
    impl = BadFieldAssign()
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "timeout"
    impl.timeout = "wrong"
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "label"
    impl.label = 999
    # pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "nonexistent"
    impl.nonexistent = 1
