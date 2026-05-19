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
from mutobj.lint._rules import check_r001, check_r002

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
    p = Path(path).resolve()
    resolver = DeclarationResolver()
    impl_pairs = _scan_impl_pairs_for_file(p)
    return _lint_one(p, resolver, impl_pairs=impl_pairs)


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
    impl_pairs = _scan_impl_pairs(files)

    results: list[LintMessage] = []
    for f in files:
        results.extend(_lint_one(f, resolver, impl_pairs=impl_pairs))
    results.sort()
    return results


def _lint_one(
    path: Path,
    resolver: DeclarationResolver,
    impl_pairs: dict[Path, tuple[str, str]] | None = None,
) -> list[LintMessage]:
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
    messages = check_r001(path, tree, file_info, resolver, impl_pairs=impl_pairs)
    messages.extend(check_r002(path, tree, impl_pairs, source_lines=source.splitlines()))
    return messages


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


# ============================================================ 预扫描 impl 配对


def _scan_impl_pairs(files: list[Path]) -> dict[Path, tuple[str, str]]:
    """扫描文件列表，找出 decl-impl 配对。

    对每个包目录（含 __init__.py），找到 ``_{stem}_impl.py`` 与 ``{stem}.py``
    的配对关系，返回 ``{decl_path: (impl_full_module_name, decl_package)}``。
    """
    # 按目录分组
    by_dir: dict[Path, list[str]] = {}
    for f in files:
        by_dir.setdefault(f.parent, []).append(f.name)

    pairs: dict[Path, tuple[str, str]] = {}

    for dirpath, filenames in by_dir.items():
        if "__init__.py" not in filenames:
            continue
        # 计算目录的包名
        try:
            pkg_name = _resolve_package_name(dirpath)
        except ValueError:
            continue
        if pkg_name is None:
            continue

        for fn in filenames:
            if fn.startswith("_") and fn.endswith("_impl.py"):
                stem = fn[1:-8]  # _xxx_impl.py → xxx
                if not stem:
                    continue
                impl_module = fn[:-3]  # _xxx_impl
                decl_fn = f"{stem}.py"
                if decl_fn in filenames:
                    decl_path = (dirpath / decl_fn).resolve()
                    pairs[decl_path] = (f"{pkg_name}.{impl_module}", pkg_name)

    return pairs


def _scan_impl_pairs_for_file(file_path: Path) -> dict[Path, tuple[str, str]] | None:
    """为单个文件扫描配对（用于 lint_file）。"""
    dirpath = file_path.parent
    if not (dirpath / "__init__.py").is_file():
        return None

    stem = file_path.stem
    try:
        pkg_name = _resolve_package_name(dirpath)
    except ValueError:
        return None
    if pkg_name is None:
        return None

    impl_fn = f"_{stem}_impl.py"
    if (dirpath / impl_fn).is_file():
        return {file_path: (f"{pkg_name}._{stem}_impl", pkg_name)}

    return None


def _resolve_package_name(dirpath: Path) -> str | None:
    """从目录路径反推包点分名。

    沿着 __init__.py 链向上回溯，拼接包名。
    """
    parts: list[str] = []
    d = dirpath.resolve()
    while d != d.parent and (d / "__init__.py").is_file():
        parts.append(d.name)
        d = d.parent
    if not parts:
        return None
    parts.reverse()
    return ".".join(parts)


__all__ = ["LintMessage", "lint_file", "lint_directory"]
