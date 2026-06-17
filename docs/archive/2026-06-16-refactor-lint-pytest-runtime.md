# mutobj lint 重构 — 从 AST 启发式扫描迁移到 pytest 运行时检查

**状态**：✅ 已完成
**日期**：2026-06-16
**类型**：重构

## 需求

### 当前问题

1. **架构与流程错位**：用户实际流程是 `pytest` → `pyright` → `mutobj-lint`。到 lint 阶段，被测代码已被 import、依赖齐全、副作用已发生。但 lint 坚持纯 AST 不 import，浪费了运行时能力。

2. **`_resolver.py` 是启发式天花板**：`_resolver.py`（~354 行）做跨文件 Declaration 继承链追踪，只覆盖「同一顶层包 + 简单 import 模式」。已暴露的破口：
   - 跨顶层包失效（`mutagent.SettingsPanel` 继承自 `mutgui.View` 时 R001 整类跳过）
   - 跨文件基类追溯做不动，要靠 `# noqa` 绕过
   - 动态 import、`as` 别名、动态生成的子类一律盲区

   运行时 `issubclass(cls, Declaration)` 一行根治。

3. **AST 做不到的规则被卡住**：以下规则在纯 AST 下要么不可能、要么实施成本/收益严重失衡：
   - R004 @impl 函数签名匹配（纯 AST 方案需 ~300 行设计，运行时下坍缩成几十行）
   - R005 field 类型覆盖检查
   - R006 声明全覆盖检测（声明类的所有桩方法是否都有 @impl）
   - R002 真语义版（"声明真有实现"而非"声明文件末尾真有 import 语句"）
   - R003 真语义版（property getter `Cls.prop.getter` 类型名提取，原 `_extract_type_name` 倒数第二节启发式错误地将 property 名当作 Declaration 类型名）

4. **CLI `mutobj-lint` 与运行时流程脱节**：独立 CLI 重新走文件发现 + 解析路径，与 pytest 阶段已有的 import 状态不复用。改为各项目在 `tests/` 下加 `test_lint.py` 用例，复用 pytest 的 import 状态与失败报告机制。

### 目标

把 mutobj-lint 的语义部分迁到运行时（pytest 内执行），保留纯格式部分走源码文本，删除 `_resolver.py` 与 CLI 入口。一阶段闭合：跨包 Declaration 子类识别缺失（R001）、`_extract_type_name` property getter 误判（R003）、纯 AST 方案下 R004 实现可行性瓶颈。

## 关键参考

- `mutobj/src/mutobj/lint/_api.py` — 当前公开 API（`LintMessage`, `lint_file`, `lint_directory`），将被 `check()` 替代
- `mutobj/src/mutobj/lint/_resolver.py` — DeclarationResolver，整文件删除（~354 行）
- `mutobj/src/mutobj/lint/_rules.py` — R001/R002/R003 实现（~625 行），按"语义 vs 格式"重新拆分
- `mutobj/src/mutobj/lint/__main__.py` — CLI 入口，删除（~176 行）
- `mutobj/src/mutobj/lint/__init__.py` — 包入口，保留但出口变更
- `mutobj/src/mutobj/core.py` — `Declaration` / `impl()` / `_get_implementation()` 等运行时 API

## 设计方案

### 公开 API：`check()` 替代 `lint_file()` / `lint_directory()`

单一入口，内部拆"加载 → 收集子类 → 跑规则"三阶段。

```python
from mutobj.lint import check, LintMessage, LintResults

# 精确模块（importlib.import_module）
check(["mutobj.core", "mutobj.lint"])

# 通配符：自动发现子模块（pkgutil.walk_packages）
check(["mutobj.*"])

# 混合 + 排除
check(["mutobj.core", "mutobj.lint.*"], exclude=["mutobj.lint._internal.*"])

# 多顶层包
check(["mutobj.*", "mutio.*"])

# 空 list = 不检测任何模块（返回空结果）
check([])
```

**参数语义**：

| 参数 | 类型 | 含义 |
|------|------|------|
| `patterns` | `list[str]` | 待检模块列表；空 list 表示不检测任何模块 |
| `exclude` | `list[str]` | 排除匹配模式；支持 `*` 通配符 |
| `"mutobj.core"` | — | `importlib.import_module("mutobj.core")` 后检查该模块 |
| `"pkg.*"` | — | `pkgutil.walk_packages` 递归发现子模块，逐个 import 后检查 |

