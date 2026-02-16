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
- 识别桩方法（只包含 `...` 或 `pass` 的方法）
- 支持 `@property`、`@classmethod`、`@staticmethod` 声明
- 支持通过关键字参数初始化：`User(name="Alice", age=30)`

---

### `@mutobj.impl(method, *, override=False)`

方法实现装饰器，用于为声明的方法提供实现。

**参数：**
- `method`: 要实现的方法（如 `User.greet`）
- `override`: 是否允许覆盖已有实现，默认 `False`

**示例：**

```python
# 普通方法实现
@mutobj.impl(User.greet)
def greet(self: User) -> str:
    return f"Hello, {self.name}!"

# 覆盖已有实现
@mutobj.impl(User.greet, override=True)
def greet_v2(self: User) -> str:
    return f"Hi, {self.name}!"
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
- `ValueError`: 方法未声明或已有实现且 `override=False`
- `TypeError`: 参数类型错误

---

### `mutobj.Extension[T]`

Extension 泛型基类，用于为 Declaration 子类提供扩展功能和私有状态。

```python
class UserExt(mutobj.Extension[User]):
    _counter: int = 0

    def __extension_init__(self):
        """可选：Extension 初始化钩子"""
        self._counter = 0

    def _helper(self) -> str:
        """私有辅助方法"""
        return f"Counter: {self._counter}"
```

**特性：**
- 通过 `Extension[TargetClass]` 语法绑定目标类
- 支持私有状态（`_` 前缀属性存储在 Extension 实例上）
- 可通过 `self.attr` 访问目标实例的公共属性
- 可定义 `__extension_init__` 钩子进行初始化

---

### `Extension.of(instance)`

获取实例的 Extension 视图。

**参数：**
- `instance`: mutobj.Declaration 的实例

**返回：**
- 缓存的 Extension 视图对象

**示例：**

```python
@mutobj.impl(User.greet)
def greet(self: User) -> str:
    ext = UserExt.of(self)
    ext._counter += 1
    return f"Hello, {self.name}! (called {ext._counter} times)"
```

**特性：**
- 视图对象被缓存，同一实例多次调用返回同一对象
- 首次调用时自动调用 `__extension_init__`（如果定义）

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

调用未实现的方法时抛出。

```python
class Service(mutobj.Declaration):
    def process(self) -> None:
        ...

s = Service()
s.process()  # NotImplementedError: Method 'process' is declared in Service but not implemented.
```

### ValueError

- 尝试实现未声明的方法
- 重复实现方法但未设置 `override=True`

```python
# 重复实现
@mutobj.impl(User.greet)
def greet_v1(self: User) -> str:
    return "v1"

@mutobj.impl(User.greet)  # ValueError: Method 'greet' already implemented
def greet_v2(self: User) -> str:
    return "v2"
```

### AttributeError

- 访问未设置的属性
- 设置只读 property

---

## Version

```python
import mutobj
print(mutobj.__version__)  # "0.1.0"
```
