# Extension 重新设计 设计规范

**状态**：✅ 已完成
**日期**：2026-03-08
**类型**：功能设计

## 背景

Extension 用于为 Declaration 实例附加私有状态和实现细节，按关注点分离——Declaration 定义"对象是什么"，Extension 表达"某个子系统关于这个对象需要记住什么"。

当前 Extension 实现存在以下结构性问题：

### 问题 1：无注册机制，不可枚举

`Extension[User]` 仅在类型层面绑定目标类，运行时无注册。无法知道一个 Declaration 类型有哪些 Extension，也无法遍历实例上已创建的 Extension。

序列化场景是典型例子：序列化器需要遍历所有"可序列化的 Extension"并调用其序列化方法，但无法发现这些 Extension 的存在。

### 问题 2：`of()` 混淆了"确保存在"和"查询"

`of()` 是"不存在则创建，存在则返回"（ensure 语义），但命名像纯查询。两个语义不同的操作不应合并在一个方法中：

- "我要用这个 Extension"——确保存在，不存在则创建
- "这个 Extension 是否已经在用？"——查询，不存在返回 None

### 问题 3：字段声明不结构化

可变默认值（`list`、`dict` 等）不能直接声明，必须通过 `__extension_init__` 手动初始化：

```python
class DataExt(mutobj.Extension[Data]):
    _cache: list = None      # 不能写 = []，类变量会共享

    def __extension_init__(self):
        self._cache = []     # 必须手动初始化
```

更重要的是，普通 Python 类属性不提供结构化 schema，运行时无法内省 Extension 的字段信息。这与 Declaration 使用 `field()` + `AttributeDescriptor` 提供完整内省能力不一致。

### 触发场景

mutbot Session Channel 架构重构中，需要在 Extension 上声明 `_channels: list[Channel]`——可变列表，必须按实例独立。同时需要枚举 Session 上的所有 Extension 进行序列化。

## 设计方案

### 设计决策与依据

以下决策来自对 mutobj 核心定位和 ECS（Entity-Component-System）架构的对比分析。完整推导见 `docs/design/architecture.md`。

**决策 1：Extension 声明即注册**

`Extension[T]` 子类定义时，自动注册到目标 Declaration 类型的 Extension 注册表中。注册使 Extension 可发现、可枚举。

依据：参考 Unity Component / ECS 架构，实体（Declaration）必须知道自己可以拥有哪些组件（Extension）。没有注册就没有枚举能力，横切关注点（序列化、调试、监控）无法工作。

**决策 2：Archetype 是实现细节，不暴露给开发者**

运行时可以观测到"所有 User 实例都拥有相同的 Extension 组合"并据此优化内存布局，但这对开发者透明。开发者自由注册 Extension，不需要声明 Archetype。

依据：如果 Archetype 是概念层的东西，下游项目新增 Extension 就意味着"修改 Archetype"——这与 mutobj 的可扩展定位直接冲突。将 Archetype 保持为实现细节，扩展在概念层自由发生，优化在实现层自动适应。

**决策 3：操作语义分离——get_or_create / get**

"确保存在并返回"和"查询是否存在"是两个语义不同的操作，必须用不同的方法表达。

命名选择 `get_or_create` / `get`：
- `get_or_create`：名字本身就是完整的行为描述，不可能理解错。Django ORM 开发者熟悉这个模式。对 AI 也最友好——AI 生成代码时，方法名和意图一一映射，不需要记忆隐含规则。
- `get`：Python 标准的"安全查询"命名（`dict.get`），返回 None 表示不存在。
- 排除 `of`（语义模糊，不传达"会创建"）、`__call__`（让人以为构造了新实例）、`get(create=True)`（AI 最容易漏参数）。

**决策 4：字段声明结构化，复用 field() 基础设施**

Extension 字段使用与 Declaration 相同的 `field()` 机制声明。这不仅解决可变默认值问题，更为运行时提供完整的字段 schema。

依据："概念不对称，基础设施对称"——Declaration 字段和 Extension 字段在概念层是不同的东西（公开接口 vs 私有扩展状态），但在基础设施层共享同一套声明机制，使运行时优化不需要两套独立处理逻辑。

**决策 5：不自动处理裸可变默认值**

`_cache: list = []` 不会被自动检测并按实例复制，用户必须写 `field(default_factory=list)`。理由：隐式行为容易困惑；`field(default_factory=...)` 是 Python 生态已被广泛接受的写法；自动处理需要维护"可变类型"列表，边界模糊。

**决策 6：统一为 `__init__`，去掉 `__extension_init__`**

