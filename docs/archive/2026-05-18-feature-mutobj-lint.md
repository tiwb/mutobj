# mutobj 静态 Lint 工具

**状态**：✅ 已完成
**日期**：2026-05-18
**类型**：功能设计

## 需求

mutobj 的核心约定可以浓缩为一条：

> **一个文件要么是 mutobj 声明风格（全 `...` 桩），要么是纯 Python 风格（全实现），两种风格不能混在同一文件。** 声明类中桩方法统一用 `...`，文档写在声明侧（桩方法 docstring），实现侧不加文档。

这一约定本身简单，但纯约定无法防止违规进入代码库。需要一个静态分析工具：

- 在开发期 / CI 阶段自动检测违规代码
- 不 import 被检测模块（快、无副作用）

**本文档只设计 lint 工具的实现。**

## 关键参考

- `refactor-impl-non-declaration-guard.md` — `@impl` 目标须为 Declaration 的运行时守卫（与本工具互补）
- `src/mutobj/` — 主包目录，lint 模块直接放在这里
- mutobj 依赖纯标准库，lint 也保持纯 `ast` 实现

## 设计方案

### 模块定位

`mutobj.lint` 作为 mutobj 子模块，与 mutobj 同版本发布。理由：

- lint 零第三方依赖（纯 `ast` 标准库），不像 flake8 那样有拆包的动机
- 规则跟随 mutobj 版本变更，放在一起避免版本不同步
- 独立 PyPI 包（如 `mutobj-lint`）的价值目前看不到

### API 设计

```python
import mutobj.lint

# 公开 API
results = mutobj.lint.lint_file(path)         # path: str | Path
results = mutobj.lint.lint_directory(path)    # 递归扫描

@dataclass(frozen=True)
class LintMessage:
    rule_id: str          # "R001"
    path: str             # 文件路径
    line: int             # 行号
    column: int           # 列号（便于编辑器跳转）
    message: str          # 人类可读描述
    severity: str         # "error" | "warning"
```

设计要点：
- **纯 AST 分析**：`ast.parse()` + `ast.NodeVisitor`，不 import 任何被检测模块
- **无副作用**：可在 CI / pre-commit 中安全跑
- **结果有序**：按 (path, line, column) 排序，输出可重现

### 规则集（MVP）

#### R001 — Declaration 子类方法体一致性

**类级**：一个 Declaration 子类只要存在任何一个桩方法（`...`），那它所有方法都必须是桩。方法是桩当且仅当 body 为 `...`（可带 docstring）。

**文件级**：同一个文件内所有 *有行为的* Declaration 子类必须同模式——全是声明类，或全是实现类。

**判定**：

- **桩方法**：body = `[Expr(Constant(str))?, Expr(Constant(Ellipsis))]`（可选的 docstring 后跟 `...`）
- **实现方法**：body ≠ 上述（含 `raise NotImplementedError`、`pass`、有实际语句）
- **声明类**：至少一个桩方法 → 所有方法必须是桩方法
- **实现类**：至少一个实现方法 且 零个桩方法
- **无行为类**：零个方法（零桩零实现）→ 不参与文件级混合判断（允许纯标记类与其他类共存）
- 普通 Python 类（非 Declaration 子类）不参与判定

| 场景 | 结果 |
|------|------|
| 全 `...` 桩 | ✅ 纯声明文件 |
| 全实际实现（无 `...`） | ✅ 纯实现文件 |
| 无 Declaration 子类 | ✅ 跳过，不报告 |
| 无行为类 + 声明类共存 | ✅ 不冲突（无行为类不参与判定） |
| 无行为类 + 实现类共存 | ✅ 同上 |
| 桩 + `raise NotImplementedError` 混合 | ❌ R001（类级混合） |
| 桩 + `pass` / 实际语句混合 | ❌ R001（类级混合） |
| `__init__` 含 `super().__init__()` / 赋值，同类其他方法为桩 | ❌ R001（`__init__` 不豁免） |
| 实现类中 `__init__` 是 `...` 桩 | ❌ R001（同上，桩面在实现侧同样违反） |
| 一个文件里声明类 + 实现类混放 | ❌ R001（文件级混合） |

| Lint ID | 检测内容 | 严重程度 | 理由 |
|---------|---------|---------|------|
| `R001` | 同一文件中 Declaration 子类存在"声明类"和"实现类"混合；或声明类内部存在非桩方法 | error | 一个文件要么全桩要么全实现，混合写法导致代码意图不清、review 心智负担重 |

