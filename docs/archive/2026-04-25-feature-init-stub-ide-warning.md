# Declaration `__init__` 声明桩 — IDE 警告与构造模式 设计规范

**状态**：✅ 已完成
**日期**：2026-04-25
**类型**：功能设计 / 规范讨论

## 背景

mutobj 的 Declaration 子类经常需要在声明文件里给出构造签名（接口契约），实现放到 `_impl.py` 里通过 `@mutobj.impl(Cls.__init__)` 提供。典型例子见 `mutio/src/mutio/net/server.py`：

```python
class JSONResponse(Response):
    def __init__(self, content: Any, status_code: int = 200) -> None: ...

class FileResponse(Response):
    def __init__(
        self,
        path: str | Path,
        *,
        status_code: int = 200,
        media_type: str | None = None,
        cache_control: str | None = None,
        filename: str | None = None,
        content_disposition_type: str = "attachment",
    ) -> None: ...
```

实现位于 `_server_impl.py`：

```python
@mutobj.impl(JSONResponse.__init__)
def _json_response_init(self, content, status_code=200):
    Response.__init__(self, ..., body=self.render(content), headers=...)
```

## 问题

声明桩里的 `def __init__(self, ...) -> None: ...` 触发 IDE 警告：

- **pyright**: `reportMissingSuperCall`
- **pylint**: `W0231 super-init-not-called`

警告本质正确（子类重定义了 `__init__` 但没调 super），但在 mutobj 的范式下：

1. 桩函数体是 `...`，不是真正的实现，调不调 super 都没意义
2. 实际实现在 `@impl` 函数里手动调用 `Response.__init__(self, ...)`，已经处理了构造链
3. 用户每次写 `__init__` 桩都被警告污染，体验差，也容易让 agent/新手以为这是反模式

更深层的问题：**mutobj 缺少"声明阶段执行复杂构造逻辑"的官方落点**。当前唯一选择就是声明 `__init__` 桩 + `@impl` 实现，但 `__init__` 是 Python 协议钩子，IDE 对它有强约束（必须 super）。

## 现状分析

### 何时需要声明 `__init__`

不是所有 Declaration 子类都需要。两种典型场景：

**场景 A — 简单属性赋值**（不需要 `__init__`）

```python
class Request(mutobj.Declaration):
    method: str = "GET"
    path: str = "/"
    headers: dict[str, str] = mutobj.field(default_factory=dict)
```

调用：`Request(method="POST", path="/api")`。mutobj 的 `Declaration.__init__` 自动把 kwargs setattr 上去。无需用户写 `__init__`，无 IDE 警告。

**场景 B — 构造时需要计算 / 转换**（当前必须用 `__init__`）

`JSONResponse(content)` 需要把 content 序列化成 body、自动设 content-type header；`FileResponse(path)` 需要读文件、推断 mime、设 cache-control。这些不是简单赋值能完成的。

当前只能写 `__init__` 桩 + `@impl`，IDE 警告无法避免。

### 解决思路（待讨论）

下面列出几个方向，**不预设结论**，留待后续单独讨论。

#### 方案 A：声明桩加 `# pyright: ignore[reportMissingSuperCall]`

最便宜，零设计成本。但：
- 把 mutobj 内部约束泄漏到所有用户代码
- agent / 新手会忘加，警告反复出现
- 不解决"`__init__` 是个尴尬的协议钩子"这个根本问题

#### 方案 B：mutobj 提供 `@mutobj.constructor` 装饰器

```python
class JSONResponse(Response):
    @mutobj.constructor
    def __init__(self, content: Any, status_code: int = 200) -> None: ...
```

装饰器内部生成一个调用了 `super().__init__()` 的桩函数体，骗过 IDE。但用户写桩时仍然要记得加装饰器，且语义上仍然是 `__init__`，没有摆脱协议钩子的束缚。

#### 方案 C：DeclarationMeta 自动注入合法桩

`DeclarationMeta.__new__` 检测到 `__init__` 桩函数体是 `...`（或被 `@mutobj.impl` 注册过），自动替换成 `lambda self, *a, **kw: super().__init__(*a, **kw)` 风格的桩。完全无感，用户照常写 `def __init__(self, x) -> None: ...`，元类悄悄把它替换为合法的实现。

