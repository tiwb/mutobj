# mutobj Lint 规范 — 测试目录结构整理

**状态**：✅ 已完成
**日期**：2026-05-19
**类型**：重构

## 需求

lint 测试原本全部集中在一个文件 `tests/test_lint.py`，1335 行，覆盖 R001 + R002 + CLI。后续新增 R003 及更多规则时，单文件持续膨胀不可维护。拆分为 `tests/test_lint/` 包目录，按规则分文件，共享 helpers 独立管理。

## 关键参考

- `tests/test_lint.py` — 拆分前的原始文件（12 个 TestClass，1335 行）
- `docs/specifications/feature-mutobj-lint-iter1.md` — R001 + R002 规则设计
- `docs/specifications/feature-mutobj-lint-iter3.md` — R003 规则设计（依赖本拆分完成）

## 最终目录结构

```
tests/
  test_lint.py → 删除

  test_lint/                  # 包目录
    __init__.py               # 空文件
    _helpers.py               # write / make_pkg 共享工具函数
    test_core.py              # LintMessage 数据结构 + lint_directory 扫描入口
    test_r001.py              # R001: 声明/实现风格混合 + TestDogfooding
    test_r002.py              # R002: _impl import 规范
    test_cli.py               # CLI: 文本/JSON/退出码/--exclude
```

不含 `conftest.py`：当前没有需要跨文件共享的 pytest fixture 或 hook，未来需要时再按 pytest 惯例新增。

## 迁移映射

| 原 test_lint.py 中的 TestClass | 目标文件 | 说明 |
|-------------------------------|---------|------|
| `TestLintMessage` | `test_core.py` | LintMessage 不可变性与排序 |
| `TestLintDirectory` | `test_core.py` | lint_directory 递归扫描/排除/排序 |
| `TestR001PureDeclarationFile` | `test_r001.py` | 纯声明文件 |
| `TestR001PureImplementationFile` | `test_r001.py` | 纯实现文件 |
| `TestR001ClassLevelMixed` | `test_r001.py` | 类级混合 |
| `TestR001FileLevelMixed` | `test_r001.py` | 文件级混合 |
| `TestR001EdgeCases` | `test_r001.py` | 边界情况 |
| `TestR001CrossFileInheritance` | `test_r001.py` | 跨文件继承 |
| `TestR001DeclImplPairConstraint` | `test_r001.py` | decl-impl 配对约束 |
| `TestDogfooding` | `test_r001.py` | mutobj 自身源码 lint 结果验证 |
| `TestR002MissingImport` | `test_r002.py` | import 缺失 |
| `TestR002ImportVariants` | `test_r002.py` | import 形式变体 |
| `TestR002ImportSpacing` | `test_r002.py` | 空行间距 |
| `TestR002Directory` | `test_r002.py` | lint_directory 扫描 |
| `TestR002NoqaCheck` | `test_r002.py` | noqa 注释检查 |
| `TestR002AliasCheck` | `test_r002.py` | as 别名检查 |
| `TestCLI` 系列（多个 class） | `test_cli.py` | CLI 行为测试 |

## 共享工具：`_helpers.py`

```python
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
```

`write` 和 `make_pkg` 是普通函数（非 fixture），各测试文件通过 `from ._helpers import write, make_pkg` 显式引入。

## 设计决策

1. **不改变测试逻辑**：纯文件搬迁，不修改任何 assert 或测试覆盖
2. **pytest 自动发现**：`tests/test_lint/` 是包目录（含 `__init__.py`），pytest 自动递归发现其中 `test_*.py`
3. **无 conftest.py**：`TestLintDirectory` 和 `TestLintMessage` 最初放在 conftest 中，但这与 conftest "pytest 配置文件/共享 fixture" 的语义不符，最终迁入独立文件 `test_core.py`
4. **按规则号 + 核心分文件**：规则号命名 `test_r001.py` / `test_r002.py` 便于定位；核心数据结构与扫描入口放 `test_core.py` 与规则测试区分
5. **删除旧文件**：`tests/test_lint.py` 已删除，避免与 `test_lint/` 包冲突

## 验证结果

- `pytest tests/test_lint/ -v` → 73 passed
- 全量 `pytest` → 414/415 passed（1 失败为已有 pyright fixture 问题，与本拆分无关）
