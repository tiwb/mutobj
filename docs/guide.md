# mutobj 使用指南

mutobj 让你把类的 **数据结构**、**方法契约**、**方法实现** 和 **附加私有状态** 拆开组织：

- `Declaration` —— 类的数据结构与方法契约
- `@impl` —— 注册或覆盖方法实现
- `Extension` —— 给 Declaration 实例附加私有状态
- `Implementation` —— 把整组实现集中到一个独立类里（可选）

每一章只覆盖核心用法。完整 API 以 `mutobj.__all__` 为准，签名细节看对应方法的签名和函数文档。

---

## 1. Declaration — 数据与契约

### 最小示例

```python
import mutobj

class User(mutobj.Declaration):
    name: str
    email: str
    age: int = 0
    tags: list[str] = mutobj.field(default_factory=list[str])

    def greet(self) -> str:
        return f"Hello, I'm {self.name}!"

u = User(name="Alice", email="a@b.com", age=25)
u.greet()
```

### 1.1 字段

字段由**类型注解**决定（无注解的等号赋值会被拒绝，类级数据必须用 `ClassVar[...]` 声明）：

```python
from typing import ClassVar

class Config(mutobj.Declaration):
    # 实例字段
    host: str                                              # 必填
    port: int = 8080                                       # 不可变默认值，直接写
    api_key: str | None = None
    tags: list[str] = mutobj.field(default_factory=list)   # 可变默认值必须 field()
    counter: int = mutobj.field(default=0, init=False)     # 不进 __init__
    # 类级共享属性
    instances: ClassVar[int] = 0                            # 所有实例共享
```

规则：

- 可变类型（`list/dict/set/bytearray`）**禁止直接赋值**作为默认值，必须 `field(default_factory=...)`，否则抛 `TypeError`
- 字段顺序按 MRO，基类在前
- `init=False` 的字段不进 `__init__` 参数列表，但必须在 `__post_init__` 前赋值，否则构造完成后抛 `TypeError`
- 子类可用同名注解覆盖父类默认值（类型须与父类一致，注解可省略则沿用父类类型）。类型一致性由 pyright / mutobj-lint 静态保证，mutobj 不作运行时校验
- 必填字段（无默认值）在构造完成后仍未赋值会抛 `TypeError`

**ClassVar — 类级共享属性**：

需要类级共享属性（启动期注入的全局引用、共享缓存）时，用 `typing.ClassVar`：

| 写法 | `Cls.x` | `inst.x` | `Cls.x = v` |
|------|---------|----------|-------------|
| `x: ClassVar[T] = v` | 返回值 | 走类属性回落 | 立刻对所有实例生效 |
| `x: T = v`（实例字段） | 返回 `FieldInfo` | 实例自己的值 | 重建描述符 default，老实例不变 |

- ClassVar 不参与 `__init__`，不进字段反射
- 子类同名属性可覆盖默认值，类型须与父类一致（注解可省略）
- 循环 import 时配合 `TYPE_CHECKING` 用字符串 forward ref，运行时行为一致

```python
# 子类覆盖 ClassVar
class Base(mutobj.Declaration):
    default_size: ClassVar[int] = 100

class Child(Base):
    default_size: ClassVar[int] = 200   # ✅ 覆盖默认值，类型一致
    # default_size = 50                 # ✅ 省略注解，沿用父类类型
    # default_size: ClassVar[str] = "x" # ❌ 类型不一致，pyright 报错
```

### 1.2 `__init__` 与 `__post_init__`

**`__init__`** 默认按字段顺序接受位置参数和关键字参数（仅 `init=True` 的字段）。自定义构造逻辑时用 `@mutobj.impl(Cls.__init__)` 覆盖——与 dataclass 不同，mutobj 的 `__init__` 是普通方法，可自由覆盖。

**`__post_init__`** 字段绑定完成后由元类**强制**调用。即使用户自定义 `__init__` 没调 `super().__init__()`，`__post_init__` 也会触发：

```python
class Box(mutobj.Declaration):
    width: float
    height: float
    area: float = 0.0

    def __post_init__(self) -> None:
        self.area = self.width * self.height
```

`__post_init__` 是**唯一可以无桩 @impl 的 dunder**——可以直接在实现文件 `@impl(Box.__post_init__)`，Declaration 不需要写桩。其他 dunder（含 `__init__`）仍要求 Declaration 上有声明。