风险：
- 需要识别"这是声明桩"而不是"用户的真实实现"
- 与 `@mutobj.impl(Cls.__init__)` 注册时机的相互作用

#### 方案 D：约定不在 Declaration 子类里声明 `__init__`，改用 classmethod 工厂

```python
class JSONResponse(Response):
    @classmethod
    def create(cls, content: Any, status_code: int = 200) -> JSONResponse: ...
```

调用变成 `JSONResponse.create(content)`，破坏性极大（用户调用方式全变），且不符合 Python 直觉。**不推荐**。

#### 方案 E：引入 `__post_init__`（dataclass 风格）

`Declaration.__init__` 在末尾自动调用 `self.__post_init__()`（如果定义了）。复杂构造逻辑落在 `__post_init__` 里，不再需要声明 `__init__` 桩。

```python
class JSONResponse(Response):
    content: Any  # 属性声明

    def __post_init__(self) -> None: ...

@mutobj.impl(JSONResponse.__post_init__)
def _(self):
    self.body = json.dumps(self.content, ensure_ascii=False).encode("utf-8")
    self.headers["content-type"] = "application/json; charset=utf-8"
```

调用：`JSONResponse(content={"x": 1}, status_code=201)`。

优点：
- 完全符合 mutobj "声明优先" 哲学
- IDE 不会对 `__post_init__` 报 super 警告
- dataclass 用户已经熟悉这个模式
- 让"复杂构造"有官方落点

缺点：
- 需要修改 `Declaration.__init__` 行为（新增钩子调用）
- 现有所有声明 `__init__` 的 Declaration 子类需要重构（mutio Response 系列、可能还有 mutagent / mutbot 内部）
- 某些场景（位置参数语义、参数转换）仍然需要 `__init__` —— 例如 `JSONResponse(content)` 把 content 作为位置参数，`__post_init__` 模式下要么必须传 kwarg，要么需要额外设计

#### 方案 F：组合方案 — `__post_init__` + 桩注入

E 处理简单的"设默认 + 后处理"场景；C 处理仍然需要自定义构造签名（特别是位置参数）的场景。两者并存，让用户按需选择。

## 选定方案

经讨论确定走 **方案 E（`__post_init__`）** 路线，并借此机会把 `mutobj.field` 与 dataclass 的 API 语义对齐，为后续接入 `@dataclass_transform` 打基础。

设计判断：
- **不直接复用 `dataclasses.field`**：`mutobj.field` 未来要扩展 mutobj 专属能力（如 `impl_key`、reload 策略），混用会导致用户认知分裂、IDE 推断不一致、内部实现要双分支。但**签名/语义 100% 对齐 dataclass**，让熟悉 dataclass 的人零成本上手。
- **`__post_init__` 是新代码的官方"复杂构造"落点**，现有 `__init__` 桩代码不强制迁移（向后兼容）。
- **位置参数支持（`JSONResponse(content)`）暂不引入**，需要 `InitVar` 配合，单独立项（见"延后项"）。

### 本次实施范围

**1. `Declaration.__init__` 自动调用 `__post_init__`**

如果子类声明了 `__post_init__`（即在类定义里出现 `def __post_init__(self) -> None: ...`），`Declaration.__init__` 在完成默认值/kwargs 处理后自动调用 `self.__post_init__()`。

`__post_init__` 是普通声明方法，通过 `@mutobj.impl(Cls.__post_init__)` 提供实现：

```python
class JSONResponse(Response):
    content: Any  # 简单字段声明

    def __post_init__(self) -> None: ...

@mutobj.impl(JSONResponse.__post_init__)
def _(self):
    self.body = json.dumps(self.content, ensure_ascii=False).encode("utf-8")
    self.headers["content-type"] = "application/json; charset=utf-8"
```

调用方式：`JSONResponse(content={"x": 1}, status_code=201)`，或对 `init=True` 字段继续使用现有位置参数绑定。

**2. `mutobj.field` 新增 `init` 参数**

```python
def field(
    *,
    default: Any = MISSING,
    default_factory: Callable[[], Any] | None = None,
    init: bool = True,           # 新增
) -> Any: ...
```

