# mutobj 使用指南

mutobj 让你把类的**字段声明**、**接口签名**、**方法实现**和**附加私有状态**分四种位置组织：

- `Declaration` 子类 —— 像 dataclass 一样声明字段，像 abstract class 一样声明接口
- `@impl` —— 在另一个文件里提供方法实现，可被覆盖、可热重载
- `Extension[T]` —— 为某个 Declaration 类型附加私有状态，不污染公开声明
- `field(...)` —— 字段元数据（默认值、可变默认工厂、是否进 `__init__`）

---

## 最小示例

**声明文件 `user.py`**

```python
import mutobj

class User(mutobj.Declaration):
    name: str
    email: str
    age: int = 0
    tags: list[str] = mutobj.field(default_factory=list)

    def greet(self) -> str: ...
    def is_adult(self) -> bool: ...

from . import _user_impl as _user_impl  # 末尾导入实现，触发 @impl 注册
```

**实现文件 `_user_impl.py`**

```python
import mutobj
from .user import User

@mutobj.impl(User.greet)
def greet(self: User) -> str:
    return f"Hello, I'm {self.name}!"

@mutobj.impl(User.is_adult)
def is_adult(self: User) -> bool:
    return self.age >= 18
```

**使用**

```python
from mypkg.user import User

u = User(name="Alice", email="a@b.com", age=25)   # 关键字
u = User("Alice", "a@b.com", 25)                  # 位置参数也行
print(u.greet(), u.is_adult())
```

---

## 字段声明（dataclass 风格）

`Declaration` 的字段语义和 `@dataclass` 几乎一致：

```python
class Config(mutobj.Declaration):
    host: str                                              # 必填
    port: int = 8080                                       # 不可变默认值，直接写
    api_key: str | None = None
    tags: list[str] = mutobj.field(default_factory=list)   # 可变默认值，必须 field()
    headers: dict[str, str] = mutobj.field(default_factory=dict)
    _internal: int = mutobj.field(default=0, init=False)   # 不进 __init__
```

**规则**：

- 类型注解决定字段身份（无注解的等号赋值不算字段，按类属性处理）
- 可变类型（`list/dict/set/bytearray`）**禁止直接赋值**，否则抛 `TypeError`，必须 `field(default_factory=...)`
- 字段顺序按 MRO，基类在前，子类在后
- `field(init=False)` 的字段在构造时只用默认值，不接受 `__init__` 参数
- 子类可用同名注解（或同名等号赋值）覆盖父类默认值

**`__post_init__`**：所有字段绑定完后自动调用，做派生计算。

```python
class Box(mutobj.Declaration):
    width: float
    height: float
    area: float = 0.0

    def __post_init__(self) -> None:
        self.area = self.width * self.height
```

---

## @impl 实现

```python
@mutobj.impl(User.greet)
def greet(self: User) -> str:
    return f"Hello, {self.name}"
```

- 目标方法**必须存在于 Declaration 上**，方法体可以是 `...`、`pass` 或真实代码（作为默认实现）
- `@impl` **没有** `override` 参数。多次注册自动构成**覆盖链**，最后注册的为活跃实现
- 卸载活跃实现自动恢复链上一层；全部卸载恢复 Declaration 自身的方法体

```python
mutobj.unregister_module_impls("mypkg._user_impl")
```

---

## 三种构造方式 —— 选哪个

mutobj 0.7 之后，构造逻辑可以放在三处，按场景选：

**1) 纯字段，依赖默认 `__init__`**（最常用，dataclass 风格）

```python
class Request(mutobj.Declaration):
    method: str = "GET"
    path: str = "/"
    headers: dict[str, str] = mutobj.field(default_factory=dict)
```

字段都通过 `field()`/类型注解声明，不用写 `__init__`。

**2) 自定义 `__init__` + `super().__init__()`**（业务对象、构造逻辑较复杂）

```python
class DockPanel(View):
    def __init__(self, id: str, panels: list[PanelDef], layout: LayoutNode) -> None:
        super().__init__()                       # 必须调用，触发字段默认值绑定
        self.id = id
        self.panels = {p.id: p for p in panels}
        self.layout = layout
```

子类自由控制构造，**记得调用 `super().__init__()`**，否则字段默认值不会被设置。

**3) `@impl(Cls.__init__)` 注入构造逻辑**（声明文件想保持纯净，把行为搬到实现文件）

```python
# response.py
class JSONResponse(Response):
    def __init__(self, content: Any, status_code: int = 200) -> None: ...
    def render(self, content: Any) -> bytes: ...

# _response_impl.py
@mutobj.impl(JSONResponse.__init__)
def _init(self: JSONResponse, content: Any, status_code: int = 200) -> None:
    Response.__init__(self, status_code=status_code, body=self.render(content),
                      headers={"content-type": "application/json"})

@mutobj.impl(JSONResponse.render)
def _render(self: JSONResponse, content: Any) -> bytes:
    return json.dumps(content).encode("utf-8")
```

适合 Declaration 是公开 API、实现细节希望可替换的场景（mutio Response 全用此模式）。

---

## Extension — 附加私有状态