`__extension_init__` 存在的唯一原因是：当前 `__init__` 被调用时 `_instance` 还未设置。通过改变创建流程（`__new__` 创建裸实例 → 绑定 `_instance` → 处理 field → 调用 `__init__`），`__init__` 执行时 `_instance` 已可用，`__extension_init__` 不再需要。

统一为 `__init__` 的好处：少一个概念（`__init__` 是所有 Python 开发者的已有知识）；未来可自然扩展为带参数的 `__init__`，配合 `get_or_create` 传参。

**决策 7：Extension 支持多继承，枚举支持类型过滤**

Extension 可通过多继承实现接口（如 `Serializable`），`extensions()` 和 `extension_types()` 支持按类型过滤。类型签名通过 `@overload` + `TypeVar` 实现精确推导，调用方获得完整的类型安全和 IDE 补全。

依据：横切关注点（序列化、缓存、监控）需要按能力枚举 Extension。`hasattr` duck typing 无类型安全、不可内省、AI 无法推断方法名。多继承 + 类型过滤是标准 Python 模式（`collections.abc`、Django mixin），开发者零学习成本。`type[T] -> list[T]` 签名对 AI 也是最强信号——方法名和意图一一映射，不需要查文档。

**决策 8：Extension 注册规则——`Extension[T]` 语法即注册声明**

注册规则只有一条：**类定义中写了 `Extension[T]` 就注册，没写就不注册。** 不引入额外的 `register` 参数。

```python
# 写了 Extension[User] → 注册
class UserExt(Extension[User]):
    _count: int = 0

# 纯继承，没写 Extension[T] → 不注册（代码复用，不鼓励但不禁止）
class UserExtPlus(UserExt):
    _extra: str = ""

# 继承实现 + 写了 Extension[UserAdvance] → 注册
class UserAdvanceExt(UserExt, Extension[UserAdvance]):
    _level_cache: dict = field(default_factory=dict)
```

设计理由：
- Extension 继承不鼓励（组合优于继承），但不禁止。如果你选择继承，你应该清楚自己在做什么
- `Extension[T]` 语法本身就是显式的注册声明，不需要额外参数表达同一个意图
- 未注册的子类仍然可以通过 `get_or_create()` 使用（`_target_class` 通过 Python 继承传递），只是不出现在枚举中
- 不引入 `register` 参数，避免 "写了 `Extension[User]` 但 `register=False`" 这种语义矛盾

**决策 9：`extension_types()` 沿 Declaration MRO 收集**

`extension_types(UserAdvance)` 不仅返回直接注册在 `UserAdvance` 上的 Extension，还包含注册在 `User`（父类）上的 Extension。

```python
class User(Declaration): ...
class UserAdvance(User): ...

class UserExt(Extension[User]): ...
class UserAdvanceExt(Extension[UserAdvance]): ...

extension_types(User)        # → [UserExt]
extension_types(UserAdvance) # → [UserExt, UserAdvanceExt]（沿 MRO 收集）
```

依据：Liskov 替换原则——`UserAdvance` is-a `User`，`User` 的 Extension 在 `UserAdvance` 上同样可用。序列化 `UserAdvance` 实例时，必须能发现注册在 `User` 上的 Extension，否则数据丢失。

### 公开 API

#### Extension 类方法

```python
# 确保存在并返回（最常用，用于 @impl 代码）
# 返回 ExtType，永不为 None
ext = UserCacheExt.get_or_create(user)

# 查询，不存在返回 None（用于条件检查）
# 返回 ExtType | None
ext = UserCacheExt.get(user)
```

#### 模块级函数

```python
# 枚举实例上已创建的 Extension 实例（不触发创建）
for ext in mutobj.extensions(user):
    ...

# 按类型过滤：只返回 Serializable 的 Extension（类型安全，IDE 可补全）
for ext in mutobj.extensions(user, Serializable):
    ext._serialize()  # ✓ pyright 推导 ext 为 Serializable

# 查询类注册了哪些 Extension 类型
ext_types = mutobj.extension_types(User)  # → [UserCacheExt, UserStatsExt, ...]

# 按类型过滤 Extension 类型
ext_types = mutobj.extension_types(User, Serializable)
```

类型签名通过 `@overload` + `TypeVar` 实现精确推导：

```python
T = TypeVar("T")

@overload
def extensions(instance: Declaration) -> list[Extension]: ...
@overload
def extensions(instance: Declaration, filter_type: type[T]) -> list[T]: ...

@overload
def extension_types(decl_class: type[Declaration]) -> list[type[Extension]]: ...
@overload
def extension_types(decl_class: type[Declaration], filter_type: type[T]) -> list[type[T]]: ...
```

#### Extension 字段声明

