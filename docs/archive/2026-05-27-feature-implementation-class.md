# Implementation 类 —— 普通类迁移到 Declaration 的桥接机制

**状态**：✅ 已完成  
**日期**：2026-05-27  
**类型**：功能设计

## 需求

将已有的大代码量普通 Python 类迁移到 mutobj 的 `Declaration + @impl` 模式时，若每个方法都手动拆成：

```python
@mutobj.impl(Decl.method)
def method(self, ...): ...
```

迁移成本很高。希望提供一种 `Implementation[Decl]` 桥接类机制：原文件改名为 `_xxx_impl.py`，原类改名为 `XXXImpl(Implementation[XXX])`，方法基本保持原位，框架自动把同名方法注册为 Declaration 方法实现。

核心约束：

- Declaration 和 Impl 是**两个独立类**，不互相继承，`isinstance` 不互通。
- Impl 需要像原普通类一样自由定义任意方法和属性，包括 `get`、`owner`、`_xxx`、`__init__` 等名字。
- `Implementation` 基类不能预定义 `get()`、`get_or_create()`、`owner` 等会污染迁移类命名空间的公开 API。
- 使用方通过 Declaration 实例调用公开方法，内部桥接到 Impl。
- 需要触碰实现细节时，通过 mutobj 的**模块级 API** 获取 Impl 实例，而不是调用 Impl 类上的预定义方法。

## 关键参考

### 源码

- `mutobj/src/mutobj/core/_state.py:5` — `_impl_chain`：覆盖链存储结构
- `mutobj/src/mutobj/core/_impls.py:115-149` — `_register_to_chain()`：注册实现到覆盖链
- `mutobj/src/mutobj/core/_impls.py:71-92` — `_apply_impl()`：将链顶实现应用到类方法/property
- `mutobj/src/mutobj/core/_declaration.py:40-316` — `DeclarationMeta.__new__`：Declaration 类创建流程
- `mutobj/src/mutobj/core/_declaration.py:318-323` — `DeclarationMeta.__call__`：`__new__ → __init__ → __post_init__` 流水线
- `mutobj/src/mutobj/core/_declaration.py:374-390` — `Declaration.__new__`：字段默认值绑定
- `mutobj/src/mutobj/core/_declaration.py:391-415` — `Declaration.__init__`：字段参数解析
- `mutobj/src/mutobj/core/_constants.py:18-20` — `_DECLARATION_USER_HOOKS`：Declaration 基类白名单钩子
- `mutobj/src/mutobj/core/_constants.py:1-4` — `_DECLARED_METHODS` 等标记常量
- `mutobj/src/mutobj/core/_impls.py:345-412` — `impl()` 装饰器：方法注册到覆盖链
- `mutobj/src/mutobj/core/_extensions.py:16-63` — `Extension` 类：关联机制参考
- `mutobj/src/mutobj/core/_implementation.py` — `Implementation` 基类、自动桥接与模块级查询 API

## 核心模型

```text
Declaration（类型契约）                 Impl（实际干活）
┌────────────────────────┐   外部关联   ┌──────────────────────────┐
│ 字段声明: path, cache  │ ←──────────→ │ 原普通类迁移而来          │
│ 方法签名: get()        │              │ 可自由定义 get/owner/... │
│                        │              │ def get(self): ...       │
│ 不直接继承 Impl        │              │ def __init__(self): ...  │
└────────────────────────┘              └──────────────────────────┘
```

设计要点：

- Declaration 定义字段契约和公开方法签名。
- Impl 持有实际状态和实现逻辑，是迁移场景中的“原普通类”。
- Declaration 与 Impl 的关联由框架的外部 registry 保存。
- 框架**不向 Impl 类或 Impl 实例注入公开方法或公开属性**。
- Impl 方法里的 `self` 是 Impl 实例自己。
- 如需从 Impl 找到对应 Declaration，使用模块级 API，例如 `mutobj.implementation_owner(self)`，而不是 `self.owner`。

## 模块级 API

因为迁移前的普通类可能已经定义了 `get()`、`get_or_create()`、`owner` 等名字，`Implementation` 不能复用 `Extension` 那种类方法/实例属性 API。

