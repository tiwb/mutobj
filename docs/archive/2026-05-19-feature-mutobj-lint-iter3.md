# mutobj Lint 规范 — R003 @impl 函数命名规范

**状态**：✅ 已完成
**日期**：2026-05-19
**类型**：功能设计

## 需求

`@impl` 装饰的函数如果以 `_` 开头，会在 pyright `strict` 模式下触发 `reportUnusedFunction`。

原因：pyright 只对私有函数（`_` 前缀）检查是否被访问，而 `@impl` 通过运行时 `_register_to_chain` 注册函数，pyright 静态分析看不到这条调用链。

**去掉 `_` 前缀即可消除误报**：pyright 不再将其视为私有函数，不再检查是否被访问。命名更改不改变任何运行时行为。

需要在 mutobj lint 工具中新增 R003 规则，检测 `_*_impl.py` 中 `@impl` 装饰的函数是否使用了 `_` 前缀命名。

## 关键参考

- `src/mutobj/lint/_rules.py` — 现有 R001 / R002 实现
- `src/mutobj/lint/_resolver.py` — Declaration 子类识别与 import 解析
- `tests/test_lint.py` — 现有 73 个测试，R003 测试沿用同一模式
- `docs/specifications/feature-mutobj-lint-iter1.md` — R001 + R002 设计
- `docs/specifications/feature-mutobj-lint-iter2.md` — lint 测试目录结构整理

## 实测证据

mutgui strict 模式下 28 个 `reportUnusedFunction` **全部**集中在带 `_` 前缀的 @impl 函数：

```
_action_impl.py:34   _action_resolved_action_id
_action_impl.py:42   _action_resolved_label
_dock_panel_impl.py:136  _dock_panel_init
...
```

而 `_view_impl.py` 中 `view_render`、`view_on_event` 等无 `_` 前缀的 @impl 函数 **零误报**。

## 设计方案

### R003 — @impl 函数命名规范

**规则**：`_*_impl.py` 文件中被 `@impl`（或 `@mutobj.impl`）装饰的函数不得以 `_` 开头。

**严重程度**：`warning`（命名约定优化，不影响运行时正确性）

**检测方式**：AST 静态分析，不 import 被检测模块。

**检测算法**：

1. 仅对文件名匹配 `_*_impl.py` 的文件执行（非 impl 文件中的 @impl 不报，如单文件 demo）
2. 解析文件顶部的 import 语句，识别 `impl` 的绑定名：
   - `from mutobj import impl` → 绑定名 `impl`
   - `import mutobj` → 绑定名 `mutobj`（此时 `@mutobj.impl(...)` 可识别）
   - `from mutobj import impl as foo` → 绑定名 `foo`
3. 遍历所有 `FunctionDef` / `AsyncFunctionDef`：
   - 若函数名以 `_` 开头
   - 且装饰器链中包含已识别的 `impl` 引用（`@impl(...)` 或 `@mutobj.impl(...)`）
   - → 报告 R003

**不检测**：
- 非 `@impl` 装饰的函数（它们用 `_` 前缀可能是合理的内部工具函数）
- 已被 `# pyright: ignore[reportUnusedFunction]` 注释的 `@impl` 函数（用户显式选择了 suppress）
- 非 `_*_impl.py` 文件

**import 解析**：复用 `_resolver.py` 中已有的 import 解析能力。文件名匹配 `_*_impl.py` 可内联一个简单的 `fnmatch` / `endswith` 判断。

### 命名约定更新

- `@impl` 函数**不使用** `_` 前缀。模块级 `_` 前缀（`_{stem}_impl.py`）已足够表达"内部实现"语义

```python
# ❌ 旧写法
@impl(View.render)
def _view_render(self, ...): ...

# ✅ 新写法
@impl(View.render)
def view_render(self, ...): ...
```

### 与现有规则的关系

| 规则 | 检测内容 | 严重度 | 状态 |
|------|---------|--------|------|
| R001 | 声明/实现风格混合 | error | ✅ 已完成 |
| R002 | 声明文件末尾 `_impl` import | warning | ✅ 已完成 |
| R003 | `@impl` 函数名 `_` 前缀（R003a） | warning | ✅ 已完成 |
| R003b | `@impl` 函数名含类型名前缀 | warning | 📝 设计中 |

## 测试策略

R003 测试沿用 `tests/test_lint/` 目录下现有分离文件模式（`test_r001.py` / `test_r002.py`）：通过 `_helpers.make_pkg()` + `_helpers.write()` 创建临时包结构，`lint_file()` / `lint_directory()` 后断言 `LintMessage` 列表。

关键测试场景：