```python
class SessionExt(mutobj.Extension[Session]):
    # 不可变默认值：直接赋值
    _retry_count: int = 0

    # 可变默认值：field()
    _channels: list[Channel] = mutobj.field(default_factory=list)
    _metadata: dict = mutobj.field(default_factory=dict)
```

### 注册机制

**消除中间类，使用标准 Python 泛型模式**

当前 `ExtensionMeta.__getitem__` 通过 `type()` 动态创建中间类，这不是标准 Python 泛型行为（标准泛型 `list[int]` 返回 `GenericAlias`，不创建真实类）。中间类的存在是设计缺陷，不是实现细节。

改用 `__init_subclass__` + `__orig_bases__`（pydantic、msgspec 等库的标准做法）：

```python
class Extension(Generic[T]):
    _target_class: type | None = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for base in getattr(cls, '__orig_bases__', ()):
            origin = getattr(base, '__origin__', None)
            if origin is not None and issubclass(origin, Extension):
                args = getattr(base, '__args__', None)
                if args:
                    cls._target_class = args[0]
                    _extension_registry.setdefault(args[0], []).append(cls)
                return
```

- `Extension[User]` 返回标准 `GenericAlias`，不创建真实类
- 不存在中间类，无需识别和过滤
- `ExtensionMeta` 可移除，减少元类复杂性
- 与 Python 泛型行为完全一致

注册表：

```python
_extension_registry: dict[type, list[type[Extension]]] = {}
```

### 初始化流程

Extension 实例在 `get_or_create()` 首次调用时创建，初始化顺序：

```
ext = cls.__new__(cls)               # 1. 创建裸实例（不调用 __init__）
→ ext._instance = instance           # 2. 绑定目标实例
→ 处理 field 描述符                    # 3. field(default_factory=...) → 实例赋值
→ ext.__init__()                     # 4. 用户 __init__（self._instance 和 field 值均已可用）
```

field 处理在 `get_or_create()` 内部完成（在创建阶段扫描类上的 Field 对象，调用 factory 生成实例级值），不引入额外的描述符机制。`__init__` 最后调用，用户可访问 `self._instance` 和所有 field 默认值。

### 使用场景示例

**场景 A：@impl 中使用 Extension**

```python
class SessionExt(mutobj.Extension[Session]):
    _channels: list[Channel] = mutobj.field(default_factory=list)

    def __init__(self):
        # self._instance 和 field 值均已可用
        if self._instance.auto_join:
            self._channels.append(Channel.default())

@mutobj.impl(Session.send)
def send(self: Session, message: str) -> None:
    ext = SessionExt.get_or_create(self)
    for ch in ext._channels:
        ch.deliver(message)
```

**场景 B：序列化（按类型枚举）**

Extension 可通过多继承实现接口，配合 `extensions()` 的类型过滤进行类型安全的枚举：

```python
class Serializable:
    """Extension 可实现的序列化接口"""
    def _serialize(self) -> dict: ...

class UserCacheExt(mutobj.Extension[User], Serializable):
    _hit_count: int = 0

    def _serialize(self) -> dict:
        return {"hit_count": self._hit_count}

@mutobj.impl(User.serialize)
def serialize(self: User) -> dict:
    data = {"name": self.name, "email": self.email}
    for ext in mutobj.extensions(self, Serializable):
        data.update(ext._serialize())  # 类型安全，IDE 可补全
    return data
```

**场景 C：条件检查**

```python
def maybe_use_cache(user: User) -> str | None:
    ext = UserCacheExt.get(user)
    if ext is not None:
        return ext._cache.get("result")
    return None
```

## 关键参考

### 源码
- `mutobj/src/mutobj/core.py:715-774` — Extension 类定义、`of()` 方法、`__getattr__` / `__setattr__` 代理
- `mutobj/src/mutobj/core.py:695-696` — `_extension_cache` WeakKeyDictionary
- `mutobj/src/mutobj/core.py:76-107` — `Field` 类和 `field()` 函数（Declaration 已有实现）
- `mutobj/src/mutobj/core.py:239-278` — `AttributeDescriptor`（Declaration 的字段描述符）
- `mutobj/tests/test_extension.py` — 现有 Extension 测试

### 设计文档
- `mutobj/docs/design/architecture.md` — mutobj 架构设计理念（Extension 设计方向的完整推导）

### 相关规范
- `mutbot/docs/specifications/refactor-split-routes.md` — 触发本需求的 Session Channel 架构重构

## 实施步骤清单

### 阶段 1：注册机制 [✅ 已完成]