第一版建议提供以下模块级 API：

| API | 作用 |
|-----|------|
| `mutobj.implementation_class(decl_or_cls)` | 查询 Declaration 实例或 Declaration 类注册的 Implementation 类；没有则返回 `None` |
| `mutobj.implementation_of(decl, impl_cls=None)` | 查询 Declaration 实例关联的 Impl 实例；没有则返回 `None`。传入 `impl_cls` 时便于类型收窄和校验 |
| `mutobj.implementation_owner(impl)` | 查询 Impl 实例关联的 Declaration 实例；没有则返回 `None` |

示例：

```python
decl = ConfigLoader(path="/x")

# 获取关联的实现实例
impl = mutobj.implementation_of(decl, ConfigLoaderImpl)

# 如果一个 Decl 至多一个 Impl，也可省略 impl_cls
impl = mutobj.implementation_of(decl)

# 在 Impl 方法内部获取 Declaration
class ConfigLoaderImpl(mutobj.Implementation[ConfigLoader]):
    def refresh(self):
        decl = mutobj.implementation_owner(self)
        ...
```

明确不提供下面这些 API：

```python
ConfigLoaderImpl.get(decl)          # 不提供：会和业务 get() 重名
ConfigLoaderImpl.get_or_create(...) # 不提供：会污染迁移类命名空间
self.owner                          # 不由框架注入：会和业务 owner 属性重名
```

用户仍然可以在自己的 Impl 类中自由定义这些名字：

```python
class ConfigLoaderImpl(mutobj.Implementation[ConfigLoader]):
    def get(self, key, default=None): ...  # 业务方法，允许

    def __init__(self, owner):            # 业务参数名，允许
        self.owner = owner                # 业务属性，允许；框架不占用
```

## 用法示例

### 改造前：普通类

```python
# config_loader.py
class ConfigLoader:
    def __init__(self, path, cache=True):
        self.path = path
        self.cache = cache
        self._data = {}
        self._load()

    def get(self, key, default=None):
        self._ensure_loaded()
        return self._data.get(key, default)

    def _load(self): ...
    def _ensure_loaded(self): ...
```

### 改造后：Declaration

```python
# config_loader.py
import mutobj
from typing import Any

class ConfigLoader(mutobj.Declaration):
    path: str
    cache: bool = True

    # 这里是公开构造签名，也是 __init__ 覆盖链入口。
    # 若 Impl.__init__ 自动注册到这里，则这个函数只是链底默认实现。
    def __init__(self, path: str, cache: bool = True) -> None: ...

    def get(self, key: str, default: Any = None) -> Any: ...

from . import _config_loader_impl as _  # noqa: F401
```

### 改造后：Implementation

```python
# _config_loader_impl.py
import mutobj
from .config_loader import ConfigLoader

class ConfigLoaderImpl(mutobj.Implementation[ConfigLoader]):
    def __init__(self, path, cache=True):
        # 如果需要保留 Decl 字段绑定，显式调用下一级 __init__ 实现。
        owner = mutobj.implementation_owner(self)
        mutobj.impl_call_super(ConfigLoader.__init__, owner, path, cache=cache)

        self.path = path
        self.cache = cache
        self._data = {}
        self._load()

    def get(self, key, default=None):
        self._ensure_loaded()
        return self._data.get(key, default)

    def _load(self): ...
    def _ensure_loaded(self): ...
```

### 使用方式

```python
# 正常使用：只接触 Declaration
decl = ConfigLoader(path="/x", cache=False)
decl.get("key")          # Declaration 方法 → 桥接到 ConfigLoaderImpl.get()

# 需要触碰实现细节时：使用模块级 API
impl = mutobj.implementation_of(decl, ConfigLoaderImpl)
impl._data
impl._load()
```

## 方法自动注册与桥接

`Implementation` 通过 `__init_subclass__` 钩子在子类定义完成时扫描子类 namespace，并把匹配的 Impl 方法自动注册为 Declaration 方法实现。

### 注册规则