- `init=True`（默认）：字段参与现有构造参数绑定（关键字参数 + 当前位置参数映射），行为与现状一致。
- `init=False`：字段不参与构造参数绑定，构造时仅按 `default` / `default_factory` 初始化；典型用途是 `__post_init__` 算出的派生字段。

`Field` 类同步加 `init` 字段到 `__slots__`。`Declaration.__init__` 会在位置/关键字参数绑定阶段统一跳过 `init=False` 字段；关键字显式传入时抛 `TypeError`（与 dataclass 一致）。

**3. 公开 `MISSING` 哨兵**

把现有私有 `_MISSING` 公开导出为 `mutobj.MISSING`，加入 `__all__`。语义和 `dataclasses.MISSING` 一致，用户可写 `if value is mutobj.MISSING`。

### 本次明确不做（延后项）

延后是为了控制本轮变更的复杂度和影响范围，不代表否决。

| 延后项 | 说明 | 触发条件 |
|--------|------|----------|
| **`field()` 其他对齐参数**（`kw_only` / `repr` / `compare` / `hash` / `metadata`） | 当前 `Declaration.__init__` 已支持位置参数和 kwargs，但还没有自动 `__repr__` / `__eq__` 生成，这些参数现在加上也是空占位。等真要做相应能力时一起加，仍然兼容（kwargs 加可选参数不破坏 API）。 | 引入自动 `__repr__`/`__eq__` 生成 |
| **`InitVar` 支持** | 解决"原料字段不存为属性"的优雅写法，并让 `__post_init__` 能区分持久字段与仅构造期输入。需要改 `__init__` 参数绑定逻辑（区分字段/InitVar），影响面较大。 | 用户对"构造期输入但不落属性"有明确诉求 |
| **`@dataclass_transform` 装饰** | PEP 681，让 IDE 自动推断 Declaration 子类的 `__init__` 签名、必填/选填、字段顺序。运行时无操作，但启用后会暴露现有代码中"字段顺序违反 dataclass 规则""手写 `__init__`"等问题，需要先扫描影响范围。 | 本次 `field`/`__post_init__` 落地后单独立项 |
| **现有 `__init__` 桩代码迁移** | mutio Response 系列（5 处）等；运行时不强制，但建议新代码用 `__post_init__`。 | 可作为单独的清理任务推进 |

### 影响范围

- **`mutobj/src/mutobj/core.py`**：
  - `Field` 加 `init` 字段
  - `field()` 加 `init` 参数
  - `Declaration.__init__` 末尾自动调 `__post_init__`（如有声明）
  - 构造参数绑定逻辑：`init=False` 字段不参与位置/关键字参数绑定
  - `__all__` 加 `MISSING`
  - `_MISSING` 别名为 `MISSING`（保留 `_MISSING` 内部用法，避免同时改太多内部引用）
- **测试**：补 `__post_init__` 自动调用、`init=False` 构造约束、`MISSING` 公开导出等测试。
- **文档**：在 mutobj README / Declaration 章节增加 `__post_init__` 用法示例。

### 决策点（已回答）

1. ~~是否接受"声明 `__init__` 是反模式"这个判断？~~ → **不强制反模式**，但提供 `__post_init__` 作为推荐替代。
2. ~~如果引入 `__post_init__`，是否同时保留 `__init__` 桩机制（向后兼容）？~~ → **保留**，新旧共存。
3. ~~位置参数构造是 mutobj 该支持的能力吗？~~ → **延后**，等 `InitVar` 一起做。
4. ~~短期止血和长期治本是否分阶段推进？~~ → **直接做 E 的最小集**，不走 A。

## 状态

实现已完成，`__post_init__` / `field(init=False)` / `MISSING` 已落地并完成回归。

## 实施步骤清单

### 准备

- [x] 关键参考补充：阅读 `mutobj/src/mutobj/core.py:90-120`（Field/field）、`core.py:795-841`（Declaration.__new__/__init__）、`core.py:480-560`（DeclarationMeta 处理 Field 的 4 处 `isinstance` 检查），确认改动落点
- [x] 补充观察：`Declaration.__init__` 已支持位置参数（`core.py:820-841` 走 `_get_ordered_fields` 映射），不是纯 kwargs。这不影响本次实施，但需在文档"延后项"修正措辞（避免后续被误读为"位置参数完全没做"）

