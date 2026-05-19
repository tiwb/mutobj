"""mutobj.lint 测试 — 共享 helpers"""

from __future__ import annotations

import textwrap
from pathlib import Path


def write(tmp: Path, rel: str, code: str) -> Path:
    """在 tmp 下创建文件（自动建父目录），写入 dedent 后的代码"""
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(code).lstrip(), encoding="utf-8")
    return p


def make_pkg(tmp: Path, name: str = "pkg") -> Path:
    """创建一个最小包结构 pkg/__init__.py，返回包目录"""
    pkg = tmp / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    return pkg