| 条件 | 行为 |
|------|------|
| Impl 方法名在 Declaration 的声明方法集合中 | 自动注册桥接实现 |
| Impl `__init__` | 作为普通方法处理：若 Decl 有独立 `__init__` 覆盖链入口，则自动注册到 `Decl.__init__` |
| Impl `__post_init__` | 作为普通方法处理：若 Decl 有独立 `__post_init__` 覆盖链入口，则自动注册到 `Decl.__post_init__` |
| Impl 方法名不在 Decl 声明集合中，且不是构造相关入口 | 不注册，保留为 Impl 私有/内部方法 |
| Impl 方法名匹配但签名不一致 | 第一版不强校验，运行时报错；lint 后续拦截 |
| Python/框架保留 dunder，如 `__new__`、`__init_subclass__`、`__class_getitem__` | 不注册 |

重点：`__init__`、`__post_init__` 不再拥有一套独立特殊规则。它们和普通方法一样进入覆盖链。唯一特殊的是：**构造期间要先分配并关联 Impl 实例，确保 `Decl.__init__` 执行时已经能找到 Impl。**

### 桥接函数

每个自动注册的方法会创建一个桥接包装函数，等价于：

```python
def bridge(decl, *args, **kwargs):
    impl = mutobj.implementation_of(decl, ImplCls)
    if impl is None:
        raise RuntimeError(...)
    return impl_method(impl, *args, **kwargs)
```

所以：

```text
decl.method(args)
  → Decl.method 覆盖链当前实现
  → bridge(decl, args)
  → impl = implementation_of(decl, ImplCls)
  → ImplCls.method(impl, args)
```

## 构造流水线

### 推荐流水线

构造顺序应调整为：

```text
DeclarationMeta.__call__(Decl, *args, **kwargs):
    decl = Decl.__new__(Decl, *args, **kwargs)

    # 只分配并登记 Impl，不调用 Impl.__init__
    if Decl 注册了 Implementation 子类:
        impl = ImplCls.__new__(ImplCls)
        _bind_decl_and_impl(decl, impl)   # 外部 registry，非 impl.owner

    # 下面都走普通覆盖链/桥接规则
    Decl.__init__(decl, *args, **kwargs)
    decl.__post_init__()

    return decl
```

注意：

- `ImplCls.__new__` / registry 绑定发生在 `Decl.__init__` 之前。
- 框架不会在 `Decl.__init__` 之后额外直接调用 `ImplCls.__init__`。
- 如果 `Impl.__init__` 被自动注册，它就是 `Decl.__init__` 覆盖链上的一个普通实现。
- 如果 `Impl.__post_init__` 被自动注册，它就是 `Decl.__post_init__` 覆盖链上的一个普通实现。
- 是否执行链下一级实现，由当前实现是否调用 `mutobj.impl_call_super(...)` 决定。

### 为什么 Impl 要先于 Decl.__init__ 分配？

因为下面这些合法场景都要求 `Decl.__init__` 期间已经能找到 Impl：

```python
@mutobj.impl(Config.__init__)
def init(self: Config, path: str):
    impl = mutobj.implementation_of(self, ConfigImpl)
    impl.path = path
```

以及：

```python
class Config(mutobj.Declaration):
    def __init__(self, path: str):
        self.path = path
        self.load()      # load 可能已经桥接到 Impl.load
```

如果 Impl 在 `Decl.__init__` 之后才创建，这两类代码都会失败。

## `__init__` 三类情况的调用顺序

### 1. Decl 没有手写 `__init__`

```python
class Config(mutobj.Declaration):
    path: str
    cache: bool = True
```

框架应为每个 Declaration 子类准备一个独立的 `__init__` 覆盖链入口，链底默认行为等价于：

```python
def Config.__init__(self, *args, **kwargs):
    return Declaration.__init__(self, *args, **kwargs)
```

#### 1.1 Impl 也没有 `__init__`

调用顺序：

```text
Config.__new__
  → 设置字段默认值，例如 cache=True

Impl.__new__ + 外部 registry 绑定

Config.__init__
  → 链底默认实现
  → Declaration.__init__ 字段参数绑定

Config.__post_init__
```

结果：

- Decl 字段正常绑定。
- Impl 实例存在，但没有被 `__init__` 初始化。
- Impl 可在后续方法中懒初始化状态。

