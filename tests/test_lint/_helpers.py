"""mutobj.lint 测试 helpers"""

from __future__ import annotations

import importlib
import sys
import textwrap
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Iterator


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


@contextmanager
def import_temp_pkg(pkg_root: Path, pkg_name: str = "pkg") -> Iterator[ModuleType]:
    """Temporarily import a package tree and clean its sys.modules entries on exit."""
    sys.path.insert(0, str(pkg_root))
    try:
        module = importlib.import_module(pkg_name)
        yield module
    finally:
        sys.path.remove(str(pkg_root))
        for name in list(sys.modules):
            if name == pkg_name or name.startswith(f"{pkg_name}."):
                del sys.modules[name]
