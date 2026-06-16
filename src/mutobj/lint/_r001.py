"""R001：声明/实现风格一致性检查。

类级：同一个 Declaration 子类的方法必须全是 ``...`` 桩或全是真实函数体，不能混合。
文件级：同一个声明文件（非 _ 开头）应当全是声明类，不能混入实现类。
        _ 开头的文件视为 impl 文件，允许混合声明类与实现类。

跳过：无方法的类（``pass``）、``@typing.overload`` 装饰的方法。
严重度：error
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ._helpers import R001, SEVERITY_ERROR, ClassSourceInfo, class_category

if TYPE_CHECKING:
    from mutobj.lint._api import LintMessage


def check_r001(
    infos: list[ClassSourceInfo],
    file_groups: dict[Path, list[ClassSourceInfo]],
) -> list["LintMessage"]:
    from mutobj.lint._api import LintMessage

    results: list[LintMessage] = []

    # ── 类级：单类内部桩与实现混合 ──
    for info in infos:
        stub_methods = [m for m in info.methods if m.is_stub]
        impl_methods = [m for m in info.methods if not m.is_stub]
        if not stub_methods or not impl_methods:
            continue
        results.extend(
            LintMessage(
                path=str(info.file_path),
                line=m.line,
                column=m.column,
                rule_id=R001,
                message=(
                    f"类级风格混合：{info.class_name}.{m.name} 不是 `...` 桩；"
                    "声明类中所有方法应当全部是 `...` 桩"
                ),
                severity=SEVERITY_ERROR,
                symbol=f"Declaration:{info.class_name}.{m.name}",
            )
            for m in impl_methods
        )

    # ── 文件级：同一文件中声明类与实现类共存 ──
    # 跳过 _ 开头的文件（_xxx.py 视为 impl 文件，允许混合声明类与实现类）
    for file_path, file_infos in file_groups.items():
        if file_path.stem.startswith("_"):
            continue
        categories: list[tuple[ClassSourceInfo, str]] = []
        has_declaration = False
        has_implementation = False
        for info in file_infos:
            cat = class_category(info)
            categories.append((info, cat))
            if cat == "declaration":
                has_declaration = True
            elif cat == "implementation":
                has_implementation = True
        if not (has_declaration and has_implementation):
            continue
        for info, cat in categories:
            if cat not in {"declaration", "implementation"}:
                continue
            results.append(LintMessage(
                path=str(file_path),
                line=info.class_line,
                column=info.class_column,
                rule_id=R001,
                message=(
                    f"文件级风格混合：{info.class_name} 与同文件内其他 Declaration 子类的"
                    "声明/实现风格不一致，一个文件应当全是声明或全是实现"
                ),
                severity=SEVERITY_ERROR,
                symbol=f"Declaration:{info.class_name}",
            ))

    return results
