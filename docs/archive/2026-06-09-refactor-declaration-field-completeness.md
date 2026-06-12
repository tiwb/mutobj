# Declaration 字段构造完整性 设计规范

**状态**：✅ 已完成
**日期**：2026-06-09
**类型**：重构

## 需求

1. **运行时承诺缺失**：当前 Declaration 允许字段无 default 且 `__init__` 不赋值，构造合法但首次访问抛 `AttributeError`，错误时机太晚、提示误导。dataclass 的契约是"出 `__init__` 后所有声明字段都有值"，mutobj 应在声明-实现分离的语境下提供等价或更强的承诺。

2. **`@impl(__init__)` 无安全网**：用户用 `@impl(Cls.__init__)` 完全替换默认构造时，框架对"漏赋字段"无任何检查——这是声明-实现分离最容易踩的坑。

3. **省略 default 的语义混淆**：一个"省略 default"的语法当前同时承担两种语义（"必填" / "由生命周期负责"），调用端无法区分。

4. **纯注解 vs `field()` 双轨机制**：当前框架对两种字段声明方式行为不一致：
   - `attr: SomeType` 纯类型注解 → 框架完全看不见，零运行时约束
   - `attr: SomeType = field()` → 框架可见，但仍不强制必填
   
   用户直觉上认为这两种写法在"字段是否必须有值"这一点上应有等价承诺。类型系统（pyright）说"必有"，运行时说"不一定"，这种不对称让"声明即承诺"的核心理念打了折扣。

5. **下游防御性写法蔓延**：以 mutagent 为例，`Conversation` 声明 `agent: Agent`（非 Optional），但构造后 `agent` 可能未赋值，消费端被迫使用 `getattr(self.agent, "context", None)` 等带默认值的防御访问；测试代码用最小 mock 构造，属性缺失不报错 → 测试和生产的构造契约不一致。

## 关键参考

- `src/mutobj/core/_fields.py:115-148` — `Field` 类与 `field()` 工厂，定义 `default / default_factory / init`
- `src/mutobj/core/_fields.py:240-246` — `_get_init_fields()` 仅返回含 `AttributeDescriptor` 且 `init=True` 的字段，**纯注解不可见**
- `src/mutobj/core/_fields.py:370-430` — `AttributeDescriptor`，含 `has_default / make_default / __get__ / __set__`，未赋值时 `__get__` 抛 `AttributeError`
- `src/mutobj/core/_declaration.py:404-470` — `Declaration` 基类，`__new__` 仅为 `has_default` 字段铺默认值；`__init__` 只 `setattr` 传入的 kwargs，不检查缺失
- `src/mutobj/core/_declaration.py` — `DeclarationMeta.__call__`，构造流程 `__new__ → __init__ → __post_init__`
- `mutbot/mutagent/src/mutagent/webui/_conversation_impl.py:185-204` — 典型消费者：`Conversation` 的 `agent` 用纯注解声明，`_refresh_shell` 里 `getattr` 防御
- `mutbot/mutagent/src/mutagent/webui/conversation.py:15-42` — `Conversation` 声明，所有字段都是纯注解
- `mutbot/mutagent/src/mutagent/core/agent.py:20-58` — `Agent` 声明，`llm` / `context` / `tools` / `model` 全是纯注解
- 对比 dataclass：无 default 字段在 `__init__` 必填，且要求"无 default 在前、有 default 在后"以保证函数签名合法

## 设计方案

### 总体目标

**让"声明即承诺"统一覆盖所有字段声明形式**：

- 类体中的类型注解（无论是否经过 `field()` 包装）都被视为声明字段
- Declaration 实例在 `__post_init__` 跑完时，所有声明字段必须已赋值
- 任何遗漏在构造期立即报错（TypeError），不再延迟到首次访问

### 字段识别统一化（消除双轨）

**核心变更**：框架扫描类的 `__annotations__`，为每个非 `ClassVar` 的注解都建立等价于字段的 `AttributeDescriptor`，纯注解和 `field()` 包装走同一条路径。

| 类体写法 | 等价于 |
|---------|-------|
| `x: T`（纯注解，无赋值） | `x: T = field()`（无 default，必填） |
| `x: T = value`（注解 + 默认值） | `x: T = field(default=value)`（有 default，可省略） |
| `x: T = field(...)`（显式 field） | 保持原语义 |
| `x: ClassVar[T] = ...` | 不被视为字段（与 dataclass 一致） |

完成这一步后，"双轨机制"消失，下文的三层闸门自然适用于所有声明字段。

补充约束：

- `x: T = immutable_value` 视为有 default；可变默认值（list/dict/set/bytearray）继续在元类层面拒绝，要求改为 `field(default_factory=...)`
- `typing.ClassVar[...]` 跳过，不视为字段；`typing.Final[...]` 暂不特殊处理，仍按普通字段处理

### 两层闸门

1. **构造完整性兜底**（统一在 `__post_init__` 之后检查）
   - `DeclarationMeta.__call__` 在 `__post_init__` 跑完后扫一遍所有声明字段，凡未赋值的报：
     `TypeError: <Cls> missing field(s) after construction: 'x', 'y'. Either pass them to __init__ or assign in __post_init__.`
   - 这是**唯一的运行时字段完整性检查点**，覆盖默认 `__init__` 和 `@impl(__init__)` 两条路径
   - 允许用户在 `__post_init__` 里补齐：检查在它之后执行
   - 默认 `__init__` **不单独检查必填字段**——因为 mutobj 允许 `@impl(__init__)` 自定义参数签名，
     加上 `super().__init__()` 链的存在，在 `__init__` 内部用 `type(self)` 做必填检查会误伤合法场景。
     默认 `__init__` 只做两件事：(a) 位置参数按 `init=True` 顺序映射到 kwargs；(b) 拒绝 `init=False` 字段被传入

