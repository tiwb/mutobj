# Declaration / Extension 子类桩方法的静态类型检查问题

**状态**：✅ 已修复（2026-04-23）
**日期**：2026-04-23
**类型**：功能设计（静态类型支持）

## 需求

### 问题现象

`mutobj.Declaration` 子类里用 `...` 作为方法桩，通过 `@impl` 装饰器在其他位置提供实现。运行时工作正常，但 Pyright（Pylance）无法识别这些方法，对**每一处调用**都报：

```
Cannot access attribute "<method>" for class "Declaration"
Attribute "<method>" is unknown [reportAttributeAccessIssue]
```

同样的模式也出现在 `mutobj.Extension` 子类：子类扩展字段 `_channels`、`_viewports` 等虽然在子类上定义，但被识别为 `Extension[T]` 基类上的未知属性，所有跨文件访问都被标红。

### 具体案例

`mutbot/cli/pysandbox.py` 使用 `MCPClient`（`mutio.mcp.client` 定义的 Declaration 子类）连接 MCP endpoint：

```python
class MCPClient(mutobj.Declaration):
    url: str = ""
    async def connect(self) -> None: ...
    async def call_tool(self, name: str, **arguments: Any) -> dict[str, Any]: ...
    async def close(self) -> None: ...

client = MCPClient(url=url)
await client.connect()          # ← Pyright 报 reportAttributeAccessIssue
await client.call_tool(...)     # ← 同上
await client.close()            # ← 同上
```

Extension 子类类似：

```python
class SessionChannels(mutobj.Extension[Session]):
    _channels: list[str] = mutobj.field(default_factory=list)

ext = SessionChannels.get_or_create(session)
ext._channels.append(name)      # ← Pyright 报 reportAttributeAccessIssue
                                #   Cannot access attribute "_channels" for class "Extension[Session]"
```

### 根本原因（已验证）

通过最小复现工程（`mutobj/tests/type_check/fixtures/`）+ pyright CLI 验证，根因**集中在三处构造器/工厂方法的返回类型标注**：所有都硬编码成基类，而非 `Self`。

```python
# mutobj/src/mutobj/core.py（修复前）

class Declaration(metaclass=DeclarationMeta):
    def __new__(cls, *args: Any, **kwargs: Any) -> Declaration:   # ← 应为 Self
        ...

class Extension(Generic[T]):
    @classmethod
    def get_or_create(cls, instance: T) -> Extension[T]:          # ← 应为 Self
        ...

    @classmethod
    def get(cls, instance: T) -> Extension[T] | None:             # ← 应为 Self | None
        ...
```

Pyright 看到显式返回类型就直接用它作为表达式的结果类型：

- `MCPClient(url="...")` 被推断为 `Declaration`（不是 `MCPClient`）
- `SessionChannels.get_or_create(s)` 被推断为 `Extension[Session]`（不是 `SessionChannels`）

所以子类上声明的方法和字段都被视为"基类不存在的属性"。

**原先的假设被证伪**：文档早期版本推测是 `async def foo(self) -> T: ...` 写法导致 Pyright 把方法识别为属性。通过 fixture 验证，`...` / `pass` / `raise NotImplementedError` **三种写法 Pyright 的识别行为完全一致**，问题与方法体形态无关，仅与实例类型推断有关。

关键证据（`reveal_type` 输出）：
- 修复前：`Type of "client" is "Declaration"`
- 修复后：`Type of "client" is "MCPClient"`，且所有桩方法被识别为正确签名

### `Extension[T]` vs `Self` 的语义差异

`Extension[T]` 中 `T` 绑定到 Declaration 类型参数（例如 `Session`），即使 `T` 正确绑定，得到的也是"**被 Session 参数化的 Extension 基类**"，不会反向推断到具体子类 `SessionChannels`。Python 的泛型不走这个方向。

`Self`（PEP 673）是专门描述"当前调用所属的那个类"的类型，classmethod / 构造器用它后，通过子类调用时自动绑定到子类本身。**构造器和工厂方法永远应该用 `Self`，不是写死基类**。

### 影响范围

所有 `Declaration` / `Extension` 子类的调用点：

