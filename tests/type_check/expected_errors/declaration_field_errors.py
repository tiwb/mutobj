"""Reverse fixture: type errors that pyright must catch on Declaration subclasses.
"""
from __future__ import annotations

import mutobj


class BadDefault(mutobj.Declaration):
    # pyright-expected: reportAssignmentType "Literal[123]"
    name: str = 123


class BadFieldAssign(mutobj.Declaration):
    count: int = 0


# pyright-expected: reportAttributeAccessIssue Cannot assign to attribute "count"
BadFieldAssign.count = "not_an_int"