- [x] **Task 1.1**: 新增 `_extension_registry` 全局注册表
  - 在 `_extension_cache` 附近新增 `_extension_registry: dict[type, list[type[Extension]]] = {}`
  - 状态：✅ 已完成

- [x] **Task 1.2**: 移除 `ExtensionMeta`，改用 `__init_subclass__` + `__orig_bases__`
  - Extension 基类改为 `class Extension(Generic[T])`，不再使用自定义元类
  - 在 `__init_subclass__` 中从 `__orig_bases__` 提取泛型参数作为 `_target_class`
  - 注册规则：仅当 `__orig_bases__` 中包含 `Extension[T]` 形式时注册（决策 8）
  - 纯继承另一个 Extension 子类（不写 `Extension[T]`）不注册，但 `_target_class` 通过 Python 继承传递
  - 实施细节：使用 `cls.__dict__.get("__orig_bases__", ())` 而非 `getattr`，确保只检查直接声明
  - 状态：✅ 已完成

- [x] **Task 1.3**: 实现 `extension_types()` 模块级函数
  - 沿 Declaration 的 MRO 收集所有注册的 Extension 类型（决策 9）
  - 支持 `filter_type` 参数，按 `issubclass` 过滤
  - 导出到 `__all__` 和 `__init__.py`
  - 状态：✅ 已完成

### 阶段 2：操作语义重构 [✅ 已完成]

- [x] **Task 2.1**: 实现 `get_or_create()` 类方法，替代 `of()`
  - 使用 `cls.__new__(cls)` 创建裸实例
  - 按新初始化顺序：`__new__` → `_instance` 绑定 → field 处理 → `__init__`
  - field 处理：遍历类及其 MRO 的 `__annotations__`，查找对应类属性中的 `Field` 实例，调用 `default_factory()` 或赋 `default` 值到实例上
  - 缓存逻辑保持不变（`_extension_cache` WeakKeyDictionary）
  - 状态：✅ 已完成

- [x] **Task 2.2**: 实现 `get()` 类方法
  - 从 `_extension_cache` 查询，不存在返回 `None`
  - 返回类型 `Extension[T] | None`
  - 状态：✅ 已完成

- [x] **Task 2.3**: 删除 `of()` 方法
  - 直接移除，不保留兼容别名
  - 状态：✅ 已完成

- [x] **Task 2.4**: 删除 `__extension_init__` 支持
  - 已随 `of()` 一同移除
  - Extension 基类的 `__init__` 改为空操作
  - 状态：✅ 已完成

### 阶段 3：枚举功能 [✅ 已完成]

- [x] **Task 3.1**: 实现 `extensions()` 模块级函数
  - 实现：从 `_extension_cache[instance]` 获取已创建的 Extension 实例，按 `filter_type` 做 `isinstance` 过滤
  - 实例不在缓存中时返回空列表（不报错）
  - 导出到 `__all__` 和 `__init__.py`
  - 状态：✅ 已完成

### 阶段 4：导出与文档 [✅ 已完成]

- [x] **Task 4.1**: 更新 `__all__` 和 `__init__.py` 导出
  - 新增导出：`extensions`、`extension_types`
  - 状态：✅ 已完成

- [x] **Task 4.2**: 更新 `docs/api/reference.md`
  - 更新 Extension 章节：`of()` → `get_or_create()` / `get()`
  - 新增 `extensions()`、`extension_types()` 文档
  - 新增 `field()` 在 Extension 中的用法
  - 状态：✅ 已完成

### 阶段 5：测试 [✅ 已完成]

- [x] **Task 5.1**: 重写现有 Extension 测试
  - `test_extension_of` → `test_extension_get_or_create`
  - `test_extension_of_cached` → `test_extension_get_or_create_cached`
  - `test_extension_init_hook` → `test_extension_init_with_instance_access`
  - `test_extension_default_values` → `test_extension_field_default_factory` + `test_extension_field_default_value`
  - `test_impl_using_extension` → 改用 `get_or_create`
  - 同步更新 `test_defaults.py` 和 `test_inheritance.py` 中的 `of()` 调用
  - 状态：✅ 已完成

- [x] **Task 5.2**: 新增注册机制测试
  - 测试 `Extension[T]` 声明自动注册
  - 测试 `extension_types()` 查询
  - 测试 `extension_types()` 带类型过滤
  - 测试纯继承 Extension 子类不注册（决策 8）
  - 测试继承 + 显式 `Extension[T]` 注册（决策 8）
  - 测试 `extension_types()` 沿 Declaration MRO 收集（决策 9）
  - 状态：✅ 已完成

