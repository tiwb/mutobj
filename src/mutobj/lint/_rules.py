"""
R001 规则实现：声明 / 实现风格混合检测

判定规则：
- 桩方法：body == [Expr(Constant(str))?, Expr(Constant(Ellipsis))]（可选 docstring + `...`）
- 实现方法：body 不匹配上述模式（含 `pass`、`raise NotImplementedError`、有真实语句）
- @overload 装饰的方法：从判定中剔除（typing 标准用法）
- `__init__` 方法：**不豁免**，与普通方法一视同仁参与桩/实现判定。
  decl 文件中 `__init__` 必须是桩或完全省略；写出含实际语句
  （`super().__init__()` / `pass` / 字段赋值等）的 `__init__` 即视为实现，
  落入类级 / 文件级一致性判定。
- 装饰器（property/classmethod/staticmethod/abstractmethod）不影响判定
- 嵌套类（非 Declaration 子类）不参与判定
- 零方法类 → 无行为类（不参与文件级混合判定）

类级混合：单个 Declaration 子类内同时存在桩方法和实现方法 → R001
文件级混合：文件内同时存在声明类和实现类（无行为类不参与）→ R001
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mutobj.lint._api import LintMessage  # 避免循环 import
    from mutobj.lint._resolver import DeclarationResolver, FileAnalysis


R001 = "R001"
R002 = "R002"
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


def check_r001(
    path: Path,
    tree: ast.AST,
    file_info: "FileAnalysis",
    resolver: "DeclarationResolver",  # noqa: ARG001 — 预留扩展
    impl_pairs: dict[Path, tuple[str, str]] | None = None,
) -> list["LintMessage"]:
    """对单文件执行 R001 检测。

    若 impl_pairs 非空且 path 在其中，说明该文件是 decl-impl 配对的声明侧，
    则额外要求所有 Declaration 子类必须是纯声明类（全 ... 桩）。
    """
    from mutobj.lint._api import LintMessage  # 延迟 import 打破循环

    messages: list[LintMessage] = []
    if not isinstance(tree, ast.Module):
        return messages

    decl_classes = file_info.declaration_classes
    if not decl_classes:
        return messages

    # 文件级聚合：只有“有行为”的类参与投票
    file_has_declaration_class = False
    file_has_implementation_class = False
    # (name, node, category)，category ∈ {"declaration", "implementation", "behaviorless", "mixed"}
    file_class_categories: list[tuple[str, ast.ClassDef, str]] = []

    for name, cls in file_info.classes.items():
        if name not in decl_classes:
            continue
        category, class_messages = _classify_class(path, cls)
        messages.extend(class_messages)
        file_class_categories.append((name, cls, category))
        if category == "declaration":
            file_has_declaration_class = True
        elif category == "implementation":
            file_has_implementation_class = True

    # 文件级混合：仅报告有行为的类（无行为类不参与、也不被报告）
    if file_has_declaration_class and file_has_implementation_class:
        for name, cls, category in file_class_categories:
            if category not in ("declaration", "implementation"):
                continue
            messages.append(LintMessage(
                path=str(path),
                line=cls.lineno,
                column=cls.col_offset,
                rule_id=R001,
                message=(
                    f"文件级风格混合：Declaration 子类 {name!r} 是 "
                    f"{_label(category)}；同文件内同时存在声明类和实现类，"
                    "一个文件应当全是声明或全是实现"
                ),
                severity=SEVERITY_ERROR,
            ))

    # decl-impl 配对约束：声明侧文件中的所有 Declaration 子类必须是纯声明类
    if impl_pairs is not None and path in impl_pairs:
        for name, cls, category in file_class_categories:
            if category in ("declaration", "behaviorless"):
                continue
            messages.append(LintMessage(
                path=str(path),
                line=cls.lineno,
                column=cls.col_offset,
                rule_id=R001,
                message=(
                    f"Declaration 子类 {name!r} 包含实现方法（非 ... 桩）；"
                    "同目录存在对应 _impl 文件，声明文件中的方法应全为 ... 桩，"
                    "实现应写在 _impl 文件中"
                ),
                severity=SEVERITY_ERROR,
            ))

    return messages


def _classify_class(
    path: Path, cls: ast.ClassDef,
) -> tuple[str, list["LintMessage"]]:
    """对单个 Declaration 子类分类。

    返回 (category, messages)，category ∈：
        - "declaration"      只有桩方法
        - "implementation"   只有实现方法
        - "behaviorless"     零方法（不参与文件级投票）
        - "mixed"            类级风格混合（messages 包含错误）

    计不在内：@overload 方法。

    注意：`__init__` 不豁免，与普通方法走同一套桩/实现判定。
    """
    from mutobj.lint._api import LintMessage

    stub_methods: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    impl_methods: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    for node in cls.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _is_overload(node):
            continue  # typing.overload 桩不参与判定
        if _is_stub_body(node):
            stub_methods.append(node)
        else:
            impl_methods.append(node)

    messages: list[LintMessage] = []

    if stub_methods and impl_methods:
        # 类级混合：报告所有非桩方法
        for m in impl_methods:
            messages.append(LintMessage(
                path=str(path),
                line=m.lineno,
                column=m.col_offset,
                rule_id=R001,
                message=(
                    f"类级风格混合：Declaration 子类 {cls.name!r} 内方法 "
                    f"{m.name!r} 不是 `...` 桩；声明类中所有方法应当全部是 "
                    "`...` 桩（实现写在 `@impl` 装饰的实现侧）"
                ),
                severity=SEVERITY_ERROR,
            ))
        return "mixed", messages

    if stub_methods:
        return "declaration", messages
    if impl_methods:
        return "implementation", messages
    # 零方法：无行为类，不参与文件级投票
    return "behaviorless", messages


def _is_stub_body(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """判定函数体是否为 `[docstring?, ...]` 形态的桩"""
    body = func.body
    if not body:
        return False
    # 剔除前导 docstring
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
    if not isinstance(stmt.value, ast.Constant):
        return False
    # `...` 的 Constant.value 是 Ellipsis
    return stmt.value.value is Ellipsis


def _is_overload(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """是否被 @overload / @typing.overload 装饰"""
    for dec in func.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "overload":
            return True
        if (
            isinstance(dec, ast.Attribute)
            and dec.attr == "overload"
            and isinstance(dec.value, ast.Name)
            and dec.value.id == "typing"
        ):
            return True
    return False


def _label(category: str) -> str:
    return {"declaration": "声明类", "implementation": "实现类"}.get(category, category)


# ============================================================ R002


def check_r002(
    path: Path,
    tree: ast.AST,
    impl_pairs: dict[Path, tuple[str, str]] | None,
    source_lines: list[str] | None = None,
) -> list["LintMessage"]:
    """检查声明文件是否在末尾 import 了对应的 _impl 模块。

    impl_pairs: {decl_path: (impl_full_module_name, decl_package)}，如
        {Path(".../view.py"): ("mutio.mcp._view_impl", "mutio.mcp")}
    source_lines: 源码行列表，用于检查 import 行的 noqa 注释
    """
    if impl_pairs is None or path not in impl_pairs:
        return []

    if not isinstance(tree, ast.Module) or not tree.body:
        return []

    expected_module, decl_package = impl_pairs[path]
    last_stmt = tree.body[-1]

    if not _is_import_of(last_stmt, expected_module, decl_package):
        return [_missing_import_msg(path, last_stmt, expected_module)]

    # Import found — run sub-checks
    messages: list["LintMessage"] = []

    # 1. noqa 注释检查（所有 import 形式）
    if source_lines is not None:
        messages.extend(_check_r002_noqa(path, last_stmt, source_lines))

    # 2. as 别名检查（仅 from . import 形式）
    messages.extend(_check_r002_alias(path, last_stmt, expected_module, decl_package))

    # 3. 间距检查
    messages.extend(_check_r002_spacing(path, tree))

    return messages


def _missing_import_msg(
    path: Path,
    last_stmt: ast.stmt,
    expected_module: str,
) -> "LintMessage":
    from mutobj.lint._api import LintMessage
    return LintMessage(
        path=str(path),
        line=(last_stmt.end_lineno or last_stmt.lineno) + 1,
        column=0,
        rule_id=R002,
        message=(
            f"同目录存在 _impl 模块 {expected_module!r}，"
            "建议在文件末尾添加 import 以触发 @impl 注册"
        ),
        severity=SEVERITY_WARNING,
    )


def _check_r002_spacing(
    path: Path,
    tree: ast.Module,
) -> list["LintMessage"]:
    """检查末尾 import 与前一定义之间是否有 2 个空行。"""
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
        message=(
            f"末尾 import 前应有 2 个空行（当前 {gap - 1} 个），"
            "与前一定义之间需保持两个空行"
        ),
        severity=SEVERITY_WARNING,
    )]


def _is_import_of(stmt: ast.stmt, expected_module: str, decl_package: str) -> bool:
    """判断一条 statement 是否 import 了指定模块。

    匹配以下形式：
        import mutio.mcp._view_impl
        import mutio.mcp._view_impl as _wip
        from mutio.mcp._view_impl import ...
        from mutio.mcp import _view_impl
        from . import _view_impl
    """
    if isinstance(stmt, ast.Import):
        for alias in stmt.names:
            if alias.name == expected_module:
                return True
    elif isinstance(stmt, ast.ImportFrom):
        if stmt.module is None:
            # from . import _xxx_impl
            if stmt.level == 1:
                for alias in stmt.names:
                    if decl_package + "." + alias.name == expected_module:
                        return True
            return False
        if stmt.level == 0:
            # from mutio.mcp._view_impl import ...
            if stmt.module == expected_module:
                return True
            # from mutio.mcp import _view_impl
            for alias in stmt.names:
                if stmt.module + "." + alias.name == expected_module:
                    return True
        # relative import with module (e.g. from . import xxx) already handled above
        # higher-level relative imports not supported for now
    return False


def _check_r002_noqa(
    path: Path,
    stmt: ast.stmt,
    source_lines: list[str],
) -> list["LintMessage"]:
    """检查 import 行是否有 ``# noqa: F401, E402`` 注释。

    抑制目标：flake8/ruff 的 F401（unused import）和 E402（import not at top）。
    """
    from mutobj.lint._api import LintMessage

    line_idx = stmt.lineno - 1
    if line_idx >= len(source_lines):
        return []

    line = source_lines[line_idx]

    # 查找 # noqa: ... 注释
    m = re.search(r'#\s*noqa[:]\s*([A-Z0-9,\s]*)', line)
    if not m:
        return [LintMessage(
            path=str(path),
            line=stmt.lineno,
            column=stmt.col_offset,
            rule_id=R002,
            message="末尾 import 行缺少 # noqa: F401, E402 注释",
            severity=SEVERITY_WARNING,
        )]

    codes = [c.strip() for c in m.group(1).split(",") if c.strip()]
    missing: list[str] = []
    if "F401" not in codes:
        missing.append("F401")
    if "E402" not in codes:
        missing.append("E402")
    if missing:
        return [LintMessage(
            path=str(path),
            line=stmt.lineno,
            column=stmt.col_offset,
            rule_id=R002,
            message=f"末尾 import 行 noqa 注释缺少 {'，'.join(missing)}",
            severity=SEVERITY_WARNING,
        )]
    return []


def _check_r002_alias(
    path: Path,
    stmt: ast.stmt,
    expected_module: str,
    decl_package: str,
) -> list["LintMessage"]:
    """检查 ``from . import _xxx_impl`` 是否有 ``as _xxx_impl`` 别名。

    只检查相对 import（``module is None, level == 1``）。
    别名抑制 pyright ``reportUnusedImport``。
    """
    from mutobj.lint._api import LintMessage

    if not isinstance(stmt, ast.ImportFrom):
        return []
    if stmt.module is not None or stmt.level != 1:
        return []

    for alias in stmt.names:
        if decl_package + "." + alias.name == expected_module:
            if alias.asname is None or alias.asname != alias.name:
                return [LintMessage(
                    path=str(path),
                    line=stmt.lineno,
                    column=stmt.col_offset,
                    rule_id=R002,
                    message=(
                        f"末尾 import 应使用 as 别名抑制 pyright reportUnusedImport："
                        f"from . import {alias.name} as {alias.name}"
                    ),
                    severity=SEVERITY_WARNING,
                )]
            return []
    return []
