"""
Declaration 子类识别（纯 AST 启发式）

策略：
1. 直接基类 `mutobj.Declaration` 或 `Declaration`（需 `from mutobj import Declaration`，支持 as 别名）
2. 同文件内传递：`class X(Y)`，Y 是已识别的 Declaration 子类
3. 同顶层包跨文件传递：`from .module import Y` 或 `from same_pkg.module import Y`
4. 跨顶层包 / 解析不到 → 不可判定，调用方按"保守不报警"处理

实现要点：
- 不 import 任何被检测模块，全程纯 ast
- 文件分析结果缓存在 resolver 实例上（同一目录扫描时复用）
- 循环引用通过 in-progress 集合防止无限递归
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class _ImportEntry:
    """单条 import 记录的归一化形式

    target_module: 真实模块路径（绝对，已解析相对导入）
    target_name: 模块内的原始名字；None 表示 import 整个模块
    """
    target_module: str
    target_name: Optional[str]


@dataclass
class FileAnalysis:
    """单文件的 AST 分析结果"""
    path: Path
    # 顶层包名（如 "mutobj"），None 表示文件不在某个 Python 包内
    top_package: Optional[str]
    # 当前模块的点分路径（如 "mutobj.lint._api"）；无包时为 None
    module_qualname: Optional[str]
    # 本地名字 -> import 来源（仅记录 from-import 和 import-as，普通 import 也记一条）
    imports: dict[str, _ImportEntry]
    # 文件中所有顶层类定义：name -> ClassDef 节点
    classes: dict[str, ast.ClassDef] = field(default_factory=lambda: {})
    # 已判定为 Declaration 子类的本地类名集合（在解析过程中填充）
    declaration_classes: set[str] = field(default_factory=lambda: set())


class DeclarationResolver:
    """跨文件 Declaration 子类识别器，带缓存与循环检测"""

    def __init__(self) -> None:
        self._cache: dict[Path, FileAnalysis] = {}
        self._in_progress: set[Path] = set()

    # ------------------------------------------------------------ public

    def analyze_file(
        self,
        path: Path,
        *,
        tree: ast.AST | None = None,
    ) -> FileAnalysis:
        """分析文件并返回结果（带缓存）。

        若文件无法读取或解析，返回一个空的 FileAnalysis（无 declaration_classes）。
        """
        path = path.resolve()
        if path in self._cache:
            return self._cache[path]

        if tree is None:
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(path))
            except (OSError, SyntaxError):
                fa = FileAnalysis(
                    path=path, top_package=None, module_qualname=None, imports={},
                )
                self._cache[path] = fa
                return fa

        if path in self._in_progress:
            # 循环：先返回一个最小骨架，调用方会忽略未填充的 declaration_classes
            fa = FileAnalysis(
                path=path, top_package=None, module_qualname=None, imports={},
            )
            return fa

        self._in_progress.add(path)
        try:
            top_pkg, mod_qn = _detect_package(path)
            imports = _collect_imports(tree, mod_qn)
            classes = _collect_top_level_classes(tree)
            fa = FileAnalysis(
                path=path,
                top_package=top_pkg,
                module_qualname=mod_qn,
                imports=imports,
                classes=classes,
            )
            # 直接缓存（即使 declaration_classes 还未完全计算），后续按需补齐
            self._cache[path] = fa
            # 计算 declaration_classes：对所有顶层类做不动点判定
            self._fill_declaration_classes(fa)
            return fa
        finally:
            self._in_progress.discard(path)

    # ----------------------------------------------------------- private

    def _fill_declaration_classes(self, fa: FileAnalysis) -> None:
        """对文件中所有顶层类，判定是否为 Declaration 子类"""
        # 不动点迭代：直到一轮无变化
        changed = True
        while changed:
            changed = False
            for name, cls in fa.classes.items():
                if name in fa.declaration_classes:
                    continue
                if self._class_is_declaration(fa, cls):
                    fa.declaration_classes.add(name)
                    changed = True

    def _class_is_declaration(self, fa: FileAnalysis, cls: ast.ClassDef) -> bool:
        """判定 ClassDef 是否（直接或传递）继承自 mutobj.Declaration"""
        for base in cls.bases:
            if self._base_is_declaration(fa, base):
                return True
        return False

    def _base_is_declaration(self, fa: FileAnalysis, base: ast.expr) -> bool:
        # 形态 1: Name
        if isinstance(base, ast.Name):
            local = base.id
            # 1a: 文件内已识别的 Declaration 子类
            if local in fa.declaration_classes:
                return True
            # 1b: 通过 import 引入的名字
            entry = fa.imports.get(local)
            if entry is not None:
                return self._import_target_is_declaration(fa, entry)
            return False

        # 形态 2: Attribute（如 mutobj.Declaration）
        if isinstance(base, ast.Attribute):
            # 收集完整点分路径
            parts = _attr_to_dotted(base)
            if parts is None:
                return False
            head, *tail = parts
            entry = fa.imports.get(head)
            if entry is None:
                return False
            # 拼出最终目标：entry.target_module + entry.target_name? + tail
            mod = entry.target_module
            name_chain: list[str] = []
            if entry.target_name is not None:
                name_chain.append(entry.target_name)
            name_chain.extend(tail)
            # mutobj 包内 Declaration 直接命中
            if mod == "mutobj" and name_chain == ["Declaration"]:
                return True
            # 其他情况：尝试跨文件解析
            if len(name_chain) == 1:
                synth = _ImportEntry(target_module=mod, target_name=name_chain[0])
                return self._import_target_is_declaration(fa, synth)
            return False

        # 其他（Subscript / Call 等）暂不处理
        return False

    def _import_target_is_declaration(
        self, fa: FileAnalysis, entry: _ImportEntry,
    ) -> bool:
        """判定一个 import 目标（模块.名字）是否是 mutobj.Declaration 子类"""
        # mutobj 直接命中
        if entry.target_module == "mutobj" and entry.target_name == "Declaration":
            return True
        # 仅 mutobj 内部其他名字不命中
        if entry.target_module == "mutobj":
            return False
        if entry.target_name is None:
            return False

        # 跨文件解析：仅限同顶层包
        if fa.top_package is None:
            return False
        target_top = entry.target_module.split(".", 1)[0]
        if target_top != fa.top_package:
            return False

        # 解析目标模块对应文件路径
        target_file = self._resolve_module_to_file(fa, entry.target_module)
        if target_file is None:
            return False
        target_fa = self.analyze_file(target_file)
        return entry.target_name in target_fa.declaration_classes

    def _resolve_module_to_file(
        self, fa: FileAnalysis, module: str,
    ) -> Optional[Path]:
        """根据当前文件的包定位、把绝对模块路径解析成本地源文件"""
        if fa.module_qualname is None or fa.top_package is None:
            return None
        if not module.startswith(fa.top_package):
            return None
        # 找到顶层包根目录：从当前文件向上找，直到找到一个不含 __init__.py 的父目录
        pkg_root = _find_package_root(fa.path)
        if pkg_root is None:
            return None
        # pkg_root 的子目录就是 top_package；module 的相对部分挂到 pkg_root.parent 下
        rel = module.replace(".", "/")
        candidate1 = pkg_root.parent / f"{rel}.py"
        candidate2 = pkg_root.parent / rel / "__init__.py"
        if candidate1.is_file():
            return candidate1.resolve()
        if candidate2.is_file():
            return candidate2.resolve()
        return None


# ============================================================ helpers


def _detect_package(path: Path) -> tuple[Optional[str], Optional[str]]:
    """根据 __init__.py 链确定 (顶层包名, 当前模块的点分路径)。

    例：path = src/mutobj/lint/_api.py，沿 __init__.py 链回溯
        - mutobj/lint/__init__.py 存在
        - mutobj/__init__.py 存在
        - src/__init__.py 不存在 → 顶层包 = mutobj
        → ("mutobj", "mutobj.lint._api")

    若文件本身不在包内，返回 (None, None)。
    """
    path = path.resolve()
    if path.name == "__init__.py":
        # __init__.py 自身代表所在目录的包
        parts: list[str] = []
        d = path.parent
    else:
        parts = [path.stem]
        d = path.parent
    while d != d.parent and (d / "__init__.py").is_file():
        parts.append(d.name)
        d = d.parent
    if not parts:
        return None, None
    parts.reverse()
    if path.name == "__init__.py":
        if not parts:
            return None, None
        return parts[0], ".".join(parts)
    return parts[0], ".".join(parts)


def _find_package_root(path: Path) -> Optional[Path]:
    """找到 path 所在顶层包的根目录（最外层仍含 __init__.py 的目录）"""
    path = path.resolve()
    d = path.parent if path.name != "__init__.py" else path.parent
    last_pkg: Optional[Path] = None
    while d != d.parent and (d / "__init__.py").is_file():
        last_pkg = d
        d = d.parent
    return last_pkg


def _collect_imports(
    tree: ast.AST, current_module: Optional[str],
) -> dict[str, _ImportEntry]:
    """收集模块顶层的 import / from-import，归一化为 {本地名: _ImportEntry}"""
    imports: dict[str, _ImportEntry] = {}
    if not isinstance(tree, ast.Module):
        return imports
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                # `import a.b.c` 时 local 一定是顶层 `a`，target_module 也用顶层
                # `import a.b.c as x` 时 local=x，target_module=a.b.c
                if alias.asname is not None:
                    imports[local] = _ImportEntry(
                        target_module=alias.name, target_name=None,
                    )
                else:
                    imports[local] = _ImportEntry(
                        target_module=local, target_name=None,
                    )
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_relative_import(node, current_module)
            if module is None:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                imports[local] = _ImportEntry(
                    target_module=module, target_name=alias.name,
                )
    return imports


def _resolve_relative_import(
    node: ast.ImportFrom, current_module: Optional[str],
) -> Optional[str]:
    """把 from .x import y / from ..x import y 解析为绝对模块路径"""
    if node.level == 0:
        return node.module
    if current_module is None:
        return None
    parts = current_module.split(".")
    # from . import y 出现在 pkg/__init__.py 时，current_module=pkg，level=1 应回到 pkg
    # from . import y 出现在 pkg/sub.py 时，current_module=pkg.sub，level=1 应回到 pkg
    # 简化处理：去掉 level 个尾部段
    if len(parts) < node.level:
        return None
    base_parts = parts[: len(parts) - node.level]
    # 当 current_module 是 __init__（即包本身），上面公式可能错；
    # 但我们 _detect_package 给 __init__.py 返回的是 "pkg"（不带 .__init__），按 module 处理
    # 实际经验法则：level=1 应保留所有父包；这里偏严格的做法对绝大多数代码可用
    if node.module:
        if base_parts:
            return ".".join(base_parts + [node.module])
        return node.module
    if base_parts:
        return ".".join(base_parts)
    return None


def _collect_top_level_classes(tree: ast.AST) -> dict[str, ast.ClassDef]:
    classes: dict[str, ast.ClassDef] = {}
    if not isinstance(tree, ast.Module):
        return classes
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes[node.name] = node
    return classes


def _attr_to_dotted(node: ast.expr) -> Optional[list[str]]:
    """把 a.b.c 形式的 Attribute 链拆成 ["a", "b", "c"]"""
    parts: list[str] = []
    cur: ast.expr = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    parts.reverse()
    return parts