### 1.3 方法签名

普通方法、`@property`、`@classmethod`、`@staticmethod` 都支持：

```python
from typing import Self

class Product(mutobj.Declaration):
    name: str
    price: float = 0.0

    def discounted(self, ratio: float) -> float:
        ...

    @property
    def tax(self) -> float: ...

    @classmethod
    def from_dict(cls, data: dict) -> Self: ...

    @staticmethod
    def validate_name(name: str) -> bool: ...
```

方法体可以是 `...`（桩）或真实代码（默认实现）。`...` 桩没有任何特殊处理——直接调用返回 `None`，仅表达「该方法的实现在别处用 `@impl` 注册」的契约意图。`impl_call_super` 在链底会抛 `NotImplementedError`，而非调用桩体本身。两种风格的取舍见 [§4 两种使用模式](#4-两种使用模式）。

### 1.4 继承

```python
class Animal(mutobj.Declaration):
    name: str
    def speak(self) -> str: ...

class Dog(Animal):
    breed: str
    # speak 不重新声明 → 委托到 Animal 的覆盖链
    # 但仍可 @impl(Dog.speak) 创建独立覆盖链
```

- 子类不重新声明的方法：**自动委托**到父类当前的实现链顶，父类换实现子类立即生效
- 子类可随时用 `@impl(SubCls.method)` 创建独立覆盖链，无需重新声明
- 子类重新声明的方法：拥有**独立的覆盖链**，与父类链解耦。适用于需要独立契约语义的场景

```python
class Cat(Animal):
    def speak(self) -> str: ...   # 重新声明 = Cat 上独立的覆盖链
                                  # @impl(Animal.speak) 不影响 Cat
```

---

## 2. @impl — 方法实现

### 2.1 注册

```python
@mutobj.impl(User.greet)
def user_greet(self: User) -> str:
    return f"Hello, {self.name}"
```

- 目标方法**必须存在于 Declaration 上**
- `@impl` **没有** `override` 参数。多次注册自动构成**覆盖链**，最后注册的为活跃实现

### 2.2 命名约定

`@impl` 函数名不影响运行时（按目标方法句柄匹配，不依赖名字），但约定如下，以保持代码可读性，并可被 `mutobj-lint` 自动检查：

```python
# 函数名 = snake_case(类型名) + "_" + 方法名
@mutobj.impl(MessageList.render)
def message_list_render(self: MessageList) -> View: ...

@mutobj.impl(JSONResponse.__init__)
def json_response_init(self, content, status=200) -> None: ...
```

类名转小写蛇形：`MessageList` → `message_list`、`WebSocketConnection` → `web_socket_connection`。

### 2.3 调用上一级实现 `impl_call_super`

类似继承中的 `super().method()`，调用覆盖链上前一层实现：

```python
# base_impl.py
@mutobj.impl(Service.process)
def service_process_base(self: Service, x: int) -> int:
    return x * 2

# logging_impl.py —— 后注册，包一层日志
@mutobj.impl(Service.process)
def service_process_logged(self: Service, x: int) -> int:
    result = mutobj.impl_call_super(Service.process, x)
    logger.info("process(%s) = %s", x, result)
    return result
```

- 链底（上一级是 Declaration 自身桩）抛 `NotImplementedError`
- caller 不在该方法的覆盖链中抛 `RuntimeError`
- 支持普通方法、async、property accessor、classmethod、staticmethod

### 2.4 卸载

```python
mutobj.impl_unregister("mypkg._user_impl")
```

- 卸载活跃实现 → 恢复链上一层
- 卸载中间层 → 活跃实现不变
- 全部卸载 → 恢复 Declaration 自身的方法体
- 同模块 reload 时，链中位置不变（就地替换）

### 2.5 元数据 `impl_meta`

`@impl` 第二个参数起的位置参数都作为这次注册的元数据（任意 Python 对象，mutobj 不强制基类）：

```python
class Stub: pass     # marker

@mutobj.impl(Action.execute, Stub())
def action_execute_stub(self, ctx):
    raise NotImplementedError(...)

# 下游查询
if mutobj.impl_meta_of(Action.execute, Stub) is not None:
    ...   # 当前活跃实现是 stub
```

- `impl_meta(method)` 返回链顶 impl 的 metas tuple
- `impl_meta_of(method, T)` 返回首个 `isinstance(_, T)` 的 meta，未命中返回 None
- 子类未 override 时 delegate 透明转发——能拿到父类链顶的 meta

### 2.6 内省

| 调用 | 用途 |
|------|------|
| `impl_chain(method)` | 返回完整覆盖链 `list[ImplChainInfo]`，含 `func` 与 `source_module` |
| `impl_has_override(method)` | 当前类是否有外部 `@impl`（区别于声明默认实现） |
| `impl_is_own(method)` | 当前类自己有 @impl（不是从父类委托过来的） |
| `impl_is_inherited(method)` | 当前类的实现来自父类委托 |

### 2.7 Property accessor

```python
class Product(mutobj.Declaration):
    @property
    def tax(self) -> float: ...

@mutobj.impl(Product.tax.getter)
def product_tax_getter(self: Product) -> float:
    return self.price * 0.08

@mutobj.impl(Product.tax.setter)
def product_tax_setter(self: Product, v: float) -> None:
    ...
```

`Cls.field.getter` / `Cls.field.setter` 对 `@property` 和普通字段（`xxx: str`）**同样适用**——两者在 mutobj 内部都是 `AttributeDescriptor`，统一走 `.getter` / `.setter` 覆盖。

---

## 3. Extension — 附加私有状态

Declaration 定义"这个类型是什么"，Extension 表达"某个子系统需要为该类型记住什么"。两者关注点不同——日志计数、缓存、UI 装饰这类**私有数据**进 Extension，不进 Declaration。

```python
class UserCache(mutobj.Extension[User]):
    hit_count: int = 0
    payloads: dict[str, bytes] = mutobj.field(default_factory=dict)

@mutobj.impl(User.greet)
def user_greet(self: User) -> str:
    cache = UserCache.get_or_create(self)
    cache.hit_count += 1
    return f"Hello, {self.name}! (访问 {cache.hit_count} 次)"
```

API：

| 调用 | 用途 |
|------|------|
| `Ext.get_or_create(instance)` | 不存在则创建，最常用 |
| `Ext.get(instance)` | 查询，不存在返回 `None` |
| `mutobj.extensions(instance, filter_type=None)` | 枚举实例上**已创建**的 Extension |
| `mutobj.extension_types(decl_class, filter_type=None)` | 查询某 Declaration 类**注册过**的 Extension 类型 |
| `mutobj.extension_base(ext_class)` | 取 Extension 绑定的 Declaration 基类（`Extension[T]` 中的 T） |

要点：

- Extension 字段同样用 `field(default_factory=...)` 声明可变默认值
- `self.target` 取宿主 Declaration 实例（不会自动代理属性，访问宿主字段写 `self.target.name`）
- Extension 实例随宿主一起消亡
- 同实例 + 同 Extension 类型只会创建一次（按 instance 缓存）
- 一个 Declaration 可挂多种 Extension

---

## 4. 两种使用模式

### 模式 A：声明自带默认实现

Declaration 的方法体写真实代码，类自己就能跑。`@impl` 只在需要覆盖默认行为时才出现。

```python
class User(mutobj.Declaration):
    name: str
    age: int = 0

    def greet(self) -> str:
        return f"Hello, {self.name}"

    def is_adult(self) -> bool:
        return self.age >= 18
```

**适用场景**：业务对象、工具类、内部数据结构。和写普通 Python 类几乎一样，只是字段声明更严格、运行时拥有 schema。

### 模式 B：声明即契约

Declaration 上方法**全部是桩** `...`，自身不做任何事。所有实现外置。

```python
# storage.py —— 纯契约
class Storage(mutobj.Declaration):
    name: str

    def put(self, key: str, value: bytes) -> None: ...
    def get(self, key: str) -> bytes | None: ...
    def delete(self, key: str) -> None: ...

from . import _storage_impl as _storage_impl   # noqa: F401
```

**适用场景**：声明文件本身要作为公开 API 文档；需要清晰的契约-实现边界。

外置实现有两种载体：

#### 4B-1. 自由函数 `@impl`（推荐起点）

```python
# _storage_impl.py
@mutobj.impl(Storage.put)
def storage_put(self: Storage, key: str, value: bytes) -> None:
    ...

@mutobj.impl(Storage.get)
def storage_get(self: Storage, key: str) -> bytes | None:
    ...
```

最直接的写法。每个方法是一个独立函数，行为可被进一步覆盖、可热重载。

#### 4B-2. `Implementation[T]` 类

把整组实现收进一个类里。**主要用于把已有的普通 Python 类渐进式迁移到 mutobj**：保留原类绝大部分代码，只在头部把基类换成 `Implementation[NewDecl]`，每一步小改动都能跑起来。

```python
# storage.py —— 公开声明
class Storage(mutobj.Declaration):
    name: str
    def put(self, key: str, value: bytes) -> None: ...
    def get(self, key: str) -> bytes | None: ...

# _storage_impl.py —— 实现集中在一个类里
class StorageImpl(mutobj.Implementation[Storage]):
    # 实现自己的字段，独立于 Declaration 字段
    _backend: dict[str, bytes] = mutobj.field(default_factory=dict)

    def __init__(self, name: str) -> None:
        # Storage(name=...) 实际走这里
        owner = mutobj.implementation_owner(self)
        owner.name = name

    def put(self, key: str, value: bytes) -> None:
        self._backend[key] = value

    def get(self, key: str) -> bytes | None:
        return self._backend.get(key)
```

要点：

- `Implementation[T]` 的方法**自动**桥接到 Declaration 的 @impl 链（不需要给每个方法写 `@impl`）
- Impl 类可以有自己的字段，存储在自己的实例上，与 Declaration 字段分离
- Impl 内部用 `mutobj.implementation_owner(self)` 取宿主 Declaration 实例
- 一个 Declaration 类全局只能注册一个 Implementation 类
- 反向查询：`mutobj.implementation_class(Storage)` / `mutobj.implementation_of(decl_inst, StorageImpl)`

### 怎么选

| 场景 | 选 |
|------|-----|
| 内部数据结构、行为简单 | 模式 A |
| 公开 API、声明即文档、多实现可替换 | 模式 B 自由函数 |
| 把已有的普通类迁进 mutobj，想最小改动 | 模式 B Implementation |

---

## 5. 工具与约定

### 5.1 文件命名

实现文件取决于是否对外公开：

- `_xxx_impl.py`（下划线前缀）—— 私有实现，"不要 import 我的内容，只是为了触发 @impl 注册"
- `xxx_impl.py`（不带下划线）—— 可被外部直接引用

私有实现配合一行末尾导入：

```python
# user.py 末尾
from . import _user_impl as _user_impl   # noqa: F401
```

`as _user_impl` 是为避开 IDE 的 unused-import 警告。

### 5.2 类发现与解析

```python
mutobj.discover_subclasses(Storage)            # 列举已注册的子类
mutobj.resolve_class("PostgresStorage")        # 短名解析
mutobj.resolve_class("mypkg.pg.PostgresStorage", base_cls=Storage)  # 全路径，自动 import
mutobj.get_registry_generation()               # 当前注册表代号，用于缓存失效判断
```

适合"配置里写类路径，运行时按需加载"的扩展模式 —— 不写就不 import，零开销。

### 5.3 字段反射

```python
for name, info in mutobj.fields(User).items():
    print(name, info.annotation, info.has_default)
    if info.has_default:
        print("default:", info.make_default())
```

- `mutobj.fields(cls)` 返回 `Mapping[str, FieldInfo]`，按 MRO 排序，子类同名字段覆盖父类
- `FieldInfo` 提供 `name` / `annotation` / `init` / `has_default` / `make_default()` / `getter` / `setter`
- 类级访问 `Cls.field_name` 也直接返回该字段的 `FieldInfo`

声明默认值与原始函数对象的内省：

- `mutobj.get_declaration_func(cls, method_name)` —— 取声明里写的原始函数对象（沿 MRO 查找）
- `mutobj.get_declaration_doc(cls, method_name)` —— 同步取声明的 docstring

### 5.4 mutobj-lint

静态检查 `@impl` 风格：

- **R001**：识别 `...` / `pass` / `yield ...` 桩方法
- **R002**：检查末尾 `from . import _xxx_impl as _xxx_impl` 写法 + `noqa: F401`
- **R003**：`@impl` 函数命名规范（禁止 `_` 前缀 + 强制类型名前缀）

```bash
mutobj-lint                # 默认读 pyproject.toml 配置或 cwd
mutobj-lint src/ tests/    # 显式指定路径
```
