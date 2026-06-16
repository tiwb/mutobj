from __future__ import annotations

import fnmatch
import importlib
import pkgutil
from dataclasses import dataclass, field
from types import ModuleType
from typing import Sequence

from pathlib import Path

from mutobj.core._declaration import Declaration

from ._helpers import ClassSourceInfo, class_source_info
from ._r001 import check_r001
from ._r002 import check_r002
from ._r003 import check_r003
from ._r004 import check_r004


@dataclass(frozen=True, slots=True)
class AsyncAllowed:
    """Allow async/sync differences for a specific @impl in R004."""


@dataclass(frozen=True, slots=True)
class SignatureOverride:
    """Suppress R004 for a specific @impl."""

    reason: str = ""


def _relpath(path: str) -> str:
    try:
        return str(Path(path).relative_to(Path.cwd()))
    except ValueError:
        return path


@dataclass(frozen=True, order=True, slots=True)
class LintMessage:
    path: str
    line: int
    column: int
    rule_id: str
    message: str
    severity: str
    symbol: str | None = field(default=None, compare=False)

    def __str__(self) -> str:
        path = _relpath(self.path)
        location = f"{path}:{self.line}"
        if self.symbol:
            return f"{self.rule_id} {location} [{self.symbol}] {self.message}"
        return f"{self.rule_id} {location} {self.message}"

    def __repr__(self) -> str:
        return str(self)


@dataclass(frozen=True, slots=True)
class LintResults:
    """Container for LintMessage list with readable formatting helpers."""

    messages: list[LintMessage] = field(default_factory=list[LintMessage])

    def format(self) -> str:
        """Return summary line + one LintMessage per line, for pytest.fail()."""
        errors = sum(1 for m in self.messages if m.severity == "error")
        warnings = sum(1 for m in self.messages if m.severity == "warning")
        lines = [f"{errors} errors, {warnings} warnings"]
        lines.extend(str(m) for m in self.messages)
        return "\n".join(lines)

    def __repr__(self) -> str:
        return self.format()

    def __bool__(self) -> bool:
        return bool(self.messages)


def check(
    patterns: Sequence[str],
    *,
    exclude: Sequence[str] | None = None,
) -> LintResults:
    """Run mutobj lint checks against already-importable modules.

    `check()` imports the requested modules directly and then runs runtime rules
    against the resulting `Declaration` subclasses. It does not sandbox import
    side effects or clean `sys.modules`; callers should treat import side
    effects as part of the checked modules' normal pytest runtime.
    """
    if not patterns:
        return LintResults()

    exclude_patterns = tuple(exclude or ())
    modules = _load_modules(patterns, exclude_patterns)
    classes = _collect_declaration_classes(modules)

    infos = [info for cls in classes if (info := class_source_info(cls)) is not None]
    file_groups: dict[Path, list[ClassSourceInfo]] = {}
    for info in infos:
        file_groups.setdefault(info.file_path, []).append(info)

    messages: list[LintMessage] = []
    messages.extend(check_r001(infos, file_groups))
    messages.extend(check_r002(infos, classes))
    messages.extend(check_r003(infos))
    messages.extend(check_r004(infos))
    messages.sort()
    return LintResults(messages=messages)


def _load_modules(
    patterns: Sequence[str],
    exclude_patterns: tuple[str, ...],
) -> list[ModuleType]:
    modules: list[ModuleType] = []
    seen: set[str] = set()
    for pattern in patterns:
        for module_name in _expand_pattern(pattern):
            if module_name in seen:
                continue
            if _is_excluded(module_name, exclude_patterns):
                continue
            modules.append(importlib.import_module(module_name))
            seen.add(module_name)
    return modules


def _expand_pattern(pattern: str) -> list[str]:
    if not pattern.endswith(".*"):
        return [pattern]

    package_name = pattern[:-2]
    package = importlib.import_module(package_name)
    module_names = [package_name]
    package_paths = getattr(package, "__path__", None)
    if package_paths is None:
        return module_names

    prefix = f"{package_name}."
    for module_info in pkgutil.walk_packages(package_paths, prefix):
        module_names.append(module_info.name)
    return module_names


def _is_excluded(module_name: str, exclude_patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(module_name, pattern) for pattern in exclude_patterns)


def _collect_declaration_classes(modules: Sequence[ModuleType]) -> list[type[Declaration]]:
    classes: list[type[Declaration]] = []
    seen: set[type[Declaration]] = set()
    for module in modules:
        for value in vars(module).values():
            if not isinstance(value, type):
                continue
            if value is Declaration or not issubclass(value, Declaration):
                continue
            if value.__module__ != module.__name__:
                continue
            if value in seen:
                continue
            classes.append(value)
            seen.add(value)
    return classes


__all__ = [
    "AsyncAllowed",
    "SignatureOverride",
    "LintMessage",
    "LintResults",
    "check",
]
