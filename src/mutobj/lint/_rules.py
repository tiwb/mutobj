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
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mutobj.lint._api import LintMessage  # 避免循环 import
    from mutobj.lint._resolver import DeclarationResolver, FileAnalysis


R001 = "R001"
SEVERITY_ERROR = "error"


def check_r001(
    path: Path,
    tree: ast.AST,
    file_info: "FileAnalysis",
    resolver: "DeclarationResolver",  # noqa: ARG001 — 预留扩展
) -> list["LintMessage"]:
    """对单文件执行 R001 检测"""
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
