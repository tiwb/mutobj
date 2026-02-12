# pyic 使用指南

## 简介

pyic (Python Interface Class) 让你可以将类的声明和实现分离到不同文件中，类似于 C/C++ 的头文件和实现文件模式。

**核心特性：**
- 声明与实现分离
- Extension 机制提供私有状态
- 完整的 IDE 和类型检查支持
- 支持 property、classmethod、staticmethod
- 支持继承

## 快速开始

### 安装

```bash
pip install pyic
```

### 基本用法

**1. 声明文件 (`models/user.py`)**

```python
import pyic

class User(pyic.Object):
    # 属性声明
    name: str
    email: str
    age: int

    # 方法声明（桩方法）
    def greet(self) -> str:
        """返回问候语"""
        ...

    def is_adult(self) -> bool:
        """检查是否成年"""
        ...
```

**2. 实现文件 (`models/user_impl.py`)**

```python
import pyic
from .user import User

@pyic.impl(User.greet)
def greet(self: User) -> str:
    return f"Hello, I'm {self.name}!"

@pyic.impl(User.is_adult)
def is_adult(self: User) -> bool:
    return self.age >= 18
```

**3. 使用**

```python
from models.user import User
import models.user_impl  # 导入实现文件以注册实现

user = User(name="Alice", email="alice@example.com", age=25)
print(user.greet())      # "Hello, I'm Alice!"
print(user.is_adult())   # True
```

## Extension 机制

Extension 允许你为类添加私有状态和辅助方法，而不污染原始类的接口。

```python
# models/counter.py
import pyic

class Counter(pyic.Object):
    name: str

    def increment(self) -> int:
        """增加并返回计数"""
        ...

    def reset(self) -> None:
        """重置计数"""
        ...
```

```python
# models/counter_impl.py
import pyic
from .counter import Counter

class CounterExt(pyic.Extension[Counter]):
    """Counter 的扩展，存储私有计数状态"""
    _count: int = 0

    def __extension_init__(self):
        self._count = 0

@pyic.impl(Counter.increment)
def increment(self: Counter) -> int:
    ext = CounterExt.of(self)
    ext._count += 1
    return ext._count

@pyic.impl(Counter.reset)
def reset(self: Counter) -> None:
    ext = CounterExt.of(self)
    ext._count = 0
```

```python
# 使用
from models.counter import Counter
import models.counter_impl

c = Counter(name="MyCounter")
print(c.increment())  # 1
print(c.increment())  # 2
c.reset()
print(c.increment())  # 1
```

## Property 支持

```python
# models/product.py
import pyic

class Product(pyic.Object):
    name: str
    _price: float

    @property
    def price(self) -> float:
        """商品价格"""
        ...

    @property
    def display_price(self) -> str:
        """格式化价格显示"""
        ...
```

```python
# models/product_impl.py
import pyic
from .product import Product

@pyic.impl(Product.price.getter)
def get_price(self: Product) -> float:
    return self._price

@pyic.impl(Product.price.setter)
def set_price(self: Product, value: float) -> None:
    if value < 0:
        raise ValueError("Price cannot be negative")
    self._price = value

@pyic.impl(Product.display_price.getter)
def display_price(self: Product) -> str:
    return f"${self._price:.2f}"
```

## classmethod 和 staticmethod

```python
# models/factory.py
import pyic

class UserFactory(pyic.Object):
    name: str
    role: str

    @classmethod
    def create_admin(cls, name: str) -> "UserFactory":
        """创建管理员用户"""
        ...

    @classmethod
    def create_guest(cls) -> "UserFactory":
        """创建访客用户"""
        ...

    @staticmethod
    def validate_name(name: str) -> bool:
        """验证用户名"""
        ...
```

```python
# models/factory_impl.py
import pyic
from .factory import UserFactory

@pyic.impl(UserFactory.create_admin)
def create_admin(cls, name: str) -> UserFactory:
    user = cls()
    user.name = name
    user.role = "admin"
    return user

@pyic.impl(UserFactory.create_guest)
def create_guest(cls) -> UserFactory:
    user = cls()
    user.name = "Guest"
    user.role = "guest"
    return user

@pyic.impl(UserFactory.validate_name)
def validate_name(name: str) -> bool:
    return len(name) >= 2 and name.isalnum()
```

## 继承

pyic 完全支持类继承。

```python
# models/animals.py
import pyic

class Animal(pyic.Object):
    name: str

    def speak(self) -> str:
        ...

    def move(self) -> str:
        ...

class Dog(Animal):
    breed: str

    # 覆盖父类方法
    def speak(self) -> str:
        ...

class Bird(Animal):
    wingspan: float

    def speak(self) -> str:
        ...

    # 新增方法
    def fly(self) -> str:
        ...
```

```python
# models/animals_impl.py
import pyic
from .animals import Animal, Dog, Bird

@pyic.impl(Animal.speak)
def animal_speak(self: Animal) -> str:
    return f"{self.name} makes a sound"

@pyic.impl(Animal.move)
def animal_move(self: Animal) -> str:
    return f"{self.name} moves"

@pyic.impl(Dog.speak)
def dog_speak(self: Dog) -> str:
    return f"{self.name} barks!"

@pyic.impl(Bird.speak)
def bird_speak(self: Bird) -> str:
    return f"{self.name} chirps!"

@pyic.impl(Bird.fly)
def bird_fly(self: Bird) -> str:
    return f"{self.name} flies with {self.wingspan}m wingspan"
```

```python
# 使用
dog = Dog(name="Buddy", breed="Labrador")
dog.speak()  # "Buddy barks!"
dog.move()   # "Buddy moves" (继承自 Animal)

bird = Bird(name="Tweety", wingspan=0.3)
bird.speak()  # "Tweety chirps!"
bird.fly()    # "Tweety flies with 0.3m wingspan"
```

## 项目结构建议

```
myproject/
├── src/
│   └── myproject/
│       ├── __init__.py
│       ├── models/
│       │   ├── __init__.py
│       │   ├── user.py          # 声明
│       │   ├── user_impl.py     # 实现
│       │   ├── product.py
│       │   └── product_impl.py
│       └── services/
│           ├── __init__.py
│           ├── auth.py
│           └── auth_impl.py
└── tests/
    └── ...
```

**`models/__init__.py` 示例：**

```python
from .user import User
from .product import Product

# 导入实现文件以注册实现
from . import user_impl
from . import product_impl

__all__ = ["User", "Product"]
```

## 最佳实践

1. **声明文件保持简洁**：只包含类型注解和方法签名
2. **实现文件命名约定**：`xxx_impl.py` 与 `xxx.py` 对应
3. **使用 Extension 管理私有状态**：避免在声明类中添加私有属性
4. **显式导入实现**：在包的 `__init__.py` 中导入实现文件
5. **类型注解**：为 `self` 参数添加类型注解以获得 IDE 支持

## 常见问题

### Q: 调用方法报 NotImplementedError？

确保导入了实现文件：

```python
from models.user import User
import models.user_impl  # 不要忘记这行！
```

### Q: 如何覆盖已有实现？

使用 `override=True`：

```python
@pyic.impl(User.greet, override=True)
def new_greet(self: User) -> str:
    return "New implementation"
```

### Q: Extension 的私有状态是实例级别的吗？

是的，每个 Object 实例有独立的 Extension 视图和状态。