#### 1.2 Impl 定义了 `__init__`

```python
class ConfigImpl(mutobj.Implementation[Config]):
    def __init__(self, path, cache=True):
        self.path = path
        self.cache = cache
```

调用顺序：

```text
Config.__new__
Impl.__new__ + 外部 registry 绑定

Config.__init__
  → bridge
  → ConfigImpl.__init__(impl, path, cache=True)

Config.__post_init__
```

此时 `ConfigImpl.__init__` 是 `Config.__init__` 的当前实现。默认字段绑定不会自动并列执行；如果需要，Impl 必须显式调用 super chain：

```python
class ConfigImpl(mutobj.Implementation[Config]):
    def __init__(self, path, cache=True):
        owner = mutobj.implementation_owner(self)
        mutobj.impl_call_super(Config.__init__, owner, path, cache=cache)

        self.path = path
        self.cache = cache
```

### 2. Decl 手写了 `__init__`

```python
class Config(mutobj.Declaration):
    path: str

    def __init__(self, path: str):
        self.path = path
```

#### 2.1 Impl 没有 `__init__`

调用顺序：

```text
Config.__new__
Impl.__new__ + 外部 registry 绑定
Config.__init__(decl, path)      # Decl 手写实现
Config.__post_init__(decl)
```

因为 Impl 已经提前绑定，Decl 手写 `__init__` 中可以安全调用：

```python
impl = mutobj.implementation_of(self, ConfigImpl)
```

或者调用其他已经桥接到 Impl 的方法。

#### 2.2 Impl 也定义了 `__init__`

```python
class ConfigImpl(mutobj.Implementation[Config]):
    def __init__(self, path):
        self.path = path
```

调用顺序：

```text
Config.__new__
Impl.__new__ + 外部 registry 绑定

Config.__init__(decl, path)
  → bridge
  → ConfigImpl.__init__(impl, path)

Config.__post_init__(decl)
```

Decl 手写的 `Config.__init__` 变成覆盖链下一级，不会自动执行。若需要复用：

```python
class ConfigImpl(mutobj.Implementation[Config]):
    def __init__(self, path):
        owner = mutobj.implementation_owner(self)
        mutobj.impl_call_super(Config.__init__, owner, path)
        self.path = path
```

### 3. 使用 `@impl(Decl.__init__)`

```python
class Config(mutobj.Declaration):
    path: str

    def __init__(self, path: str): ...

@mutobj.impl(Config.__init__)
def init(self: Config, path: str):
    impl = mutobj.implementation_of(self, ConfigImpl)
    impl.path = path
```

调用顺序：

```text
Config.__new__
Impl.__new__ + 外部 registry 绑定

Config.__init__(decl, path)
  → @impl(Config.__init__) 当前链顶实现

Config.__post_init__(decl)
```

因为 Impl 已经提前绑定，`@impl(Config.__init__)` 中可以安全访问 Impl。

### 4. `Impl.__init__` 和 `@impl(Decl.__init__)` 同时存在

二者不应被理解为两个独立初始化阶段，而是同一条 `Decl.__init__` 覆盖链上的两个实现：

```text
Config.__init__ 覆盖链：
  chain[0] = Decl 类体里的默认/手写 __init__
  chain[1] = ConfigImpl.__init__ 自动桥接实现
  chain[2] = @impl(Config.__init__) 显式实现
```

实际执行链顶实现。链下一级是否执行，由当前实现是否调用 `mutobj.impl_call_super(...)` 决定。

因此不会出现下面这种隐式双执行：

```text
@impl(Config.__init__) 执行
ConfigImpl.__init__ 再自动执行
```

这条规则保证 `__init__` 与普通方法一致。

## `__post_init__` 的统一规则

`__post_init__` 也按普通声明方法处理。

如果 Impl 定义：

```python
class ConfigImpl(mutobj.Implementation[Config]):
    def __post_init__(self):
        ...
```

则等价于自动注册：

```python
@mutobj.impl(Config.__post_init__)
def bridge_post_init(self: Config):
    impl = mutobj.implementation_of(self, ConfigImpl)
    return ConfigImpl.__post_init__(impl)
```

构造顺序：