### 核心改动（`mutobj/src/mutobj/core.py`）

- [x] 公开 `MISSING` 哨兵：把 `_MISSING` 别名为 `MISSING`，加入 `__all__`（保留 `_MISSING` 内部引用不动，避免连带改动）
- [x] `Field` 类加 `init` 字段：扩展 `__slots__`，`__init__` 接受 `init: bool = True` 参数
- [x] `field()` 函数加 `init` 参数：默认 `True`，透传给 `Field`
- [x] `AttributeDescriptor` 同步存储 `init` 信息：`Field` 提取流程（`core.py:488` / `core.py:539` / `core.py:747`）把 `init` 透传到描述符
- [x] `Declaration.__init__` 处理 `init=False` 字段：构造参数绑定阶段跳过这些字段；关键字传入时报 `TypeError`，位置参数计数也按 `init=True` 字段收紧
- [x] `Declaration.__init__` 末尾自动调 `__post_init__`：在 kwargs 处理完成后，如果 `type(self)` 有 `__post_init__` 方法（包括从 MRO 继承的），调用 `self.__post_init__()`
- [x] 确认 `__post_init__` 走 mutobj 标准声明-实现机制：作为普通声明方法被 `_DECLARED_METHODS` 收录、可被 `@mutobj.impl(Cls.__post_init__)` 注册实现；不需要在 `_MUTOBJ_RESERVED_DUNDERS` 黑名单里加任何条目

### 测试（`mutobj/tests/`）

- [x] 测试 `__post_init__` 自动调用：声明带 `__post_init__` 的子类，`@impl` 提供实现，构造实例后断言副作用生效
- [x] 测试 `__post_init__` 未声明时不调用：未声明 `__post_init__` 的子类构造正常，无 AttributeError
- [x] 测试 `__post_init__` 在 kwargs 处理完成后才调用：在 `__post_init__` 实现里读取 kwargs 设置的字段值，确认能读到（验证调用顺序）
- [x] 测试 `field(init=False)` 拒绝 kwarg：构造时传该字段对应的 kwarg 应抛 `TypeError`
- [x] 测试 `field(init=False)` 仍走默认值/工厂：构造不传 kwarg 时，字段被默认值/工厂初始化
- [x] 测试 `field(init=False)` + `__post_init__` 联动：派生字段在 `__post_init__` 里赋值，构造完成后能读到正确值
- [x] 测试 `mutobj.MISSING` 公开导出：`from mutobj import MISSING`，断言 `MISSING is mutobj.MISSING`
- [x] 回归测试：跑全部 `pytest`，确认现有测试无破坏

### 文档

- [x] 更新 `mutobj/README.md`：在 Declaration 章节加 `__post_init__` 用法示例和 `field(init=False)` 用法示例
- [x] 在本文档"延后项"小节修正措辞：明确当前 `__init__` 已支持位置参数，未来 `InitVar` 是为"原料字段不存为属性"而非"引入位置参数"
- [x] 实施完成后，更新本文档头部状态为 ✅ 已完成

### 验收

- [x] mutobj 全量测试通过
- [x] 上层项目（mutio / mutagent / mutbot）安装新版 mutobj 后跑各自测试套件，确认无回归
- [x] 在 mutio 的 `JSONResponse` 上做一次小型 POC（不合并）：用 `__post_init__` 重写一个 Response 子类，确认 IDE（pyright）不再报 `reportMissingSuperCall`

## 测试验证

- `pytest`（mutobj）— `238 passed`
- `pytest`（mutio）— `138 passed`
- `pytest`（mutagent）— `771 passed, 5 skipped`
- `pytest`（mutbot）— `594 passed`
- 临时 `mutio` POC：`pyright` 对 `Response` 子类的 `__post_init__` 写法返回 `0 errors`
- `mypy src/mutobj` 仍有 `src/mutobj/core.py` 里的既有基线错误，本次未扩大范围处理