| 场景 | 输入 | 预期 |
|------|------|------|
| `@impl` 函数无 `_` 前缀 | `def view_render(...)` | 无 R003 |
| `@impl` 函数有 `_` 前缀 | `def _view_render(...)` | R003 warning × 1 |
| 多函数混合 | `view_a` + `_view_b` + `_view_c` | R003 × 2 |
| 非 `@impl` 的 `_` 前缀函数 | `def _helper():`（无 @impl 装饰） | 无 R003 |
| `import mutobj` + `@mutobj.impl` | `@mutobj.impl(...)` / `def _foo(...)` | R003 warning × 1 |
| `from mutobj import impl as reg` | `@reg(...)` / `def _foo(...)` | R003 warning × 1 |
| 已有 `# pyright: ignore` | `@impl(...)` / `def _foo(...)  # pyright: ignore[reportUnusedFunction]` | 无 R003 |
| 非 `_*_impl.py` 文件 | `view.py` 中 `@impl` + `_` 前缀 | 无 R003（不检测） |
| `lint_directory` 批量扫描 | 目录含合规/违规 impl 文件 | 仅违规文件出 R003 |

测试文件：`tests/test_lint/test_r003.py`，沿用现有命名规范，新增测试类（如 `TestR003UnderscorePrefix`）。

## 设计方案（R003b — @impl 函数名缺少类型名前缀）

### 需求

`@impl` 函数是模块级函数，不绑定任何 class scope。当同一个 `_*_impl.py` 文件包含多个 Declaration 类型的实现时，纯方法名（`get`、`post`、`connect`）无法区分属于哪个类型。因此要求函数名以 `snake_case(类型名)` 为前缀。

```python
# ✅ 正确：函数名以 snake_case(类型名) 开头 — 类型信息清晰
@impl(View.get)
def view_get(self, ...): ...

@impl(WebSocketConnection.accept)
def ws_accept(self, ...): ...

@impl(JSONResponse.__init__)
def json_response_init(self, ...): ...

@impl(JSONResponse.__init__)
def json_response(self, ...): ...

# ❌ 错误：缺少类型名前缀 — 看不出属于哪个类型
@impl(MCPClient.connect)
def connect(self, ...): ...
```

### 设计原则

lint 的职责是检测"类型信息是否丢失"，而不是规定下划线怎么写。

- **检查**：函数名是否以 `snake_case(类型名)` 开头
- **不检查**：下划线有几个、方法名拼没拼、`__init__` 要不要写成 `_init`

`json_response_init` 和 `json_response___init__` 都保留了类型信息，写法差异属于风格偏好，不在 lint 管辖范围。`connect` 则完全丢失了类型信息，这才是 R003b 要抓的问题。

### 命名规则

**函数名必须以 `snake_case(类型名)` 开头**。接受两种形式：

- `startswith(snake_type + "_")` — 有后缀（如 `view_get`、`json_response_init`）
- 函数名**等于** `snake_type` — 无后缀（如 `@impl(JSONResponse.__init__)` / `def json_response(...)`）

不要求函数名等于特定完整字符串，不推算下划线数量。

CamelCase → snake_case 转换算法（Python 社区标准，零歧义）：

```python
import re

def _camel_to_snake(name: str) -> str:
    """在 小写→大写 和 大写→大写+小写（结尾缩略词） 处插入 _。"""
    s = re.sub(r'(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])', '_', name)
    return s.lower()
```

转换示例：

| 类型名 | snake_case |
|--------|------------|
| `MCPClient` | `mcp_client` |
| `JSONResponse` | `json_response` |
| `WebSocketConnection` | `web_socket_connection` |
| `View` | `view` |
| `HTTPServer` | `http_server` |
| `StaticView` | `static_view` |

### 唯一性保证

snake_case 是双射（不同 CamelCase 输入必然不同输出）。因此以 `snake_case(类型名)` 开头的函数名集合之间**不会重叠** — 两个不同类型的 @impl 函数不可能有相同的前缀要求。规则无二义。

### 检测算法

在 `check_r003` 函数中追加检测逻辑：

1. 对每个 `@impl` 装饰的函数，提取装饰器参数中的 Declaration 类型名
   - `@impl(View.get)` → 从 `View.get` 的 Attribute AST 节点提取 `View`
   - `@mutobj.impl(MCPClient.connect)` → 同理提取 `MCPClient`
2. 将类型名转 snake_case
3. 检查函数名是否以 `snake_type` 为前缀：
   - 函数名等于 `snake_type` → 通过
   - 函数名以 `snake_type + "_"` 开头 → 通过
   - 否则 → 报告 R003b

**与 R003a 的关系**：R003b 检测在 R003a 之后执行。先检查 `_` 前缀，再检查类型名前缀。实际实现可在同一 `check_r003` 函数内依次执行。

**装饰器参数 AST 解析**：

- `@impl(View.render)` → `decorator.args[0]` 是 `Attribute(value=Name("View"), attr="render")`
- 提取类型名：递归展开链式 `Attribute` 的 `value`，直到遇到 `Name`，取 `Name.id`
- 例如 `@impl(nested.Cls.method)` → 类型名取最后一节 `Cls`（跨包引用时完整路径无意义）

