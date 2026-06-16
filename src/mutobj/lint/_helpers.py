"""Lint helpers: shared constants, dataclasses, and utility functions."""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from mutobj.core._classmeta import decl_meta_cache
from mutobj.core._declaration import Declaration
from mutobj.core._fields import AttributeDescriptor


# ── rule IDs ──────────────────────────────────────────────────────────────────

R001 = "R001"
R002 = "R002"
R003 = "R003"
R004 = "R004"
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
_EMPTY = inspect.Signature.empty


# ── source info dataclasses ────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class MethodSourceInfo:
    name: str
    line: int
    column: int
    is_stub: bool


@dataclass(frozen=True, slots=True)
class ClassSourceInfo:
    cls: type[Declaration]
    file_path: Path
    module_name: str
    class_name: str
    class_line: int
    class_column: int
    methods: tuple[MethodSourceInfo, ...]


# ── class introspection ────────────────────────────────────────────────────────

def class_source_info(cls: type[Declaration]) -> ClassSourceInfo | None:
    try:
        source_lines, start_line = inspect.getsourcelines(cls)
    except (OSError, TypeError):
        return None

    source_path = inspect.getsourcefile(cls)
    if source_path is None:
        return None

    source = textwrap.dedent("".join(source_lines))
    try:
        tree = ast.parse(source, filename=source_path)
    except SyntaxError:
        return None

    class_node = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == cls.__name__
        ),
        None,
    )
    if class_node is None:
        return None

    methods: list[MethodSourceInfo] = []
    for node in class_node.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _is_overload(node):
            continue
        methods.append(MethodSourceInfo(
            name=node.name,
            line=start_line + node.lineno - 1,
            column=node.col_offset,
            is_stub=_is_stub_body(node),
        ))

    return ClassSourceInfo(
        cls=cls,
        file_path=Path(source_path),
        module_name=cls.__module__,
        class_name=cls.__name__,
        class_line=start_line + class_node.lineno - 1,
        class_column=class_node.col_offset,
        methods=tuple(methods),
    )


def class_category(info: ClassSourceInfo) -> str:
    stub_methods = [m for m in info.methods if m.is_stub]
    impl_methods = [m for m in info.methods if not m.is_stub]
    if stub_methods and impl_methods:
        return "mixed"
    if stub_methods:
        return "declaration"
    if impl_methods:
        return "implementation"
    return "behaviorless"


# ── AST helpers ────────────────────────────────────────────────────────────────

def _is_stub_body(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = func.body
    if not body:
        return False

    start = 0
    if (
        isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        start = 1
    rest = body[start:]
    if len(rest) != 1:
        return False

    stmt = rest[0]
    if not isinstance(stmt, ast.Expr):
        return False
    if isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis:
        return True
    if isinstance(stmt.value, ast.Yield):
        value = stmt.value.value
        return isinstance(value, ast.Constant) and value.value is Ellipsis
    return False


def _is_overload(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in func.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "overload":
            return True
        if (
            isinstance(decorator, ast.Attribute)
            and decorator.attr == "overload"
            and isinstance(decorator.value, ast.Name)
            and decorator.value.id == "typing"
        ):
            return True
    return False


# ── impl chain helpers ─────────────────────────────────────────────────────────

def iter_own_impl_entries(info: ClassSourceInfo) -> Iterable[tuple[str, Any]]:
    own_method_names = {m.name for m in info.methods}
    own_descriptor_names = {
        name
        for name, value in info.cls.__dict__.items()
        if isinstance(value, AttributeDescriptor)
    }
    chains = decl_meta_cache[info.cls].impl_chains
    for key, chain in chains.items():
        if key.endswith(".getter") or key.endswith(".setter"):
            base_name = key.split(".", 1)[0]
            if base_name not in own_descriptor_names:
                continue
        elif key not in own_method_names:
            continue
        for entry in chain:
            if entry.source_module == "__default__":
                continue
            yield key, entry


# ── naming / source helpers ────────────────────────────────────────────────────

def normalize_member_name(key: str) -> str:
    if key == "__init__":
        return "init"
    if key.endswith(".getter") or key.endswith(".setter"):
        return key.split(".", 1)[0]
    return key


def camel_to_snake(name: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name).lower()


def function_definition_line(func: Any) -> tuple[Path | None, int, str]:
    try:
        source_lines, start_line = inspect.getsourcelines(func)
    except (OSError, TypeError):
        return None, 0, ""

    source_path = inspect.getsourcefile(func)
    path = Path(source_path) if source_path is not None else None
    for index, source_line in enumerate(source_lines):
        if re.match(r"\s*(async\s+def|def)\s+", source_line):
            return path, start_line + index, source_line.rstrip()
    return path, start_line, source_lines[0].rstrip() if source_lines else ""


def module_source_for_class(cls: type[Declaration]) -> tuple[Path, str] | None:
    source_path = inspect.getsourcefile(cls)
    if source_path is None:
        return None
    return Path(source_path), cls.__module__
