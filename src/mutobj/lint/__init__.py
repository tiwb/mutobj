"""
mutobj.lint — mutobj 风格静态检查工具

提供 R001 规则：声明 / 实现风格在同一文件 / 同一类内不可混合。

公开 API:
    lint_file(path) -> list[LintMessage]
    lint_directory(path, *, exclude=None) -> list[LintMessage]
    LintMessage
"""

from mutobj.lint._api import LintMessage, lint_file, lint_directory

__all__ = ["LintMessage", "lint_file", "lint_directory"]