patterns 顺序 = import 顺序，有顺序敏感的副作用模块放后面。

**返回值**：`LintResults`。pytest 中 `if results: pytest.fail(results.format())`。空 patterns 返回空 `LintResults`。

### 规则分层：运行时语义层 vs 源码格式层

`check()` 内部分两阶段执行：

#### 阶段 1：运行时语义规则（基于 `issubclass` / `inspect` / `get_type_hints` / `_get_implementation`）

| 规则 | 检查内容 | 实现要点 |
|------|---------|---------|
| **R001** | Declaration 子类的方法不能"声明/实现风格混合" | 遍历 `Declaration.__subclasses__()` 闭包，对每个类的本类定义方法判断是 `...` 桩还是真实 body（用 `inspect.getsource` + 简单 AST 判定，不再需要 `_resolver.py`） |
| **R002-语义** | 每个声明的桩方法都应有 `@impl` 注册 | `_get_implementation(cls.method) is not None`。比"末尾 import _impl 语句"更本质，能抓"import 了但 @impl 没注册成功"的真 bug |
| **R003-语义** | @impl 函数命名前缀（类型名 + 方法名） | 直接读 `decorated_func.__name__` 与 `meta.method.__qualname__`，用 `__qualname__.split(".")[0]` 拿类型名。`Cls.prop.getter` 的三段链式 Attribute 中倒数第二节是 property 名而非类型名，运行时直接拿 `__qualname__.split(".")[0]` 即得正确类型名。 |
| **R004** | @impl 函数签名与声明一致 | `inspect.signature(decl)` vs `inspect.signature(impl)` + `get_type_hints()` 拿解析后的类型对象。staticmethod/classmethod、async/sync、`*args`/`**kwargs`、参数名/数量/类型/返回类型一并自然处理 |

#### 阶段 2：源码格式规则（基于 AST/文本）

输入从"目录扫描得到的文件列表"换成"语义规则收集到的 Declaration 子类对应的源文件 = `inspect.getsourcefile(cls)`"。仅检查纯文本约束：

| 规则 | 检查内容 | 严重度 |
|------|---------|--------|
| **R002-格式** | 声明文件末尾 import `_impl` 的写法（noqa 注释、空行间距、import 别名规范） | warning |

> **R002 / R003 的拆分动机**：spec 旧版把 R002/R003 整体划入"AST 文本规则不动"，过于保守。运行时下"声明真有实现"和"@impl 函数命名"都更准确。
>
> **R003 不再分语义/格式两层**：`_` 前缀在运行时 `func.__name__` 中直接可见，与语义层合并为一个实现。
>
> **R002 格式层保留为 warning**：`from . import _foo_impl  # noqa: F401` 是给 reader 的明确信号——IDE 跳转、`grep` 查找实现都依赖它。语义层发现"忘了 import"的后果，格式层提示"import 存在但写法不规范"的中间问题。

### `_resolver.py` 删除

整文件删除（~354 行）。所有"找父类的声明文件"需求在运行时下通过 `cls.__mro__` 直接得到，无需 AST 模拟。

### CLI 删除

- `__main__.py` 删除（~176 行）
- `pyproject.toml` 中 `[project.scripts]` 的 `mutobj-lint` 条目删除
- `[tool.mutobj-lint]` 配置段删除（配置改为 `tests/test_lint.py` 中 `check(...)` 的实参）

**编辑器/IDE 集成路径**：等价 CLI 用 `python -c "from mutobj.lint import check; print(check(['mutobj.*']).format())"`，文档里给一行示例。不再单独维护 CLI。

### 各项目 `test_lint.py` 用例

每个使用 mutobj 的项目在 `tests/` 下加：

```python
# tests/test_lint.py
import pytest
from mutobj.lint import check

def test_lint() -> None:
    results = check(["mutobj.*"])  # 各项目改成自己的顶层包
    if results:
        pytest.fail(results.format())
```

### `LintMessage` 与报告格式

`LintMessage` 必须实现 `__str__`，使 pytest failure 输出直接可读：

```
R001 mutobj/core.py:42 [Declaration:Foo] 类级风格混合：方法 bar 是真实 body，但同类的 baz 是 ... 桩
R003 mutio/sock_impl.py:10 [@impl Sock.send] 函数名 _send 缺少类型名前缀，应为 sock_send
```

