# mutobj API Reference

## Overview

mutobj (Mutable Object) 是一个支持声明与实现分离的 Python 类定义库。

## Core API

### `mutobj.Declaration`

所有 mutobj 声明类的基类。

```python
import mutobj

class User(mutobj.Declaration):
    name: str
    age: int

    def greet(self) -> str:
        """方法声明（桩方法）"""
        ...
```

**特性：**
- 自动为类型注解的属性创建描述符
- 支持属性默认值（不可变类型直接赋值，可变类型使用 `field()`）
- 所有公开方法的原始函数保存为默认实现（`...` / `pass` / 有代码均支持）
- 支持 `@property`、`@classmethod`、`@staticmethod` 声明
- 支持通过关键字参数初始化：`User(name="Alice", age=30)`

---

### `@mutobj.impl(method)`

方法实现装饰器，用于为声明的方法提供实现。

多个模块可以为同一方法注册 `@impl`，形成覆盖链。按注册顺序排列，最后注册的为活跃实现。

**参数：**
- `method`: 要实现的方法（如 `User.greet`）

**示例：**

```python
# 普通方法实现
@mutobj.impl(User.greet)
def greet(self: User) -> str:
    return f"Hello, {self.name}!"
```

**Property 实现：**

```python
class Product(mutobj.Declaration):
    price: float

    @property
    def display_price(self) -> str:
        ...

# 实现 getter
@mutobj.impl(Product.display_price.getter)
def display_price(self: Product) -> str:
    return f"${self.price:.2f}"

# 实现 setter（可选）
@mutobj.impl(Product.display_price.setter)
def set_display_price(self: Product, value: str) -> None:
    self.price = float(value.replace("$", ""))
```

**classmethod/staticmethod 实现：**

```python
class Factory(mutobj.Declaration):
    value: int

    @classmethod
    def create(cls, v: int) -> "Factory":
        ...

    @staticmethod
    def validate(data: str) -> bool:
        ...

@mutobj.impl(Factory.create)
def create(cls, v: int) -> Factory:
    obj = cls()
    obj.value = v
    return obj

@mutobj.impl(Factory.validate)
def validate(data: str) -> bool:
    return len(data) > 0
```

**异常：**
- `ValueError`: 方法未声明
- `TypeError`: 参数类型错误

**覆盖链行为：**
- 多个模块可为同一方法注册 `@impl`，后注册者成为活跃实现
- 同模块重复注册（reload 场景）就地替换，链中位置不变
- 使用 `unregister_module_impls()` 卸载指定模块的实现

---

### `mutobj.unregister_module_impls(module_name)`

移除指定模块注册的所有 `@impl`，恢复覆盖链上一层实现。

**参数：**
- `module_name`: 来源模块的 `__name__`

**返回：**
- `int`: 被卸载的 impl 数量

**示例：**

```python
import mutobj

# 卸载模块 B 的所有实现
removed = mutobj.unregister_module_impls("myapp.module_b")
print(f"卸载了 {removed} 个实现")
```

**行为规则：**
- 活跃实现被卸载 → 恢复为链中上一层
- 中间层被卸载 → 活跃实现不变
- 全部外部 impl 卸载 → 恢复为声明中的默认实现
- 卸载不存在的模块 → 返回 0，无操作

---

### `mutobj.Extension[T]`

Extension 泛型基类，用于为 Declaration 子类提供扩展功能和私有状态。

定义 `Extension[T]` 子类时，自动注册到目标 Declaration 类型的 Extension 注册表中，可通过 `extension_types()` 查询。

```python
class UserExt(mutobj.Extension[User]):
    _counter: int = 0
    _history: list = mutobj.field(default_factory=list)

    def __init__(self):
        """可选：初始化钩子（self._instance 和 field 值均已可用）"""
        if self._instance.name:
            self._history.append(f"created for {self._instance.name}")

    def _helper(self) -> str:
        """私有辅助方法"""
        return f"Counter: {self._counter}"
```

**特性：**
- 通过 `Extension[TargetClass]` 语法绑定目标类并自动注册
- 支持私有状态（`_` 前缀属性存储在 Extension 实例上）
- 可通过 `self.attr` 访问目标实例的公共属性
- 支持 `field(default_factory=...)` 声明可变默认值
- `__init__` 中可访问 `self._instance` 和所有 field 值

---

### `Extension.get_or_create(instance)`

确保存在并返回 Extension 实例。不存在则创建，存在则返回缓存实例。

**参数：**
- `instance`: mutobj.Declaration 的实例

**返回：**
- Extension 实例（永不为 None）

**示例：**