```text
Config.__new__
Impl.__new__ + 外部 registry 绑定
Config.__init__
Config.__post_init__
  → bridge
  → ConfigImpl.__post_init__(impl)
```

若需要执行 Decl 的 `__post_init__` 链下一级：

```python
class ConfigImpl(mutobj.Implementation[Config]):
    def __post_init__(self):
        owner = mutobj.implementation_owner(self)
        mutobj.impl_call_super(Config.__post_init__, owner)
        ...
```

## 关联生命周期

### Registry

建议使用外部 registry 保存关联，不污染 Impl 实例命名空间：

```python
_impl_instance_registry: weakref.WeakKeyDictionary[Declaration, object]
_impl_class_registry: dict[type[Declaration], type]
_impl_owner_registry: internal id/weakref mapping
```

语义：

- `_impl_instance_registry[decl] = impl`：Declaration 实例到 Impl 实例。
- `implementation_class(decl_or_cls)`：Declaration 类/实例到 Impl 类。
- `implementation_of(decl, impl_cls=None)`：Declaration 实例到 Impl 实例。
- `implementation_owner(impl)`：Impl 实例到 Declaration 实例。

### 为什么不写 `impl.owner = decl`？

因为迁移前的普通类可能已经有业务含义的 `owner`：

```python
class OldClass:
    def __init__(self, owner):
        self.owner = owner
```

如果框架占用 `owner`，迁移后就会改变原类语义。因此框架不得向 Impl 实例写入 `owner`。

### 生命周期

- Declaration 构造时，框架自动分配 Impl 并写入外部 registry。
- Declaration 被 GC 回收时，对应 Impl 关联自动释放。
- `mutobj.implementation_of(decl)` 不存在时返回 `None`。
- 第一版不提供 `get_or_create` 语义，避免为 Impl 构造参数分发引入第二套规则。

## Impl 继承规则

一个 Declaration 子类**至多一个** Implementation 子类。当 Declaration 存在继承关系时：

```text
ConfigLoader              ←──→  ConfigLoaderImpl
    ↑                                ↑（必须继承）
AdvancedLoader            ←──→  AdvancedLoaderImpl
```

| # | 规则 |
|---|------|
| 1 | `Implementation[Decl]` 子类自动注册到 Decl，一个 Decl 至多一个 Impl |
| 2 | 子类 Decl 要提供自己的 Impl，必须继承父类 Decl 的 Impl |
| 3 | `AdvancedLoaderImpl.__init__` 可通过 Python 原生 `super().__init__()` 协作继承 Impl 状态初始化 |
| 4 | Declaration 覆盖链 super 使用 `mutobj.impl_call_super(...)`；Impl 类继承 super 使用 Python `super()`，二者不要混淆 |

理由：子类 Decl 继承了父类 Decl 的公开方法。父类公开方法桥接到子类 Impl 时，子类 Impl 必须继承父类 Impl 的同名业务方法，否则运行时报 `AttributeError`。

```python
# ✓ 正确：AdvancedLoaderImpl 继承 ConfigLoaderImpl，因此拥有 get()
class AdvancedLoaderImpl(ConfigLoaderImpl[AdvancedLoader]):
    ...

# ✗ 不推荐：AdvancedLoader 继承了 ConfigLoader.get，
# 但 AdvancedLoaderImpl 没有 get，桥接后会炸
class AdvancedLoaderImpl(mutobj.Implementation[AdvancedLoader]):
    ...
```

具体语法（`ConfigLoaderImpl[AdvancedLoader]` 还是多重继承）由实现复杂度决定。

## 与 Extension 的对比

| | Extension | Implementation |
|------|-----------|----------------|
| 与 Decl 继承关系 | 不继承 | 不继承 |
| 关联方向 | `ext.target → decl` | 外部 registry，Impl 实例不注入 `owner` |
| 获取实例 | `Ext.get_or_create(decl)` | `mutobj.implementation_of(decl, ImplCls)` |
| 创建时机 | 手动 `get_or_create` | Declaration 构造时自动分配 |
| 是否可选 | 偏可选扩展 | 主实现类，通常随 Decl 创建 |
| 状态独立性 | ✓ 独立 `__dict__` | ✓ 独立 `__dict__` |
| 私有属性 | ✓ | ✓ |
| 会占用的公开名字 | `get` / `get_or_create` / `target` 等 | 不占用 Impl 公开方法名；不注入 `owner` |
| 方法注册 | 手动 `@impl` | 自动扫描匹配 |
| 定位 | 附加可选状态（关注点分离） | 普通类迁移桥接层 / 主实现类 |

