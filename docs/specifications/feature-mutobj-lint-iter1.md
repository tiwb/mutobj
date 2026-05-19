# mutobj Lint 规范 — R001 声明/实现风格 + R002 _impl import 检查

**状态**：✅ 已完成
**日期**：2026-05-19
**类型**：功能设计

## 需求

mutobj 项目采用声明-实现分离模式：`{stem}.py` 写 Declaration 子类的接口契约，`_{stem}_impl.py` 写 `@impl` 实现。需要 lint 工具保证风格一致性：

1. **R001** — 声明/实现风格不得混合：一个 Declaration 子类要么全是 `...` 桩（声明），要么全是真实代码（实现），不能混写；一个文件要么全是声明类，要么全是实现类
2. **R002** — 声明文件底部应 import 对应的 `_impl` 模块以触发 `@impl` 注册，且 import 写法需抑制 pyright/flake8 误报

## 关键参考

- `src/mutobj/lint/__init__.py` — lint 公开 API
- `src/mutobj/lint/_rules.py` — R001 / R002 规则实现
- `src/mutobj/lint/_resolver.py` — Declaration 子类识别
- `src/mutobj/lint/_api.py` — `lint_file` / `lint_directory` 入口，预扫描 impl 配对
- `src/mutobj/lint/__main__.py` — CLI 入口
- `tests/test_lint.py` — 全部测试（73 个）

## 设计方案

### R001 — 声明/实现风格混合检测

**判定规则**：

- **桩方法**：`body == [docstring?, ...]` — 可选 docstring 后跟 `...`
- **实现方法**：body 不匹配上述模式（含 `pass`、`raise NotImplementedError`、有真实语句）
- `@overload` / `@typing.overload`：从判定中剔除
- `__init__`：不豁免，与普通方法一视同仁。decl 文件中 `__init__` 必须是桩或完全省略
- 装饰器（property/classmethod/staticmethod/abstractmethod）不影响判定
- 嵌套类（非 Declaration 子类）不参与判定
- 零方法类 → 无行为类（不参与文件级混合判定）

**三级检测**：

| 级别 | 触发条件 | ID | 严重度 |
|------|---------|-----|--------|
| 类级混合 | 单个 Declaration 子类内同时存在桩方法和实现方法 | R001 | error |
| 文件级混合 | 文件内同时存在声明类和实现类（无行为类不参与） | R001 | error |
| decl-impl 配对约束 | 同目录存在 `_{stem}_impl.py`，声明侧文件中的 Declaration 子类必须是纯声明类 | R001 | error |

### R002 — 声明文件底部 _impl import 检查

**命名约定**：`{stem}.py`（声明）↔ `_{stem}_impl.py`（实现），两者在同一包目录下。

**预扫描**：`lint_directory` 在逐文件 AST 分析前，按目录收集所有 `_{stem}_impl.py` 并匹配同目录 `{stem}.py`，生成配对表 `{decl_path: (impl_module_name, package)}`。

**规则**：如果同目录存在 `_{stem}_impl.py`，则 `{stem}.py` 必须以 import 该模块作为文件最后一个 top-level statement。

**四个子检查**：

| # | 检查项 | 检查方式 | 严重度 | 抑制目标 |
|---|--------|----------|--------|----------|
| 1 | import 存在 + 末尾位置 | AST 最后 top-level statement | warning | — |
| 2 | import 前有 2 空行 | AST 行号差 | warning | — |
| 3 | `from . import` 有 `as _xxx_impl` 别名 | AST `ImportFrom.names[0].asname` | warning | pyright `reportUnusedImport` |
| 4 | import 行含 `# noqa: F401, E402` | 读源码行，正则匹配 | warning | flake8/ruff F401, E402 |

**Import 形式匹配**：

- `import pkg._xxx_impl` 或 `import pkg._xxx_impl as _wip`
- `from pkg._xxx_impl import ...`
- `from pkg import _xxx_impl`
- `from . import _xxx_impl`

别名检查仅限 `from . import`（`module is None, level == 1`）形式；其他形式不强求。noqa 注释检查适用于所有 import 形式。

**不触发规则**：

- 声明文件没有对应的 `_impl` 文件 → 不检查
- `__init__.py` 所在目录外（非包目录）→ 不检查
- `_*_impl.py` 模式以外的下划线文件（如 `_schema.py`）→ 不检查

**正确写法示例**：

```python
from mutobj import Declaration

class MyView(Declaration):
    def render(self, data) -> str: ...
    async def on_event(self, event) -> None: ...


from . import _view_impl as _view_impl  # noqa: F401, E402
```

## 实施步骤清单

- [x] `_rules.py` — R001 类级/文件级/配对约束检测，R002 末尾 import 四项检查
- [x] `_api.py` — 目录预扫描 impl 配对，`_lint_one` 传递 `source_lines`
- [x] `__main__.py` — CLI description 覆盖 R001 + R002
- [x] `tests/test_lint.py` — 73 个测试（R001：38 个，R002：24 个，基础设施：10 个，dogfooding：1 个）

## 测试覆盖

| 领域 | 测试数 | 覆盖场景 |
|------|--------|----------|
| R001 类级/文件级 | 24 | 纯声明、纯实现、混合、装饰器、跨文件继承、无行为类、`__init__` |
| R001 配对约束 | 5 | decl-impl 强制纯声明、零方法标记类 |
| R002 缺失/变体/间距/目录 | 12 | 4 种 import 形式、2/1/0 空行、lint_directory 预扫描 |
| R002 noqa | 7 | 正确、缺失、缺 F401、缺 E402、顺序颠倒、绝对 import、多余空格 |
| R002 alias | 5 | 正确、缺失、不匹配、绝对 import 跳过、noqa+alias 双缺 |
| 目录/CLI/LintMessage | 9 | 递归扫描、排除、排序、JSON 输出、子进程调用 |
| Dogfooding | 1 | mutobj 自身零违规 |