2. **`init=False` 必须显式说明值从哪来**
   - 类定义阶段（`DeclarationMeta.__new__`）就检查：`init=False` 字段必须满足 `default` 或 `default_factory` 至少其一
   - 否则在元类里直接拒绝该声明：
     `TypeError: Declaration '<Cls>' field 'x' is init=False but has no default; provide default/default_factory or set init=True.`
   - 不引入 `lazy=True` 之类的"晚绑定出口"。需要延迟绑定的场景用 `default=None` + `Optional[T]` 表达，类型系统可见，调用方明确

### 派生字段模式

- `init=False` 的派生字段官方推荐写法：`field(default=None, init=False)` + `Optional[T]` + 在 `__post_init__` 中赋最终值
- 完整性检查放在 `__post_init__` 之后，因此允许在该阶段补齐原本由自定义 `__init__` 漏掉的必填字段
- 完整性判定使用 `descriptor.storage_name in obj.__dict__`，避免被 `__getattr__` 干扰，也不引入额外状态

### 错误信息规范

- 构造后完整性失败：`TypeError: Foo missing field(s) after construction: 'x'. Either pass them to __init__ or assign in __post_init__.`
- `init=False` 无 default：`TypeError: Declaration 'Foo' field 'x' is init=False but has no default; provide default/default_factory or set init=True.`
- 描述符的 `__get__` 报错保持现状（兜底防御），但正常路径下不应再被触发

### 范围与不影响项

**保持不变**：
- `field()` API、`MISSING` 哨兵、`AttributeDescriptor` 数据结构
- 字段顺序规则（`_get_ordered_fields` 基类在前）
- `@impl(Cls.__init__)` / `@impl(Cls.__post_init__)` 的覆盖语义
- `__post_init__` 时机（仍由元类 `__call__` 强制调用一次）

**变更点**：
- `DeclarationMeta.__new__`：扫描 `__annotations__` 把纯注解转为隐式 `AttributeDescriptor`；追加 `init=False` 字段的合法性校验
- `Declaration.__init__`（默认实现）：位置参数只走 `init=True` 字段；拒绝 `init=False` 字段被传入；**不做必填检查**（由元类统一兜底）
- `DeclarationMeta.__call__`：在 `obj.__post_init__()` 后追加完整性检查（统一覆盖默认 init 和 `@impl(__init__)` 两条路径）

### 兼容性策略

属于破坏性变更：
- 现存"纯注解 + 不传 + 后续访问"的代码会立刻 TypeError（命中面最大）
- 现存"`field()` 无 default + 不传 + 后续访问"的代码会立刻 TypeError
- 现存"`init=False` 无 default"的代码会在导入时 TypeError

迁移路径（在 lint 工具中提供，不在本次 spec 范围内单独实现）：
- mutobj-lint 增加规则：检测 `init=False` 无 default 的声明，建议加 `default=None` 或 `default_factory=...`
- 检测无 default 的字段（含纯注解），提示用户确认是否真的应该必填，否则改为 `Optional[T] = None`

静态冲击面评估（2026-06-09）：

- `mutobj / mutio / mutagent / mutgui / mutbot` 共扫描到 363 个 `Declaration` 类、119 个纯注解字段、166 个带默认值的注解字段、28 个 `@impl(...__init__)`
- 当前工作区未发现 `field(init=False)` 且无 `default/default_factory` 的现存声明
- 结论：冲击面主要集中在"先构造空对象、再补字段"的调用路径；按用户决策直接切换到严格模式，下游仓库后续按新契约重构

## 实施步骤清单

- [x] 在 `DeclarationMeta.__call__` 中增加统一个构造后完整性检查（替代原默认 `__init__` 中的必填检查）
- [x] 在类定义与类级字段覆盖路径中拒绝 `init=False` 且无 default 的字段
- [x] 为严格模式补充回归测试，并同步修正 mutobj 内部受影响的旧测试
- [x] 修正 `@impl(__init__)` 中 `super().__init__()` 链误报问题（默认 `__init__` 不再用 `type(self)` 做必填检查）

## 消费者场景

| 消费者 | 场景 | 依赖的输出 | 验收标准 |
|--------|------|-----------|---------|
| mutio / mutagent / mutbot / mutgui | 各项目内 Declaration 子类构造（纯注解 + `field()` 两种风格） | 必填字段未传立即 TypeError；构造结束后所有字段可安全访问 | 全仓库 pytest 通过；mutagent 的 `Conversation` / `Agent` 等纯注解声明的 Declaration 在构造时强制必传 |
| mutagent 消费端 | 移除 `getattr(self.agent, "xxx", None)` 防御写法 | 构造期保证 `agent` 已赋值，消费端可直接 `self.agent.xxx` | 防御性 `getattr` 在主要路径上消失 |
| mutobj-lint | 检测违规字段声明 | 元类拒绝的写法可由 lint 提前发现；纯注解必填字段建议改 `Optional[T] = None` | lint 增加对应规则后，CI 能在不实际执行的情况下指出问题 |
| `@impl(Cls.__init__)` 用户 | 自定义构造 + `super().__init__()` 链（如 mutgui 事件系统） | 默认 `__init__` 不再在 super() 链中误报必填缺失；构造完整性在 `__post_init__` 后统一兜底 | 单测覆盖：`@impl` init 在 `super().__init__()` 之后才赋值字段（对齐 mutgui EventHandler/Callback 模式） |
