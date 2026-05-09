# 类级单例属性支持 设计规范

**状态**：✅ 已完成（已补齐字符串别名 / t.ClassVar / 跨模块继承 / reload 兼容性）
**日期**：2026-05-09
**类型**：功能设计

## 需求

下游项目（mutagent / mutbot）反复在 `Declaration` 子类上写"类级单例属性"
（启动期注入的全局引用，如 `_app`、`_sandbox_app`），但 mutobj 当前没有
明确的 API 表达这种语义，导致开发者用错写法、写出能跑但语义错位的代码，
且通过现有文档无法定位正解。

具体踩坑案例（来自
`mutagent/docs/specifications/feature-pysandbox-namespace-sharing.md` 步骤 6）：

```python
class MutBotMCP(MCPView):                          # MCPView → View → Declaration
    _sandbox_app: "SandboxApp | None" = None      # 开发者意图：类级单例
                                                   # 实际效果：被包成 AttributeDescriptor（每实例字段）

# _on_startup 末尾
MutBotMCP._sandbox_app = sandbox_app                # 实际是"重建描述符 + 改 default"
```

行为对照（实测确认）：

| 写法 | `Cls.x` 类级读 | `inst.x` 实例读 | `Cls.x = v` 后果 |
|------|---------------|-----------------|-----------------|
| `x: T = None`（mutobj 字段） | 返回 `AttributeDescriptor` 对象（**不是值**！） | 返回该实例的 `_mutobj_attr_x` | 重建描述符；**仅影响赋值后新建的实例**，老实例不变 |
| `x = None`（无注解） | 返回值 | 走类属性回落，返回值 | **所有未在自己 `__dict__` 写过 `x` 的实例（新老都算）立刻看到新值** |
| `x: ClassVar[T] = None` | 返回 `AttributeDescriptor`（**当前不识别 ClassVar**） | 同字段 | 同字段 |

`MutBotMCP` 工作"运气好"的两个前提：
1. ASGI 每个请求新建 `MutBotMCP` 实例 → 总是赶在 `_on_startup` 完成赋值之后构造，
   正好读到新 default。
2. 没人去 `print(MutBotMCP._sandbox_app)` 调试 —— 一打印就拿到一个描述符对象，
   懵掉的瞬间就是步骤 6 描述的"小坑"。

语义上开发者真正想要的是 **类级单例**，但写出来的是 **每实例字段**。当前能跑只是巧合。

### 为什么开发者反复掉坑（根因分析）

1. **`docs/guide.md:74` 把答案藏在括号里**：「类型注解决定字段身份（无注解的等号
   赋值不算字段，按类属性处理）」是字段声明小节的一条 bullet，没有任何"如果你需要
   类级单例怎么写"的反向引导。开发者顺着文档读下去只会被"字段必须类型注解"训练成
   肌肉记忆。

2. **`docs/api/reference.md` 完全没提**类级属性这一条目。AI 读文档照搬只会写出
   `_x: T = None`。

3. **mutobj 不识别 `typing.ClassVar`**。`x: ClassVar[int] = 5` 仍被包成
   `AttributeDescriptor`。这是和 `dataclass` 的明显语义偏离——凡有 dataclass
   经验的开发者都会先尝试 `ClassVar`，发现"看起来没报错"就当成已生效，错觉一旦
   形成就再难纠正。

4. **下游仓内已有错误范例**：`mutagent/sandbox/entry_mcp.py` 的
   `PySandboxTools._app: SandboxApp | None = None` 用了同样的错写法，
   `feature-pysandbox-namespace-sharing.md` 步骤 6 还明确写"与现存 `PySandboxTools._app`
   同模式"——**最近的参照是错的**。

5. **静默 + 巧合可工作**：`DeclarationMeta.__setattr__` 兢兢业业地把类级赋值
   翻译成"重建描述符 + 改 default"，让错误用法在 ASGI per-request 的特定时序下
   能跑通；既不报错也不警告，开发者收到的是 false positive 反馈。

## 关键参考

- `src/mutobj/core.py:273` — `AttributeDescriptor`，`__get__` 在 `obj is None`
  时返回 `self`（描述符对象），导致 `Cls.x` 类级读拿到描述符而非值
- `src/mutobj/core.py:530` — `DeclarationMeta.__new__` 处理 `annotations.items()`，
  无视 `ClassVar` 包装，统一创建描述符
- `src/mutobj/core.py:575` — 无注解且以 `_` 开头的类属性，metaclass 直接
  `continue`，零干预（**这就是当前唯一能写出类级单例的写法**）