**实现注意事项**：

- 链式引用如 `nested.Cls.method`：类型名取最后一节（`Cls`）
- 非链式引用的参数（如函数调用 `get_target()`、变量 `TARGET`）跳过 R003b 检测，不报错
- 不处理 import 别名（如 `from .view import View as V` + `@impl(V.get)`）。此类写法不会出现在代码库中

### 不检测

- 非 `_*_impl.py` 文件（与 R003a 一致）
- 装饰器参数无法静态解析的情况（不是简单 `Name(.Name)*.attr` 链）

### 严重程度

`warning`。命名约定，不影响运行时正确性。

## 测试策略（R003b 追加）

R003b 测试追加到现有 `tests/test_lint/test_r003.py`，单独成类（如 `TestR003TypePrefix`）。

| 场景 | 输入 | 预期 |
|------|------|------|
| 函数名以类型前缀 + 后缀开头 | `@impl(View.get)` / `def view_get(...)` | 无 R003b |
| 函数名等于类型前缀（无后缀） | `@impl(JSONResponse.__init__)` / `def json_response(...)` | 无 R003b |
| 函数名等于类型前缀 + dunder 后缀 | `@impl(JSONResponse.__init__)` / `def json_response___init__(...)` | 无 R003b |
| 函数名等于类型前缀 + `_init` 后缀 | `@impl(JSONResponse.__init__)` / `def json_response_init(...)` | 无 R003b |
| 函数名缺少类型前缀 | `@impl(MCPClient.connect)` / `def connect(...)` | R003b warning × 1 |
| 多词类型名 + 正确前缀 | `@impl(WebSocketConnection.accept)` / `def web_socket_connection_accept(...)` | 无 R003b |
| 多词类型名 + 缩写前缀 | `@impl(WebSocketConnection.accept)` / `def ws_accept(...)` | R003b warning × 1 |
| `@mutobj.impl(...)` 形式 | `@mutobj.impl(Server.run)` / `def server_run(...)` | 无 R003b |
| 装饰器参数非简单点号 | `@impl(get_target())` / `def foo(...)` | 无 R003b（跳过） |
| 同一文件多类型混合 | `@impl(View.get)`→`view_get` ✅ + `@impl(MCPClient.connect)`→`connect` ❌ | R003b × 1 |
| R003a 违规同时 R003b 违规 | `@impl(View.get)` / `def _view_get(...)` | R003a + R003b 各 1 |
| 非 `_*_impl.py` 文件 | `server.py` 中 `@impl(View.get)` / `def view_get(...)` | 无 R003b（不检测） |
| 函数名以类型前缀开头但拼错 | `@impl(FileResponse.__init__)` / `def file_resp(...)` | R003b warning × 1 |

## 实施步骤清单

### R003a（已完成）

- [x] `_rules.py` — 新增 `check_r003` 函数
- [x] `_api.py` — `_lint_one` 中调用 `check_r003`（仅对 `_*_impl.py` 文件）；参数中传入 `source_lines` 用于 noqa 检测
- [x] `__main__.py` — CLI description 覆盖 R003
- [x] `tests/test_lint/test_r003.py` — 新增 R003 测试（按上表场景）
- [x] dogfooding：对 mutobj 自身跑 lint 确认零违规

### R003b（已完成）

- [x] `_rules.py` — `check_r003` 追加 `_camel_to_snake` 与前缀检测逻辑（`startswith`，非精确匹配）
- [x] `tests/test_lint/test_r003.py` — 新增 `TestR003TypePrefix` 测试类（14 个测试场景）
- [x] dogfooding：对 mutio 跑 lint 确认所有违规被检测到（MCPClient 10 个 + WebSocketConnection 6 个 + WebSocketView 1 个 + HTTPClient 2 个）
- [x] 修订 mutobj docs/guide.md：更新 `@impl` 命名约定（类型名前缀统一要求）

## 验收标准

### R003a

- mutgui 所有 `_*_impl.py` 中 `@impl` 函数的 `_` 前缀全部被检测到
- mutgui `_view_impl.py`（已合规）零误报
- mutobj 自身零违规
- 非 `_*_impl.py` 文件不被误报

### R003b

- mutio `mcp/_client_impl.py` 中 10 个缺失类型前缀的 @impl 函数全部被检测出 ✅
- mutio `net/_server_impl.py` 中 `ws_accept` 等 7 个用了缩写的 @impl 函数全部被检测出 ✅
- mutio `net/_server_impl.py` 中 `view_get`、`server_run`、`request_body`、`json_response_init`、`json_response_render` 等合规函数零误报 ✅
- mutio `net/_client_impl.py` 中 `set_default_user_agent`、`create` 2 个缺失前缀被检测出 ✅
- `def json_response(...)`（函数名等于 snake_type，无后缀）零误报 ✅
- 装饰器参数无法静态解析时跳过，不崩溃 ✅
- 非 `_*_impl.py` 文件不检测 ✅
