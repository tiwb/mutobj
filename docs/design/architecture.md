# mutobj 架构设计理念

## mutobj 是什么

mutobj (Mutable Object) 是一个 Python 类定义库，核心能力是**声明与实现分离**。用户通过 `Declaration` 子类声明类型的数据和接口，通过 `@impl` 在其他位置提供实现，通过 `Extension` 为对象附加额外状态。

mutobj 的设计目标不仅是提供一种代码组织模式，而是建立一套**结构化的对象模型**——在保持 Python 自然开发体验的同时，为运行时优化、AI 辅助开发、跨项目扩展提供坚实的基础设施。

## 核心抽象

### Declaration：身份 + 数据 + 接口

Declaration 是 mutobj 的中心抽象。一个 Declaration 子类同时承担三个职责：

```python
class User(mutobj.Declaration):
    # 数据：结构化字段声明
    name: str
    email: str
    active: bool = True

    # 接口：方法签名（桩方法）
    def greet(self) -> str: ...
```

- **身份**：`User` 是一个类型，有唯一的类路径，可被 `resolve_class()` 发现
- **数据**：字段通过类型注解和 `field()` 结构化声明，运行时可内省
- **接口**：方法签名定义公开契约，实现可在其他位置提供

这三者的统一是刻意的设计选择——开发者用自然的 Python 类语法定义一个完整的类型，不需要分别声明 schema、interface、entity。

### @impl：实现的分离与可替换

`@impl` 将方法实现从类定义中分离出来：

```python
@mutobj.impl(User.greet)
def greet(self: User) -> str:
    return f"Hello, {self.name}!"
```

实现可以被替换——多个模块可以为同一方法注册 `@impl`，最后注册的为活跃实现。这是 mutobj "可变" 语义的核心：类型的行为可以在运行时被修改和热重载。

### Extension：按关注点附加状态

Extension 为 Declaration 实例附加额外的私有状态和内部逻辑，而不污染公开声明：

```python
class UserCacheExt(mutobj.Extension[User]):
    _cache: dict
    _hit_count: int = 0
```

Extension 的存在理由是**关注点分离**：User 的声明定义了"User 是什么"，而 `UserCacheExt` 表达的是"缓存子系统需要为每个 User 记住什么"。这两种信息属于不同的关注点，不应混在同一个类定义中。

## 设计原则

### 原则 1：语义层 OOP，基础设施层可优化

mutobj 在开发者面对的语义层保持面向对象——`self.name`、`ext._count`、方法调用，都是自然的 Python OOP。但在基础设施层，所有数据通过结构化机制声明（类型注解 + `field()` + `AttributeDescriptor`），运行时拥有完整的字段 schema。

这意味着：**开发者写的是 OOP，但运行时有能力将数据重新排布**。当前实现使用 Python 字典存储属性，未来可以在不改变用户代码的前提下，对标记了优化提示的类型切换到更紧凑的内存布局（SOA、`__slots__`、甚至 native 存储）。

这个原则的关键约束是：**阶段 N 的 API 写法不能和阶段 N+1 的优化冲突**。开发者今天写的代码，未来不需要改写就能获得优化。

### 原则 2：可扩展优先于可优化

mutobj 的核心定位是"可扩展、可变化"。当扩展性和优化存在张力时，扩展性优先。

具体体现：
- Declaration 子类可以在任何模块中定义，`discover_subclasses()` 自动发现
- `@impl` 可以在任何模块中注册，实现可被替换和热重载
- Extension 可以从任何模块为任何 Declaration 类型附加状态
- 配置驱动加载——`resolve_class()` 按类路径动态导入，不 import 就不存在

优化是在这个扩展性框架内做的——运行时观测到稳定的模式后可以加速，但不能以牺牲扩展能力为代价。

### 原则 3：强约束换取运行时能力

mutobj 为 Python 增加了约束（必须继承 Declaration、字段必须类型注解、方法实现通过 `@impl`），但每一条约束都换来了具体的运行时能力：

| 约束 | 换取的能力 |
|------|-----------|
| 继承 Declaration | 类注册表、子类发现、热重载 |
| 字段类型注解 | 结构化 schema、运行时内省、未来内存优化 |
| `@impl` 分离 | 实现可替换、实现链、模块级注销/重注册 |
| `field()` 声明 | 可变默认值安全、default_factory、字段元数据 |

这些约束对 AI 辅助开发也是友好的——AI 可以通过内省 Declaration 的 schema 和方法签名理解类型的完整结构，而不需要执行代码或猜测运行时行为。

## Declaration 与 Extension 的关系

### Declaration 字段是"内建组件"

对比 ECS（Entity-Component-System）架构：

```
ECS:    Entity = 纯 ID + Component[]（所有数据在 Component 中，平等排列）
mutobj: Declaration = 身份 + 内建数据 + Extension[]
```

Declaration 自身的字段可以理解为一个**始终存在的、匿名的内建组件**。这解释了为什么许多 mutobj 应用完全不需要 Extension——Declaration 自身已经是一个自足的数据容器。