- `src/mutobj/core.py:790` — `DeclarationMeta.__setattr__`，类级赋值时重建描述符
  default 的实现（运行时 hot-swap default 的能力来源）
- `docs/guide.md:74` — 唯一一处提到"无注解的等号赋值不算字段"，藏在 bullet 中
- `docs/api/reference.md` — 完全未提类级属性
- `mutagent/docs/specifications/feature-pysandbox-namespace-sharing.md` 步骤 6 —
  原始踩坑现场，括注「遇到 mutobj `AttributeDescriptor` 小坑」
- `mutagent/src/mutagent/sandbox/entry_mcp.py:20` — `PySandboxTools._app`
  错误范例
- `mutbot/src/mutbot/web/mcp.py:33` — `MutBotMCP._sandbox_app` 错误范例
- `tests/test_class_setattr.py` — 现有运行时类级赋值测试，覆盖描述符 default 重建路径

## 设计方案

总体思路：**多管齐下，让"类级单例"这条路在 mutobj 里有一等公民的表达方式，
并堵死开发者错写时的"无声通过"路径**。

### 方案 A：支持 `typing.ClassVar`（核心方案）

在 `DeclarationMeta.__new__` 处理 `annotations.items()` 时识别 `ClassVar` 包装，
**跳过描述符创建**，将其作为普通 Python 类属性处理。这是 dataclass / attrs 早就
建立的标准约定，对齐之后开发者可以写：

```python
from typing import ClassVar

class MutBotMCP(MCPView):
    _sandbox_app: ClassVar["SandboxApp | None"] = None     # IDE / mypy / pyright 完美兼容
```

**实现要点**：

- 用 `typing.get_type_hints(cls, include_extras=True)` 解析延迟注解？**不**，
  会触发用户类的全部 forward-ref 解析，副作用太大且对未导入符号会抛异常
- 用 `typing.get_origin(ann) is ClassVar`？只对**已 evaluated** 的注解有效
- mutobj 类属性的注解大量以**字符串形态**存在（`from __future__ import annotations`
  / 显式字符串 `"SandboxApp | None"`），需要做轻量字符串解析：
  - 识别 `ClassVar`、`ClassVar[...]`、`typing.ClassVar`、`typing.ClassVar[...]`、
    `t.ClassVar`、以及通过 `from typing import ClassVar as CV; CV[...]` 这类别名
  - 别名识别需要查 `cls.__module__` 的 `globals()` —— 失败时退化为字符串前缀匹配
- 已 evaluated 的注解走 `typing.get_origin` 快路径
- 跳过描述符创建后，该字段**不进 `_attribute_registry`**，不参与 `__init__` 字段绑定，
  不参与 `__new__` 的默认值应用
- 子类覆盖父类 `ClassVar` 字段：父类是 `ClassVar` → 子类同名也按 `ClassVar`
  处理（即使子类没重复 `ClassVar` 标注），避免子类悄悄"降级"为字段

**风险与边界**：

- 字符串注解解析有边界 case（如 `Annotated[ClassVar[X], ...]`、自定义包装等），
  v1 只覆盖直接的 `ClassVar` / `ClassVar[...]`，复杂嵌套不支持，遇到时按"字段"
  处理（保持当前行为，不破坏现状）
- `ClassVar` 字段不支持 `field(default_factory=...)`：如果用户写
  `_x: ClassVar[list] = field(default_factory=list)`，应在类创建时直接 `TypeError`，
  引导其要么用 `Declaration` 字段，要么用模块级常量

### 方案 B：guide.md 补一节「类级单例属性 vs 实例字段」（必做）

在 `docs/guide.md` 字段声明章节之后新增独立小节，**正反对照**：

- 给出"需求示例"：`_app` / `_sandbox_app` 这类启动期注入的全局引用
- 给出三种写法的对照表（即本文档"需求"章节的那张表）
- 明确推荐：**优先用 `ClassVar`**（方案 A 落地后），**fallback 用无注解 `_x = None`**
  （方案 A 未落地时）
- 反例：`_x: T = None` + `Cls._x = v` 看似工作但实际是"每实例字段 + 描述符
  default 重建"，老实例不更新、类级读拿到描述符对象

同时在 `docs/api/reference.md` 顶部加一条索引：「Class-level singleton attributes
→ guide.md」。

### 方案 C：开发期可观测性（可选）

在 `DeclarationMeta.__setattr__` 命中 AttributeDescriptor 重建路径时，如果检测到
**对已有非 MISSING default 的二次赋值**（典型的"我以为是类级单例"用法），输出
DEBUG 级 logger 提示：