> **不做 `@impl` 函数命名 / 目标校验**：AST 静态分析做不到 100% 准确，由运行时守卫兜底。
>
> **`__init__` 不豁免**：mutobj `Declaration` 基类已提供通用 `__init__`（按声明字段填充）和 `__post_init__` hook（由元类强制调用，不依赖 `super().__init__()` 链），decl 侧 `__init__` 要么不写、要么写成桩（实现走 `@impl`）；含 `super().__init__()` / `pass` / 赋值等实际语句的 `__init__` 是实现，参与 R001 一致性判定。
>
> **不做跨文件导入检测**：先聚焦核心规则，后续按需扩展。
>
> **不提供外部插件机制**：下游如需自定义规则，MVP 阶段推荐 fork 或独立实现；待出现真实需求再设计插件 API，避免过早抽象。

### 实现要点

#### Declaration 类识别策略

lint 不 import 被检测模块，无法直接判断 `class X(Y)` 中的 Y 是否是 `Declaration` 子类。采用 AST 启发式：

1. **直接基类**：`class X(mutobj.Declaration)` 或 `class X(Declaration)` 且文件内有 `from mutobj import Declaration`
2. **传递基类**：`class X(Y)` 中 Y 是同文件内已识别的 Declaration 子类
3. **跨文件传递**：通过同包 `from .module import Y` 解析 Y 的来源文件，递归识别（限同包内，不解析 site-packages）
4. **不可判定**：上述都不命中时，保守不报警（避免误报）

#### R001 检测算法

对每个 `.py` 文件：

1. 识别文件中所有 Declaration 子类
2. 对每个 Declaration 子类，遍历其 `FunctionDef` / `AsyncFunctionDef`（`__init__` 也在内，不豁免）：
   - 判断每个方法体是"桩"还是"实现"（strip docstring 后是否只剩 `Expr(Constant(Ellipsis))`）
   - 如果同时存在桩和实现 → 报告类级混合
   - 如果只有桩 → 标记为声明类
   - 如果只有实现 → 标记为实现类
   - 如果零方法 → 标记为无行为类
3. 横跨所有有行为的 Declaration 子类（排除无行为类）：
   - 如果同时存在声明类和实现类 → 报告文件级混合
4. 无 Declaration 子类的文件直接跳过

#### 实施细节补充

以下细节钉死实施边界，避免反复纠结：

1. **`@overload` 桩排除**：被 `@typing.overload` / `@overload` 装饰的方法不参与桩 / 实现判定（标准 typing 用法，`...` 是必需的桩；若纳入会让任何 overload 用户的实现类误报）。
2. **`__init__` 同普通方法**：不豁免，根据 body 是否为 `...` 桩判定成“声明侧桩”或“实现”（`Declaration` 基类已提供通用 `__init__` 与 `__post_init__` hook，decl 侧不需手写实现型 `__init__`）。
3. **decorator 不影响桩判定**：`@property` / `@classmethod` / `@staticmethod` / `@abstractmethod` 等装饰的方法，body 判定规则与普通方法一致（`...` 是桩，其他是实现）。
4. **嵌套类**：Declaration 子类内部定义的普通类（非 Declaration 子类）不参与判定，沿用 "非 Declaration 子类不参与" 规则。
5. **import 别名支持**：`from mutobj import Declaration as D` 这类 `as` 别名识别 `Declaration`，AST 上读 `alias.asname` 即可。
6. **跨包 Declaration 识别保守降级**：跨顶层包（如 mutgui 文件 `from mutagent.xxx import Foo`）、`site-packages` 不解析；解析不到 → 落入 "不可判定" 分支，**不报警**（避免误报）。
7. **空类 / 空方法体**：Declaration 子类无方法 → 视为声明类（与现有约定一致，零桩零实现）；方法 body 是单纯的 `pass` → 实现方法（非桩）。

#### 文件扫描范围

- `lint_directory` 递归扫所有 `.py` 文件
- 跳过：`__pycache__`、`.git`、`.venv`、`venv`、`build`、`dist`、`node_modules`
- 通过 `--exclude` 选项可追加排除模式（CLI 引入时）

### 文件位置

