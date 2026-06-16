"""R002：@impl 注册完整性 + 末尾 import 语句规范。

语义层（error）：每个声明桩方法在运行时必须注册了至少一个 @impl 实现。
格式层（warning）：声明文件末尾的 import 语句需遵循规范写法：
  - 必须有 ``from . import _xxx_impl as _xxx_impl  # noqa: F401, E402``
  - import 前保留恰好 2 个空行
  - 跳过 __init__.py，仅在对应的 _impl 文件存在时检查
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mutobj.core._declaration import Declaration, get_declaration_func
from mutobj.core._impls import impl_has_override

from ._helpers import R002, SEVERITY_ERROR, SEVERITY_WARNING, ClassSourceInfo, module_source_for_class

if TYPE_CHECKING:
    from mutobj.lint._api import LintMessage


def check_r002(
    infos: list[ClassSourceInfo],
    classes: list[type[Declaration]],
) -> list["LintMessage"]:
    from mutobj.lint._api import LintMessage

    results: list[LintMessage] = []

    # ── 语义：声明桩是否有 @impl ──
    for info in infos:
        for m in info.methods:
            if not m.is_stub:
                continue
            decl_func = _get_decl_func_with_property(info.cls, m.name)
            if decl_func is None or not impl_has_override(decl_func):
                results.append(LintMessage(
                    path=str(info.file_path),
                    line=m.line,
                    column=m.column,
                    rule_id=R002,
                    message=f"声明桩 {info.class_name}.{m.name} 没有注册任何 @impl 实现",
                    severity=SEVERITY_ERROR,
                    symbol=f"Declaration:{info.class_name}.{m.name}",
                ))

    # ── 格式：末尾 import 语句 ──
    seen_paths: set[Path] = set()
    for cls in classes:
        source = module_source_for_class(cls)
        if source is None:
            continue
        path, module_name = source
        if path in seen_paths or path.name == "__init__.py":
            continue
        seen_paths.add(path)

        impl_path = path.with_name(f"_{path.stem}_impl.py")
        if not impl_path.is_file():
            continue

        try:
            source_text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(source_text, filename=str(path))
        except SyntaxError:
            continue

        package_name = module_name.rsplit(".", 1)[0] if "." in module_name else module_name
        expected_module = f"{package_name}._{path.stem}_impl"
        results.extend(_check_format(path, tree, expected_module, package_name, source_text.splitlines()))

    return results


def _get_decl_func_with_property(cls: type, method_name: str) -> Any:
    """Like get_declaration_func, but also tries .getter / .setter keys for properties."""
    decl_func = get_declaration_func(cls, method_name)
    if decl_func is not None:
        return decl_func
    for suffix in (".getter", ".setter"):
        decl_func = get_declaration_func(cls, f"{method_name}{suffix}")
        if decl_func is not None:
            return decl_func
    return None


# ── format sub-checks ──────────────────────────────────────────────────────────

def _check_format(
    path: Path,
    tree: ast.Module,
    expected_module: str,
    decl_package: str,
    source_lines: list[str],
) -> list["LintMessage"]:
    if not tree.body:
        return []

    last_stmt = tree.body[-1]
    if not _is_import_of(last_stmt, expected_module, decl_package):
        return [_missing_import_msg(path, last_stmt, expected_module)]

    results: list["LintMessage"] = []
    results.extend(_check_noqa(path, last_stmt, source_lines))
    results.extend(_check_alias(path, last_stmt, expected_module, decl_package))
    results.extend(_check_spacing(path, tree))
    return results


def _missing_import_msg(path: Path, last_stmt: ast.stmt, expected_module: str) -> "LintMessage":
    from mutobj.lint._api import LintMessage

    return LintMessage(
        path=str(path),
        line=(last_stmt.end_lineno or last_stmt.lineno) + 1,
        column=0,
        rule_id=R002,
        message=f"文件末尾缺少 {expected_module!r} 的 import 注册语句",
        severity=SEVERITY_WARNING,
        symbol="format",
    )


def _check_spacing(path: Path, tree: ast.Module) -> list["LintMessage"]:
    from mutobj.lint._api import LintMessage

    if len(tree.body) < 2:
        return []

    last_stmt = tree.body[-1]
    prev_stmt = tree.body[-2]
    prev_end = prev_stmt.end_lineno or prev_stmt.lineno
    gap = last_stmt.lineno - prev_end
    if gap == 3:
        return []

    return [LintMessage(
        path=str(path),
        line=last_stmt.lineno,
        column=last_stmt.col_offset,
        rule_id=R002,
        message=f"末尾 import 前应保留 2 个空行，当前只有 {gap - 1} 个",
        severity=SEVERITY_WARNING,
        symbol="format",
    )]


def _is_import_of(stmt: ast.stmt, expected_module: str, decl_package: str) -> bool:
    if isinstance(stmt, ast.Import):
        return any(alias.name == expected_module for alias in stmt.names)

    if not isinstance(stmt, ast.ImportFrom):
        return False

    if stmt.module is None:
        return (
            stmt.level == 1
            and any(f"{decl_package}.{alias.name}" == expected_module for alias in stmt.names)
        )

    if stmt.level != 0:
        return False

    if stmt.module == expected_module:
        return True

    return any(f"{stmt.module}.{alias.name}" == expected_module for alias in stmt.names)


def _check_noqa(
    path: Path,
    stmt: ast.stmt,
    source_lines: list[str],
) -> list["LintMessage"]:
    from mutobj.lint._api import LintMessage

    line_index = stmt.lineno - 1
    if line_index >= len(source_lines):
        return []

    line = source_lines[line_index]
    match = re.search(r"#\s*noqa:\s*([A-Z0-9,\s]*)", line)
    if match is None:
        return [LintMessage(
            path=str(path),
            line=stmt.lineno,
            column=stmt.col_offset,
            rule_id=R002,
            message="末尾 import 行缺少 # noqa: F401, E402 注释",
            severity=SEVERITY_WARNING,
            symbol="format",
        )]

    codes = {c.strip() for c in match.group(1).split(",") if c.strip()}
    missing = [c for c in ("F401", "E402") if c not in codes]
    if not missing:
        return []

    return [LintMessage(
        path=str(path),
        line=stmt.lineno,
        column=stmt.col_offset,
        rule_id=R002,
        message=f"末尾 import 行的 noqa 注释缺少 {', '.join(missing)}",
        severity=SEVERITY_WARNING,
        symbol="format",
    )]


def _check_alias(
    path: Path,
    stmt: ast.stmt,
    expected_module: str,
    decl_package: str,
) -> list["LintMessage"]:
    from mutobj.lint._api import LintMessage

    if not isinstance(stmt, ast.ImportFrom):
        return []
    if stmt.module is not None or stmt.level != 1:
        return []

    for alias in stmt.names:
        if f"{decl_package}.{alias.name}" != expected_module:
            continue
        if alias.asname == alias.name:
            return []
        return [LintMessage(
            path=str(path),
            line=stmt.lineno,
            column=stmt.col_offset,
            rule_id=R002,
            message=(
                f"末尾 import 应写成 from . import {alias.name} as {alias.name}，"
                "以抑制 pyright reportUnusedImport"
            ),
            severity=SEVERITY_WARNING,
            symbol="format",
        )]
    return []
