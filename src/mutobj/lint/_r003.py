"""R003：@impl 函数命名规范。

格式：<类型名_snake_case>_<成员名>
  - 类型名 = 声明类名 camelCase → snake_case（SettingsPanel → settings_panel）
  - 成员名 = 方法名（__init__ → init）或 descriptor 属性名

例：@impl(Service.run) → service_run；@impl(Config.root.getter) → config_root

``_`` 前缀的函数会额外警告不应使用前缀。
严重度：warning
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._helpers import (
    R003,
    SEVERITY_WARNING,
    ClassSourceInfo,
    camel_to_snake,
    function_definition_line,
    iter_own_impl_entries,
    normalize_member_name,
)

if TYPE_CHECKING:
    from mutobj.lint._api import LintMessage


def check_r003(infos: list[ClassSourceInfo]) -> list["LintMessage"]:
    from mutobj.lint._api import LintMessage

    results: list[LintMessage] = []
    for info in infos:
        expected_type_prefix = camel_to_snake(info.class_name)
        for key, entry in iter_own_impl_entries(info):
            # Implementation 子类的 @impl 是自动生成的 bridge，无需命名检查
            if "::implementation::" in entry.source_module:
                continue
            func = entry.func
            path, line, _def_line = function_definition_line(func)
            if path is None:
                continue

            original_name = func.__code__.co_name
            expected_prefix = f"{expected_type_prefix}_{normalize_member_name(key)}"
            stripped_name = original_name.lstrip("_")
            has_expected_prefix = (
                stripped_name == expected_prefix
                or stripped_name.startswith(f"{expected_prefix}_")
            )

            if original_name.startswith("_"):
                if has_expected_prefix:
                    message = (
                        f"@impl 函数 {original_name!r} 不应使用 `_` 前缀；"
                        f"建议改为 {stripped_name!r}"
                    )
                else:
                    message = (
                        f"@impl 函数 {original_name!r} 不应使用 `_` 前缀，且应以 "
                        f"{expected_prefix!r} 开头"
                    )
                results.append(LintMessage(
                    path=str(path),
                    line=line,
                    column=0,
                    rule_id=R003,
                    message=message,
                    severity=SEVERITY_WARNING,
                    symbol=f"@impl {info.class_name}.{key}",
                ))
                continue

            if has_expected_prefix:
                continue

            results.append(LintMessage(
                path=str(path),
                line=line,
                column=0,
                rule_id=R003,
                message=f"@impl 函数 {original_name!r} 应以 {expected_prefix!r} 开头",
                severity=SEVERITY_WARNING,
                symbol=f"@impl {info.class_name}.{key}",
            ))

    return results