```
mutobj.declaration: rebuilding AttributeDescriptor default on
  {cls.__name__}.{name}; if you intend a class-level singleton,
  declare with ClassVar or drop the annotation.
```

- 默认 silent（不打扰）
- 开发模式（环境变量 `MUTOBJ_DEBUG=1` 或 logger 配置 DEBUG）下自动显形
- 只是提示，不改变任何行为，不破坏向后兼容

### 方案 D：Mutobj 仓自身不直接动 mutbot/mutagent 代码

mutbot 的 `MutBotMCP._sandbox_app` 和 mutagent 的 `PySandboxTools._app` 是下游
错误范例。**本规范不直接修这两处**（mutobj 仓不应跨项目改代码），但要：

- 在 guide.md 新章节里**点名引用**这两个真实场景作为示例（"启动期注入的全局引用，
  典型如 mutagent 的 `PySandboxTools._app` / mutbot 的 `MutBotMCP._sandbox_app`"），
  让下游 maintainer 阅读时能立刻对号入座
- 在本文档「消费者场景」表中明确"下游需要做什么"，作为下游修复的 trigger

下游修正动作（由 mutbot / mutagent 各自项目独立排期，不在本规范实施清单内）：
两处都改成 `ClassVar` 写法（方案 A 落地后）或无注解 `_x = None`（方案 A 未落地时），
并加 inline comment 链接到 guide.md 新章节。

### 方案 E：跨项目经验回流约定（流程改进）

在 mutobj 的 `CONTRIBUTING.md` 或工作区根的 `AGENTS.md`（视维护者偏好）加一条
协作约定：

> 跨项目实施时，下游 spec 中提到的"上游小坑"必须同步成上游（mutobj）文档或
> postmortem 的一条改动，否则该 spec 不算完成。

具体落地由维护者决定，本规范只描述意图。

## 待定问题

（全部已决议，无待定项）

- **Q1**: 方案 A 落地，作为当前迭代的 minor feature。
- **Q2**: guide.md 新章节标题用「`ClassVar`：类级单例属性」（方案 A 落地后直接突出 ClassVar）。
- **Q3**: 不做（方案 A+B 落地后错误写法路径已被打断；hot-swap default 正确场景不应被误伤）。
- **Q4**: 方案 E 暂不实施，先补齐核心机制观察一段时间。

## 实施步骤清单

- [x] 方案 A：`DeclarationMeta.__new__` 支持 `ClassVar` 识别与跳过描述符创建
- [x] 方案 A 测试：覆盖 `ClassVar` 各种写法变体（直接注解、字符串注解、别名、`t.ClassVar`、跨模块继承、reload）
- [x] 方案 B：`docs/guide.md` 新增「`ClassVar`：类级单例属性」章节
- [x] 方案 B：`docs/api/reference.md` 顶部增加索引条目
- [x] 全量测试回归

## 消费者场景

| 消费者 | 场景 | 依赖的输出 | 验收标准 |
|--------|------|-----------|---------|
| mutagent maintainer | 修正 `PySandboxTools._app` 错误范例 | guide.md 新章节 + `ClassVar` 支持 | 改写后 `Cls._app` 类级读返回值（不是描述符）；老实例和新实例都看到最新值 |
| mutbot maintainer | 修正 `MutBotMCP._sandbox_app` 错误范例 | 同上 | 同上 |
| 未来下游开发者 | 在 Declaration 子类上声明启动期注入的全局引用 | guide.md 新章节 | 第一次搜索"class-level"/"singleton"/"ClassVar" 即可找到正解，不再需要踩坑后由 reviewer 指出 |
| AI 协作者（Claude / pi 等） | 阅读 mutobj 文档生成代码 | api/reference.md 索引 + guide.md 章节 | 在不读源码的前提下，能正确写出类级单例属性，不复制 `PySandboxTools._app` 错误范例 |

## 不做（明确排除）

- 不动 mutbot / mutagent 仓代码（方案 D：仅"点名"，由下游各自排期修正）
- 不做 `__set_name__` / 描述符自动转 ClassVar 推断（方案 A 已足够，再加推断会
  引入歧义）
- 不做"运行时 hot-swap default"能力的废弃（`DeclarationMeta.__setattr__`
  的现有路径仍然有效，正确使用场景仍然支持）
- 不做 `Annotated[ClassVar[X], ...]` 等复杂嵌套支持（v1 只识别直接 `ClassVar`）