```python
@mutobj.impl(User.greet)
def greet(self: User) -> str:
    ext = UserExt.get_or_create(self)
    ext._counter += 1
    return f"Hello, {self.name}! (called {ext._counter} times)"
```

---

### `Extension.get(instance)`

查询 Extension 实例，不存在返回 None。

**参数：**
- `instance`: mutobj.Declaration 的实例

**返回：**
- 已缓存的 Extension 实例，或 `None`

**示例：**

```python
def maybe_use_cache(user: User) -> str | None:
    ext = UserCacheExt.get(user)
    if ext is not None:
        return ext._cached_result
    return None
```

---

### `mutobj.extensions(instance, filter_type=None)`

枚举实例上已创建的 Extension 实例（不触发创建）。

**参数：**
- `instance`: Declaration 实例
- `filter_type`: 可选，按类型过滤（`isinstance` 检查）

**返回：**
- 已创建的 Extension 实例列表

**示例：**

```python
# 枚举所有 Extension
for ext in mutobj.extensions(user):
    print(type(ext).__name__)

# 按接口过滤
for ext in mutobj.extensions(user, Serializable):
    data.update(ext._serialize())
```

---

### `mutobj.extension_types(decl_class, filter_type=None)`

查询 Declaration 类注册了哪些 Extension 类型。沿 Declaration 的 MRO 收集。

**参数：**
- `decl_class`: Declaration 类（非实例）
- `filter_type`: 可选，按类型过滤（`issubclass` 检查）

**返回：**
- 注册的 Extension 类型列表

**示例：**

```python
# 查询所有注册的 Extension 类型
ext_types = mutobj.extension_types(User)

# 按接口过滤
serializable_types = mutobj.extension_types(User, Serializable)
```

---

## Type Annotations

mutobj 完全支持类型检查工具（mypy、pyright）和 IDE 跳转。

```python
# 声明文件 user.py
import mutobj

class User(mutobj.Declaration):
    name: str
    age: int

    def greet(self) -> str:
        """返回问候语"""
        ...

# 实现文件 user_impl.py
import mutobj
from .user import User

@mutobj.impl(User.greet)
def greet(self: User) -> str:  # IDE 可识别 self 类型
    return f"Hello, {self.name}"  # IDE 可补全 name 属性
```

---

## Inheritance

mutobj 完全支持类继承。

```python
class Animal(mutobj.Declaration):
    name: str

    def speak(self) -> str:
        ...

@mutobj.impl(Animal.speak)
def animal_speak(self: Animal) -> str:
    return f"{self.name} makes a sound"

# 子类继承属性和方法
class Dog(Animal):
    breed: str

d = Dog(name="Buddy", breed="Labrador")
d.speak()  # "Buddy makes a sound"

# 子类可覆盖方法
class Cat(Animal):
    def speak(self) -> str:
        ...

@mutobj.impl(Cat.speak)
def cat_speak(self: Cat) -> str:
    return f"{self.name} meows"
```

---

## Error Handling

### NotImplementedError

调用桩方法（方法体为 `...` 或 `pass`）且无 `@impl` 注册时抛出。如果方法体有真实代码，则作为默认实现执行，不会抛出此异常。

```python
class Service(mutobj.Declaration):
    def process(self) -> None:
        ...

s = Service()
s.process()  # NotImplementedError: Method 'process' is declared in Service but not implemented.
```

### ValueError

- 尝试实现未声明的方法

```python
@mutobj.impl(User.nonexistent)  # ValueError: Method 'nonexistent' does not exist in User
def bad(self: User) -> str:
    return "error"
```

### AttributeError

- 访问未设置的属性
- 设置只读 property

---

### `mutobj.field(*, default=MISSING, default_factory=None)`

声明属性的默认值，用于可变类型或需要工厂函数的场景。

**参数：**
- `default`: 不可变默认值（与 `default_factory` 互斥）
- `default_factory`: 可变默认值的工厂函数，每次实例化时调用（与 `default` 互斥）

**示例：**

```python
from mutobj import field

class Config(mutobj.Declaration):
    # 不可变默认值——直接赋值即可，不需要 field()
    port: int = 8080

    # 可变默认值——必须使用 field(default_factory=...)
    tags: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)

    # 自定义工厂函数
    data: list[int] = field(default_factory=lambda: [1, 2, 3])
```

**异常：**
- `TypeError`: 同时传入 `default` 和 `default_factory`

**注意：** 可变类型（`list`、`dict`、`set`、`bytearray`）不能直接赋值为属性默认值，否则会在类定义时抛出 `TypeError`。Extension 中同样支持 `field()` 声明可变默认值。

---

## Version

```python
import mutobj
print(mutobj.__version__)  # "0.1.0"
```