- [x] **Task 5.3**: 新增枚举与过滤测试
  - 测试 `extensions()` 返回已创建的 Extension
  - 测试 `extensions()` 带类型过滤（多继承接口）
  - 测试未创建 Extension 的实例返回空列表
  - 状态：✅ 已完成

- [x] **Task 5.4**: 新增 `get()` 测试
  - 测试未创建时返回 None
  - 测试已创建后返回缓存实例
  - 状态：✅ 已完成

- [x] **Task 5.5**: 新增 field() 支持测试
  - 测试 `field(default_factory=list)` 按实例独立
  - 测试 `field(default=...)` 不可变默认值
  - 测试多个实例的 field 值互不影响
  - 状态：✅ 已完成

## 实施风险审阅

### ~~风险 1：`ExtensionMeta.__getitem__` 创建的中间类识别~~

**已通过设计变更消除**。改用 `__init_subclass__` + `__orig_bases__` 后，`Extension[User]` 返回标准 `GenericAlias`，不创建中间类，不存在识别问题。同时移除 `ExtensionMeta`，减少元类复杂性。

### 风险 2：`__new__` + 延迟 `__init__` 与用户自定义 `__new__` 冲突

**问题**：`get_or_create()` 使用 `cls.__new__(cls)` 创建裸实例，然后手动调用 `__init__()`。如果用户在 Extension 子类中定义了 `__new__`，可能产生意外行为。

**评估**：低风险。Extension 子类定义 `__new__` 的场景极罕见。可在文档中说明 Extension 不应覆盖 `__new__`，或在 `__init_subclass__` 中检测并报错。

### 风险 3：field 扫描的 MRO 遍历

**问题**：Extension 支持继承（Extension 子类继承另一个 Extension 子类）。field 扫描需要遍历 MRO 中的 `__annotations__` 和类属性，收集所有 `Field` 实例。

**风险**：如果子类和父类声明同名 field，需要确保子类的 field 覆盖父类的（不重复初始化）。Declaration 的 `DeclarationMeta.__new__` 中已有类似逻辑处理继承的 `AttributeDescriptor`，可参考。

**建议方案**：从 MRO 底部（最远祖先）向上遍历，后出现的同名 field 覆盖先出现的。或直接只扫描 `cls.__annotations__`（不含继承），配合 `getattr(cls, name)` 获取可能继承的 Field——`getattr` 本身会沿 MRO 查找。

### 风险 4：`_extension_registry` 与 Declaration 热重载的交互

**问题**：mutobj 支持 Declaration 类的热重载（`DeclarationMeta.__new__` 中检测同名类并 `_update_class_inplace`）。如果 Extension 的目标 Declaration 被热重载，`_extension_registry` 中以旧类对象为 key 的记录可能失效。

**评估**：中风险。热重载后旧类对象被新类对象替换（`_update_class_inplace` 原地修改），所以 `_extension_registry` 的 key 仍然有效（因为是同一个对象）。但需要验证 `_update_class_inplace` 确实是原地修改而非创建新类。

**验证方式**：在实施阶段写一个测试覆盖此场景。

### 风险 5：Extension 基类的 `__init__` 签名变化

**问题**：当前 Extension 基类定义了 `__init__(self) -> None`。改为允许用户覆盖 `__init__` 后，基类的 `__init__` 应变为无操作或移除。如果用户子类不调用 `super().__init__()`，需要确保不影响内部状态。

**评估**：低风险。新流程中 `_instance` 由 `get_or_create()` 直接赋值（不依赖 `__init__`），field 值也由 `get_or_create()` 处理。`__init__` 纯粹是用户钩子，基类可以提供空 `__init__`，用户不调用 `super()` 也无问题。

### ~~风险 6：Extension 继承 Extension 的注册行为~~

**已通过决策 8 解决**。规则简单明确：有 `Extension[T]` 就注册，没有就不注册。不引入额外参数。未注册的子类仍可通过 `get_or_create()` 使用，但不出现在枚举中。

### 总结

| 风险 | 等级 | 处理策略 |
|------|------|---------|
| ~~中间类识别~~ | ~~中~~ | ~~已通过设计变更消除~~ |
| `__new__` 冲突 | 低 | 文档说明，可选运行时检测 |
| field MRO 遍历 | 中 | 参考 DeclarationMeta 的继承处理，用 `getattr` 沿 MRO 查找 |
| 热重载交互 | 中 | 验证 `_update_class_inplace` 原地修改，补充测试 |
| `__init__` 签名 | 低 | 基类空 `__init__`，不依赖 `super()` 调用 |
| ~~Extension 继承注册~~ | ~~中~~ | ~~已通过决策 8 解决~~ |

无高风险项。原风险 1、6 已通过设计决策消除。