```python
import mutobj
from .user import User

class UserCache(mutobj.Extension[User]):
    """User 的缓存状态。"""
    hit_count: int = 0
    payloads: dict[str, bytes] = mutobj.field(default_factory=dict)

@mutobj.impl(User.greet)
def greet(self: User) -> str:
    cache = UserCache.get_or_create(self)
    cache.hit_count += 1
    return f"Hello, {self.name}! (访问 {cache.hit_count} 次)"
```

**API**：

| 调用 | 用途 |
|------|------|
| `Ext.get_or_create(instance)` | 不存在则创建，最常用（@impl 内部用） |
| `Ext.get(instance)` | 查询，不存在返回 `None`（条件检查用） |
| `mutobj.extensions(instance, filter_type=None)` | 枚举实例上已创建的 Extension |
| `mutobj.extension_types(decl_class, filter_type=None)` | 查询某 Declaration 类注册了哪些 Extension 类型 |

**约定**：

- 字段用 `mutobj.field()` 声明，可变默认值同样用 `default_factory`
- 通过 `ext.target` 拿到原 Declaration 实例（**不会**自动代理属性，要写 `ext.target.name`）
- Extension 的命名风格表达"私有性"：内部用的 Extension 一般加下划线前缀（如 `_RequestExt`），需要被业务代码引用的可以不加（如 `UserCache`）
- 一个 Declaration 实例可以挂多个不同类型的 Extension；同实例 + 同 Extension 类型只创建一次（按 instance 缓存）

---

## Property / classmethod / staticmethod

三者都支持声明-实现分离。**声明时方法体作为默认实现**，`@impl` 覆盖。

```python
# 声明
class Product(mutobj.Declaration):
    name: str
    _price: float = 0.0

    @property
    def price(self) -> float: ...

    @classmethod
    def from_dict(cls, data: dict) -> "Product": ...

    @staticmethod
    def validate_name(name: str) -> bool: ...

# 实现
@mutobj.impl(Product.price.getter)
def get_price(self: Product) -> float:
    return self._price

@mutobj.impl(Product.price.setter)
def set_price(self: Product, value: float) -> None:
    if value < 0: raise ValueError
    self._price = value

@mutobj.impl(Product.from_dict)
def from_dict(cls, data: dict) -> Product:
    return cls(name=data["name"], _price=data["price"])

@mutobj.impl(Product.validate_name)
def validate_name(name: str) -> bool:
    return len(name) >= 2 and name.isalnum()
```

---

## 继承

```python
class Animal(mutobj.Declaration):
    name: str
    def speak(self) -> str: ...

class Dog(Animal):
    breed: str
    def speak(self) -> str: ...   # 重新声明 = 在 Dog 上独立的覆盖链

@mutobj.impl(Animal.speak)
def _animal_speak(self: Animal) -> str: return f"{self.name} makes a sound"

@mutobj.impl(Dog.speak)
def _dog_speak(self: Dog) -> str: return f"{self.name} barks!"
```

子类不重新声明的方法**自动委托**到基类当前的实现链顶（基类换实现，子类立即生效）。

---

## 实现文件命名

约定取决于实现是否对外公开：

- **私有实现** → `_xxx_impl.py`（下划线前缀），表达"不要 import 我的内容，只是为了触发 @impl 注册"
- **可被外部直接引用** → `xxx_impl.py`（不带下划线）

私有写法对应一行末尾导入：

```python
# user.py 末尾
from . import _user_impl as _user_impl   # noqa: F401
```

`as _user_impl` 是为了避开 IDE 的 unused-import 警告。

---

## 覆盖链与卸载

```python
# moduleA.py
@mutobj.impl(Service.process)
def a(self: Service) -> str: return "A"

# moduleB.py —— 后注册，成为活跃实现
@mutobj.impl(Service.process)
def b(self: Service) -> str: return "B"

Service().process()                               # "B"
mutobj.unregister_module_impls("moduleB")
Service().process()                               # "A"
mutobj.unregister_module_impls("moduleA")
Service().process()                               # 默认实现（声明里的方法体）
```

**规则**：

- 卸载活跃实现 → 恢复链上一层
- 卸载中间层 → 活跃实现不变
- 全部卸载 → 恢复声明中的方法体
- 同模块 reload 时，链中位置不变（就地替换）

---

## 类发现与解析

```python
# 列举某基类的所有已注册子类（按需 import 后才在 registry 中）
mutobj.discover_subclasses(Provider)

# 通过短名或全路径解析，全路径会自动 import
mutobj.resolve_class("AnthropicProvider")
mutobj.resolve_class("mypkg.providers.anthropic.AnthropicProvider", base_cls=Provider)
```

适合"配置里写类路径，运行时按需加载"的扩展模式 —— 不写就不 import，零开销。

---

## 常见报错

| 错误 | 原因 |
|------|------|
| `TypeError: ... uses mutable default value list` | 字段直接赋了 `[]/{}/set()`，改用 `mutobj.field(default_factory=list)` |
| `NotImplementedError: Method 'xxx' is declared but not implemented` | 声明的方法体是 `...` 且没有 `@impl` 注册 —— 检查实现文件是否被 import |
| `ValueError: Cannot find class for method xxx` | `@impl(target)` 拿不到 target 所属的类，通常是 target 不是 Declaration 子类的属性 |
| `@impl(...): ambiguous target — multiple Declaration classes named X` | 多个 Declaration 同名（不同模块），target 缺 `__mutobj_class__` 标签 —— 通常是手动从外部赋值的 dunder，应在类体内定义 |