- `mutobj/src/mutobj/core.py` — 基础设施
- `mutio/src/mutio/` — `MCPClient`、Server/Request 等 Extension 体系
- `mutagent/src/mutagent/sandbox/app.py` — `SandboxApp`
- `mutbot/src/mutbot/` — `SessionChannels`、`ChannelTransport` 等 Extension
- `mutgui/src/mutgui/` — `ViewObservers`、`ViewRenderState`、`ViewPortRuntime` 等 Extension
- 所有下游用户代码（每次调用都中招）

## 修复方案

三处单行改动，全部在 `mutobj/src/mutobj/core.py`：

```python
from typing import Self   # 新增

class Declaration(metaclass=DeclarationMeta):
    def __new__(cls, *args: Any, **kwargs: Any) -> Self:        # Declaration → Self
        ...

class Extension(Generic[T]):
    @classmethod
    def get_or_create(cls, instance: T) -> Self:                # Extension[T] → Self
        ...

    @classmethod
    def get(cls, instance: T) -> Self | None:                   # Extension[T] | None → Self | None
        ...
```

附带清理：`core.py:744` 的 `cls in _attribute_registry` 触发 metaclass 场景下的 `reportUnnecessaryContains` 误判，加逐行 `# pyright: ignore`，与文件里既有的 616、693 等处的 metaclass 相关抑制风格一致。

### 运行时影响

**零影响**。`Self` 只是给静态检查器看的注解，运行时等价于无注解。修复纯粹改变 pyright 的视角。

### 下游连锁收益

不改下游任何代码，静态错误数变化：

| 项目 | Extension attr-access 错误 | 总错误数 |
|---|---:|---:|
| mutobj | — | 1 → **0** |
| mutio | 14 → **0** | 14 → **0** |
| mutbot | 31 → **0** | 33 → 2（剩余均与 Extension 无关：JWT 库 + psutil stub） |
| mutgui | 14 → **1** | 剩下的 1 个是独立的 `_view_block` 动态赋值问题 |

mutgui 的 `reportPrivateUsage` 在 strict 模式下仍有 77 条，那是 Extension `_xxx` 字段命名习惯的独立问题，不在本次修复范围内。

## 验证方式

在 `mutobj/tests/type_check/` 下建立 pyright 回归测试：

- **fixtures**：采用标准 mutobj 用法，每个 fixture 必须被 pyright **零诊断**通过
  - `01_repro.py` — Declaration 子类：构造、实例化、方法调用
  - `02_extension.py` — Extension 子类：`get_or_create`、`get`、字段访问
  - fixture 字段名用公开命名（不带 `_` 前缀），与 `reportPrivateUsage` 规则无关，在 mutobj 的 strict 配置下也能干净通过

- **runner**：`test_pyright.py` — 调用 `pyright --outputjson`，解析结果，断言 `errorCount == 0 and warningCount == 0`；pyright 未安装时 `pytest.mark.skipif` 自动跳过

手工验证过反向场景：把 `-> Self` 改回基类 → 测试立即失败并列出全部回归诊断；恢复 → 通过。

## 关键参考

- 修复位置：`mutobj/src/mutobj/core.py` — `Declaration.__new__`、`Extension.get_or_create`、`Extension.get`
- 回归测试：`mutobj/tests/type_check/test_pyright.py`
- Fixtures：`mutobj/tests/type_check/fixtures/01_repro.py`、`02_extension.py`
- PEP 673 — Self Type: https://peps.python.org/pep-0673/

## 后续工作（已登记，非本次范围）

1. **Extension `_xxx` 字段命名**：在 `refactor-extension-setattr.md`（2026-04-21）去掉 `__setattr__` 代理后，`_` 前缀的语义依据已消失，但字段命名未同步重命名。mutgui strict 模式下仍有 77 条 `reportPrivateUsage`。可选做法是把 Extension 字段重命名为公开名（无 `_` 前缀），让 mutgui 恢复 strict 干净。工作量约 30+ 字段、若干访问点。
2. **下游清理 `# type: ignore[attr-defined]` 压制**：mutbot、mutio 等有个位数的遗留 ignore（为了绕原先 `Extension.get_or_create` 返回基类），现在可以删除。
3. **mutgui strict 模式其他噪音**（~110 条 `reportUnknown*Type` 等）：与 mutobj 元编程机制（`@impl` 注入、setattr 动态字段）的静态建模有关，需要单独 SDD 规范讨论 typing 路径。