- `src/mutobj/lint/__init__.py` — 公开 API（`lint_file` / `lint_directory` / `LintMessage`）
- `src/mutobj/lint/__main__.py` — CLI 入口（`mutobj-lint` 命令）
- `src/mutobj/lint/_rules.py` — R001 规则实现
- `src/mutobj/lint/_resolver.py` — Declaration 类识别（同/跨文件解析）

### CLI 命名

`mutobj-lint` 作为独立命令（与 pip-tools、tox-gh-actions 风格一致），而非 `mutobj` 的子命令。理由：mutobj 是库，日常无 CLI 需求，为 lint 去造主命令属于过度设计。在 `pyproject.toml` 中通过 `[project.scripts]` 声明入口：

```toml
[project.scripts]
mutobj-lint = "mutobj.lint.__main__:main"
```

入口脚本在 `pip install mutobj` / `uv tool install mutobj` 时自动安装到 PATH，但只有实际执行 `mutobj-lint` 时才会 import lint 模块——不执行就是磁盘上的死代码，零运行时开销。

### CLI 用法

```bash
mutobj-lint src/mutgui/
mutobj-lint --json src/mutgui/                 # JSON 输出（CI 用）
mutobj-lint --exclude tests src/mutgui/        # 排除目录
```

- **文本输出**参考 ruff：`path:line:col: R001 message`，便于终端 / 编辑器 problem matcher 解析。
- **JSON 输出**兼容 [Code Climate spec](https://github.com/codeclimate/platform/blob/master/spec/analyzers/SPEC.md)（GitLab CI 与多家工具支持）。
- **退出码**：发现 error → 1，全清 → 0，便于 CI / pre-commit 集成。

### 规则演进策略

- 新增规则：分配下一个 `R00x`，本 spec 表格追加一行（含检测内容和理由）
- 已废弃规则：保留 ID 标注 `[已废弃]`，运行时返回空结果但不报错（兼容旧 CI 配置）
- 严重程度变更：在 spec 中显式记录变更原因

## 实施步骤清单

- [x] 创建 `src/mutobj/lint/` 包骨架（`__init__.py` 公开 API、`__main__.py` CLI 入口、`_rules.py`、`_resolver.py`）
- [x] 实现 `LintMessage` 数据类与排序规则（按 path, line, column）
- [x] 实现 `_resolver.py`：AST 启发式识别 Declaration 子类（直接基类 / 同文件传递 / 同包跨文件传递 / 不可判定降级），支持 `from mutobj import Declaration as D` 别名
- [x] 实现 `_rules.py` 的 R001：桩 / 实现方法判定（含 docstring + `...` 形态、`@overload` 排除、decorator 透明、空方法处理），类级一致性 + 文件级一致性
- [x] 实现 `lint_file` / `lint_directory` 公开 API，目录扫描排除 `__pycache__` / `.git` / `.venv` / `venv` / `build` / `dist` / `node_modules`
- [x] 实现 CLI 入口（`mutobj-lint`）：文本输出 `path:line:col: R001 message`、`--json` Code Climate 兼容输出、`--exclude` 模式、退出码（有 error → 1）
- [x] `pyproject.toml` 注册 `[project.scripts]` 入口 `mutobj-lint = "mutobj.lint.__main__:main"`
- [x] 编写测试 `tests/test_lint.py`：覆盖 R001 各场景（全桩 / 全实现 / 类级混合 / 文件级混合 / 无 Declaration 跳过 / `@overload` 不误报 / `@property` 桩 / 跨文件传递识别 / 跨包不可判定不报警 / `as` 别名 / 无行为类 / `__init__` 不豁免）
- [x] CLI 集成测试：文本与 JSON 输出格式、退出码、`--exclude`
- [x] dogfooding：对 `src/mutobj/` 自身跑 lint，确认零违规
- [x] 更新 README：新增 lint 工具使用说明

## 消费者场景

| 消费者 | 场景 | 依赖的输出 | 验收标准 |
|--------|------|-----------|---------|
| mutgui CI | PR 中自动检查 | `mutobj.lint` API + CLI 退出码 | CI 跑 lint 发现违规即 fail |
| mutgui 开发者 | 本地 pre-commit | CLI | 提交前发现 R001 违规 |
| mutbot 开发者 | 同上 | 同上 | mutbot 代码通过 lint |
| mutobj 维护者 | dogfooding | API | mutobj 自身代码通过 lint |
| 编辑器 / IDE 集成 | 实时反馈 | JSON 输出 | 输出可被 problem matcher 解析定位 |