Extension 在需要时才出场：当不同关注点需要为同一个对象附加各自的私有状态时。

### 概念不对称，基础设施对称

Declaration 字段和 Extension 字段在**概念层**是不同的东西：

- **Declaration 字段**：定义层，"这个类型有什么数据"，是公开契约的一部分
- **Extension 字段**：扩展层，"某个子系统为这个类型附加什么数据"，是私有实现细节

但在**基础设施层**，两者应共享同一套结构化声明机制（`field()`、类型注解、描述符）。运行时做优化时不关心"谁声明的"，只关心"有哪些字段、什么类型、如何存储"。

这个设计使得 Extension 字段和 Declaration 字段在未来可以统一进入同一个优化管道，而不需要两套独立的处理逻辑。

## Extension 的设计方向

### 当前实现

Extension 机制已完成重新设计（详见 `docs/archive/2026-03-08-feature-extension-redesign.md`）：

- `Extension[T]` 声明时自动注册到目标 Declaration 类型的注册表（`__init_subclass__` + `__orig_bases__`）
- `ExtType.get_or_create(instance)`：确保存在并返回（最常用）
- `ExtType.get(instance)`：查询，不存在返回 None
- `mutobj.extensions(instance, filter_type)`：枚举实例上已创建的 Extension
- `mutobj.extension_types(decl_class, filter_type)`：查询类注册了哪些 Extension 类型，沿 MRO 收集
- `__init__` 中 `self.target` 和 field 值均已可用
- 支持 `field(default_factory=...)` 声明可变默认值
- 通过 `self.target` 显式访问宿主 Declaration 实例（不做属性代理 —— 避免命名冲突和隐式行为）

### 已实现的演进方向

以下方向已在重新设计中实现：

#### 注册与发现

`Extension[T]` 声明时自动注册到目标 Declaration 的注册表。支持：

- 类级别枚举：`extension_types(User)` 返回所有注册的 Extension 类型
- 实例级别枚举：`extensions(user)` 返回已创建的 Extension 实例
- 类型过滤：`extensions(user, Serializable)` 按接口过滤

#### 操作语义的分离

- `get_or_create(instance)`：确保存在并返回（用于 @impl 代码）
- `get(instance)`：查询，不存在返回 None（用于条件检查）

#### 字段声明结构化

Extension 字段使用与 Declaration 相同的 `field()` 机制声明，支持 `default_factory` 可变默认值。

#### Archetype 是实现细节

运行时可以观测到"所有 User 实例都拥有 ExtA、ExtB、ExtC"这一稳定模式，并据此优化内存布局。但 Archetype（组件组合模式）**不是暴露给开发者的概念**。

原因：如果 Archetype 是概念层的东西，那么下游项目新增 Extension 就意味着"修改 Archetype"——这是一个重操作，直接与 mutobj 的可扩展定位冲突。将 Archetype 保持为实现细节，扩展在概念层自由发生，优化在实现层自动适应。

这与 Python 的 `__slots__` 类比：`__slots__` 是优化手段，不是数据模型的概念。开发者不需要为了正确性而使用 `__slots__`，但运行时可以利用它提升性能。

### 渐进优化路径

Extension 的设计应支持从纯 Python 到极致优化的渐进路径，且各阶段的用户代码不需要改写：

| 阶段 | 存储方式 | 适用场景 |
|------|---------|---------|
| 默认 | Python 字典 | 通用场景，零配置 |
| 结构化 | `__slots__` 或紧凑存储 | 标记了优化提示的类型 |
| SOA | 同类实例数据连续排布 | 批量处理热点路径 |
| Native | C 扩展或 native 存储 | 极致性能需求 |

每个阶段的切换由运行时配置或标记驱动，不改变开发者的代码写法。这确保了 mutobj 可以从"方便的 Python 库"渐进演化为"高性能对象系统"，而不需要推翻重来。

## 与 ECS 的关系

mutobj 不是 ECS 框架，但设计上与 ECS 的核心理念兼容：

**借鉴的**：
- 组件化思想——Extension 作为可附加的数据组件
- 数据可内省——结构化字段声明使运行时了解完整 schema
- 组合优于继承——通过 Extension 组合扩展对象能力

**刻意不采用的**：
- 纯 ID 实体——Declaration 自身持有数据和接口，这是 OOP 的自然表达
- 强制数据与行为分离——Extension 可以包含方法（内部 helper），不强迫所有逻辑放到外部 System
- 强制 Archetype 声明——组件组合模式由运行时推导，不暴露给开发者

**保持兼容的**：
- 注册与枚举能力——未来可支持"查询所有拥有 ExtA + ExtB 的实例"
- 数据布局可优化——结构化声明使 SOA 布局在技术上可行
- 批量操作——当实例数据连续排布时，可支持高效的批量遍历

这个定位可以概括为：**OOP 的开发体验，DOD 的优化潜力**。开发者从面向对象自然过渡，不需要跨越 OOP 到 ECS 的认知鸿沟；当性能成为瓶颈时，同一套代码可以逐步获得面向数据的优化。