提供 `LintResults.format() -> str` 方法：每条一行 `str(msg)`，最末加汇总（"共 N 条问题"）。pytest assert 消息走它。

### `sys.modules` 与测试隔离

**关键决策**：`check()` 不主动清理 `sys.modules`，不保证幂等。规则如下：

1. **多次 `check()` 调用是过滤而非累积**：每次按当次参数从 `sys.modules` 中筛出待检模块，跑当次规则。`sys.modules` 状态由调用方管理。
2. **`check()` 只检测 patterns 中显式列出的模块**：空 patterns 不检测任何模块。无隐式扫描 `sys.modules` 全部内容的版本，避免意外的副作用传播。
3. **测试隔离责任在 `tests/test_lint.py`**：项目自己的 `test_lint.py` 一般是单一断言，不存在串扰；如确需多个 check 调用且要隔离，用 `monkeypatch.delitem(sys.modules, ...)` 或独立 pytest 进程（`pytest --forked`）。
4. **mutobj 自己 `tests/test_lint/` 下的测试**：R001/R002-语义/R003-语义/R004 测试需要"写临时包 → import → check → 断言 → 卸载"。提供测试辅助 `_helpers.import_temp_pkg(path) -> ContextManager[ModuleType]`，退出时清理 `sys.modules` 中所有以该包名开头的项。

### 副作用最小化

- `check()` 在 pytest 中运行，被检查模块的 import 副作用在 pytest 更早阶段（其他 test、conftest）已经发生过，`check()` 不引入新副作用。
- 带参数版若 import 一个新模块（之前没 import 过），副作用属于"用户显式要求"，不算 lint 强加。
- 文档 docstring 必须明确这一点，避免用户误以为 `check("整个项目")` 会"安全沙箱"运行。

### 数据流

```
check(patterns: list[str], exclude: list[str] = [])
  │
  ├─ Phase 0：模块加载
  │   ├─ patterns 为空 → 返回 []（不检测）
  │   ├─ "pkg.exact" → importlib.import_module
  │   ├─ "pkg.*" → pkgutil.walk_packages → import 每个子模块
  │   └─ 应用 exclude 过滤
  │
  ├─ Phase 1：收集 Declaration 子类
  │   target_classes = [c for c in 已加载模块的 vars().values()
  │                       if isinstance(c, type) and issubclass(c, Declaration)]
  │
  ├─ Phase 2：跑运行时语义规则
  │   for cls in target_classes:
  │       results += check_r001_runtime(cls)
  │       results += check_r002_semantic(cls)   # 每个桩方法是否有 @impl
  │       results += check_r003_semantic(cls)   # @impl 函数名规范
  │       results += check_r004_runtime(cls)    # @impl 函数签名匹配
  │
  └─ Phase 3：跑源码格式规则
      源文件集合 = {inspect.getsourcefile(cls) for cls in target_classes}
      for src in 源文件集合:
          results += check_r002_format(src)     # 末尾 import 语句格式（warning）
```

### 实施范围分阶段

#### 第一阶段（本 spec 直接落地）

- ✅ 新 `check()` API + `LintMessage.__str__` + `LintResults.format()`
- ✅ 删除 `_resolver.py`、`__main__.py`、`[tool.mutobj-lint]` 配置段
- ✅ R001 重写为运行时版（跨包 Declaration 子类识别）
- ✅ R003 语义层用 `__qualname__`（property getter 类型名提取）
- ✅ R002 拆分为语义层（"@impl 是否注册"）+ 格式层（末尾 import 语句格式）
- ✅ R004 运行时版
- ✅ 测试迁移 + `_helpers.import_temp_pkg()` 工具
- ✅ mutobj 自身 `tests/test_lint.py` 落地

#### 第二阶段（后续另开 spec）

- R005 field 类型覆盖检查
- R006 声明全覆盖检测

## 已确认的设计决策

以下决策由 QUEST Q1~Q4 确认后沉淀，原待定问题已删除：