## 暂不纳入的设计（后续子设计）

以下内容不在本次范围，留作后续 spec：

- **字段桥接**：Declaration 字段声明自动桥接到 Impl 属性，使 `decl.path = "/x"` 等同于 `impl.path = "/x"`。
- **property 自动注册**：Impl 上的 `@property` 自动匹配 Declaration 上声明的 property。
- **Decl 与 Impl 的 `__init__` 签名一致性校验**：lint 规则，不纳入框架第一版实现。
- **额外方法校验**：Impl 上未匹配 Declaration 且非 `_` 前缀的方法，暂不报错（宽松模式）。
- **lint 规则**：方法签名不匹配检测、Impl 继承关系检测、重复 Impl 检测等。
- **手动创建 Impl**：第一版不提供 `get_or_create`，避免构造参数分发规则复杂化。

## 实施决议

### 默认字段绑定与 `Impl.__init__`

若 Decl 未手写 `__init__`，框架默认链底会执行 `Declaration.__init__` 字段绑定。但一旦 `Impl.__init__` 自动注册成为链顶，默认字段绑定不会自动并列执行，除非 Impl 显式：

```python
owner = mutobj.implementation_owner(self)
mutobj.impl_call_super(Decl.__init__, owner, *args, **kwargs)
```

已按“统一覆盖链规则”实现：`Impl.__init__` 成为 `Decl.__init__` 覆盖链的一环。需要保留字段绑定时，Impl 侧显式调用 `mutobj.impl_call_super(Decl.__init__, owner, ...)`。

### 显式 `@impl(Decl.__init__)` 与 `Impl.__init__` 的同模块共存

概念上二者属于同一覆盖链。但当前 `_register_to_chain` 以模块为 reload 稳定键，同一模块对同一方法多次注册会发生替换语义。实现时需要决定：

已采用方案 2：Implementation 自动桥接使用 `module::implementation::qualname` 形式的独立 source key，`impl_call_super` 也改为优先按调用中的真实函数解析 source key，因此显式 `@impl(...)` 与 `Impl.__init__` / `Impl.method` 可在同模块共存并正常走 super 链。

### `implementation_owner(impl)` 的反向映射实现

为了不写 `impl.owner`，需要外部反向映射。候选实现：

- `WeakKeyDictionary[impl, decl]`：简单，但要求 Impl 实例可 weakref；若迁移类使用 `__slots__` 且无 `__weakref__` 会失败。
- `id(impl) -> weakref.ref(decl)`：不要求 Impl 可 weakref，但需要在 Decl GC 时清理，避免 id 复用风险。

已实现 `id(impl) -> weakref.ref(decl)`，并在 Declaration 侧挂 `weakref.finalize(...)` 自动清理反向索引，避免向 Impl 注入 `owner` 属性，也不要求 Impl 支持 weakref。

### 一个 Decl 多个 Impl

一个 Declaration 能否同时注册多个 `Implementation[Decl]` 子类？

已实现为**不允许**。一个 Declaration 至多一个 Impl；重复注册会抛 `TypeError`。同时，子类 Declaration 若定义自己的 Impl，必须继承父类 Declaration 已注册的 Impl，保证继承来的公开方法桥接到的业务方法仍然可用。

## 实施步骤清单

- [x] 新增 `Implementation[T]` 基类与 `implementation_class` / `implementation_of` / `implementation_owner` 模块级 API
- [x] 在 `DeclarationMeta.__call__` 中于 `Decl.__init__` 前分配并绑定 Impl 实例
- [x] 为 Declaration 子类提供独立 `__init__` 覆盖链入口，并自动桥接 Implementation 同名方法
- [x] 为同模块 `@impl(...)` + Implementation bridge 共存、继承约束、注销行为补齐回归测试
