"""
mutobj.lint 公开 API 实现
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from mutobj.lint._resolver import DeclarationResolver
from mutobj.lint._rules import check_r001

# 默认排除的目录名（任意层级匹配目录名即跳过）
_DEFAULT_EXCLUDES: frozenset[str] = frozenset({
    "__pycache__", ".git", ".venv", "venv", "build", "dist", "node_modules",
})


@dataclass(frozen=True, order=True)
class LintMessage:
    """单条 lint 报告"""
    # 排序优先级：path -> line -> column -> rule_id
    path: str
    line: int
    column: int
    rule_id: str
    message: str
    severity: str  # "error" | "warning"


def lint_file(path: str | Path) -> list[LintMessage]:
    """对单个 .py 文件执行 lint。

    无法 parse / 文件不存在 / 不是 .py 文件时返回空列表（保守不报警）。
    """
    p = Path(path)
    resolver = DeclarationResolver()
    return _lint_one(p, resolver)


def lint_directory(
    path: str | Path,
    *,
    exclude: Iterable[str] | None = None,
) -> list[LintMessage]:
    """递归扫描目录下所有 .py 文件。

    Args:
        path: 目录路径
        exclude: 追加排除的目录名（在默认基础上累加）

    Returns:
        所有违规报告，按 (path, line, column) 排序
    """
    root = Path(path)
    excludes: set[str] = set(_DEFAULT_EXCLUDES)
    if exclude:
        excludes.update(exclude)

    files = list(_iter_py_files(root, excludes))
    resolver = DeclarationResolver()

    results: list[LintMessage] = []
    for f in files:
        results.extend(_lint_one(f, resolver))
    results.sort()
    return results


def _lint_one(path: Path, resolver: DeclarationResolver) -> list[LintMessage]:
    """对单文件执行所有规则。失败时静默返回空。"""
    if not path.is_file() or path.suffix != ".py":
        return []
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    file_info = resolver.analyze_file(path, tree=tree)
    return check_r001(path, tree, file_info, resolver)


def _iter_py_files(root: Path, excludes: set[str]) -> Iterable[Path]:
    """递归收集 .py 文件，跳过排除目录。

    单文件路径直接返回该文件。
    """
    if root.is_file():
        if root.suffix == ".py":
            yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        # 原地修改 dirnames 以剪枝（os.walk 约定）
        dirnames[:] = [d for d in dirnames if d not in excludes]
        for fn in filenames:
            if fn.endswith(".py"):
                yield Path(dirpath) / fn


__all__ = ["LintMessage", "lint_file", "lint_directory"]