1. **R003 不再独立保留格式层**：`_` 前缀在运行时 `func.__name__` 中可见，合并到 R003-语义层，一个实现覆盖全部。
2. **pytest 失败显示**：一阶段用 `LintResults.format()` 输出多行字符串作为 assert message，pytest 默认保留换行。如体验差后续再优化，不为预期之外的情况预先设计。
3. **破坏性变更不设 deprecation 周期**：mutobj 0.x，外部调用 `lint_file` / `lint_directory` / CLI 的场景未知。直接删除，CHANGELOG 记录即可。如有反馈再加 shim。
4. **R002 格式层保留为 warning**：生态约定俗成的 `# noqa: F401` import 模式是 reader 信号，IDE 跳转和 `grep` 都依赖它。

## 测试策略

### mutobj 自身测试结构

```
tests/test_lint/
├── _helpers.py          # 新增 import_temp_pkg() 上下文管理器
├── test_r001.py         # 重写：用临时包 + import + check
├── test_r002_semantic.py    # 新增：@impl 是否注册
├── test_r002_format.py      # 保留：末尾 import 语句格式（旧 R002 测试改名）
├── test_r003.py             # 重写：__name__ + __qualname__ 路径，含 property getter 场景
├── test_r004.py             # 新增：签名匹配（async/sync、参数名/数/类型、返回类型、staticmethod/classmethod、meta 标记等）
└── test_check_api.py        # 新增：check() 参数语义、exclude、多次调用
```

### 测试隔离辅助

```python
# tests/test_lint/_helpers.py
@contextmanager
def import_temp_pkg(pkg_root: Path, pkg_name: str) -> Iterator[ModuleType]:
    """临时把 pkg_root 加到 sys.path，import pkg_name，退出时清理 sys.modules。"""
    sys.path.insert(0, str(pkg_root))
    try:
        mod = importlib.import_module(pkg_name)
        yield mod
    finally:
        sys.path.remove(str(pkg_root))
        for name in list(sys.modules):
            if name == pkg_name or name.startswith(pkg_name + "."):
                del sys.modules[name]
```

### R004 测试场景

覆盖以下维度，实现路径走运行时（`inspect.signature` + `get_type_hints` + `impl_meta_of`）：async/sync 不匹配、参数名不一致、参数数量偏差、返回类型差异、参数类型差异、staticmethod/classmethod 首参跳过、`*args`/`**kwargs` 存在性、`# noqa: R004` 行内抑制、`AsyncAllowed` / `SignatureOverride` meta 标记抑制。

**Meta 标记机制**保留语义但简化实现：`@impl(method, AsyncAllowed())` 在运行时由 `impl()` 装饰器存到 `_impl_meta`，R004 直接 `impl_meta_of(func)` 拿到，无需 AST 解析。

### Dogfooding

mutobj 自身 + mutio + mutgui + mutagent + mutbot 全跑一次 `check(["<pkg>.*"])`，确保零误报。mutagent `SettingsPanel`（继承自跨包 `mutgui.View`）必须能被新 R001 正确识别；`@impl(SettingsPanel.conversation.getter)` 的类型名提取必须得到 `SettingsPanel`。

## 实施步骤清单

- [x] 更新 lint 公开 API：引入 `check()` / `LintResults` / 运行时 meta 标记，重构 `LintMessage`
- [x] 重写运行时规则层：完成 R001、R002-语义、R003、R004，并保留 R002-格式源码检查
- [x] 删除旧 AST 解析入口：移除 `_resolver.py`、`__main__.py`、`mutobj-lint` script 与 `[tool.mutobj-lint]` 配置
- [x] 迁移 mutobj lint 测试：补齐 `import_temp_pkg()`、`check()` API、R001/R002/R003/R004 覆盖与 `tests/test_lint.py`
- [x] 在 mutio、mutgui、mutagent、mutbot 落地 `tests/test_lint.py`，完成运行时 dogfooding
- [x] 运行目标验证并同步 README / guide 中的 lint 使用方式

## 测试验证

- `pyright`
- `pytest tests/test_lint_runtime tests/test_lint.py -q`
- `python -c "from mutobj.lint import check; ..."` 对 `mutobj.* / mutio.* / mutgui.* / mutagent.* / mutbot.*` 做运行时探测

## 遗留问题

- 下游仓库 dogfooding 尚未落地：当前运行时探测在 `mutio` / `mutgui` / `mutagent` / `mutbot` 发现大量现存 R003/R004 结果，需先确认这些是否为真实违规还是规则还需继续放宽，再决定是否提交各仓库 `tests/test_lint.py`。
