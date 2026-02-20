# mutobj 使用指南

## 简介

mutobj (Mutable Object Declaration) 让你可以将类的声明和实现分离到不同文件中，类似于 C/C++ 的头文件和实现文件模式。

**核心特性：**
- 声明与实现分离
- Extension 机制提供私有状态
- 完整的 IDE 和类型检查支持
- 支持 property、classmethod、staticmethod
- 支持继承

## 快速开始

### 安装

```bash
pip install mutobj
```

### 基本用法

**1. 声明文件 (`models/user.py`)**

```python
import mutobj

class User(mutobj.Declaration):
    # 属性声明
    name: str
    email: str
    age: int

    # 属性默认值
    active: bool = True

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
import mutobj
from .user import User

@mutobj.impl(User.greet)
def greet(self: User) -> str:
    return f"Hello, I'm {self.name}!"

@mutobj.impl(User.is_adult)
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
import mutobj

class Counter(mutobj.Declaration):
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
import mutobj
from .counter import Counter

class CounterExt(mutobj.Extension[Counter]):
    """Counter 的扩展，存储私有计数状态"""
    _count: int = 0

    def __extension_init__(self):
        self._count = 0

@mutobj.impl(Counter.increment)
def increment(self: Counter) -> int:
    ext = CounterExt.of(self)
    ext._count += 1
    return ext._count

@mutobj.impl(Counter.reset)
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
import mutobj

class Product(mutobj.Declaration):
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
import mutobj
from .product import Product

@mutobj.impl(Product.price.getter)
def get_price(self: Product) -> float:
    return self._price

@mutobj.impl(Product.price.setter)
def set_price(self: Product, value: float) -> None:
    if value < 0:
        raise ValueError("Price cannot be negative")
    self._price = value

@mutobj.impl(Product.display_price.getter)
def display_price(self: Product) -> str:
    return f"${self._price:.2f}"
```

## classmethod 和 staticmethod

```python
# models/factory.py
import mutobj

class UserFactory(mutobj.Declaration):
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
import mutobj
from .factory import UserFactory

@mutobj.impl(UserFactory.create_admin)
def create_admin(cls, name: str) -> UserFactory:
    user = cls()
    user.name = name
    user.role = "admin"
    return user

@mutobj.impl(UserFactory.create_guest)
def create_guest(cls) -> UserFactory:
    user = cls()
    user.name = "Guest"
    user.role = "guest"
    return user

@mutobj.impl(UserFactory.validate_name)
def validate_name(name: str) -> bool:
    return len(name) >= 2 and name.isalnum()
```

## 继承

mutobj 完全支持类继承。

```python
# models/animals.py
import mutobj

class Animal(mutobj.Declaration):
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
import mutobj
from .animals import Animal, Dog, Bird

@mutobj.impl(Animal.speak)
def animal_speak(self: Animal) -> str:
    return f"{self.name} makes a sound"

@mutobj.impl(Animal.move)
def animal_move(self: Animal) -> str:
    return f"{self.name} moves"

@mutobj.impl(Dog.speak)
def dog_speak(self: Dog) -> str:
    return f"{self.name} barks!"

@mutobj.impl(Bird.speak)
def bird_speak(self: Bird) -> str:
    return f"{self.name} chirps!"

@mutobj.impl(Bird.fly)
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

## 声明文件写法

Declaration 中的**所有公开方法**都是声明方法，方法体会被保存为默认实现。方法体可以使用 `...`、`pass` 或真实代码：

```python
import mutobj

class Calculator(mutobj.Declaration):
    base: int

    # 桩方法——调用时返回 None（Ellipsis 不执行任何操作）
    def add(self, n: int) -> int:
        """加法"""
        ...

    # 带默认实现——如果没有 @impl 注册，直接使用此实现
    def multiply(self, n: int) -> int:
        """乘法，提供默认实现"""
        return self.base * n

    # pass 也是合法的桩方法体
    def subtract(self, n: int) -> int:
        pass
```

当通过 `@impl` 注册实现后，默认实现被覆盖。卸载 `@impl` 后，默认实现自动恢复。

## IDE 跳转约定

mutobj 使用 Python 原生机制实现 IDE 跳转和延迟加载，不需要额外支持。

**方式一：`TYPE_CHECKING` 导入**

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from . import user_impl

class User(mutobj.Declaration):
    def greet(self) -> str:
        impl: user_impl.greet  # IDE 可识别类型，Ctrl+Click 跳转到实现
```

**方式二：函数体内 import + 转发**（推荐——精确到函数且支持延迟加载）

```python
class User(mutobj.Declaration):
    def greet(self) -> str:
        from .user_impl import greet
        return greet(self)
```

**实现模块导入**：在声明文件末尾或包的 `__init__.py` 中统一导入：

```python
# 声明文件末尾
from . import user_impl

# 或在 __init__.py 中统一导入
from .user import User
from . import user_impl
```

## 覆盖链与模块卸载

### 覆盖链

多个模块可以通过 `@impl` 为同一方法注册实现，形成覆盖链。按注册顺序排列，最后注册的为活跃实现：

```python
# 声明
class Service(mutobj.Declaration):
    def process(self) -> str:
        return "default"

# module_a.py —— 第一个 @impl
@mutobj.impl(Service.process)
def process_a(self: Service) -> str:
    return "module_a"

# module_b.py —— 后注册，成为活跃实现
@mutobj.impl(Service.process)
def process_b(self: Service) -> str:
    return "module_b"

s = Service()
s.process()  # "module_b"（链顶为活跃实现）
```

### 模块卸载

使用 `unregister_module_impls` 移除指定模块的所有 `@impl`，自动恢复覆盖链上一层：

```python
import mutobj

# 卸载 module_b 的实现
mutobj.unregister_module_impls("module_b")
s.process()  # "module_a"（恢复为链中上一层）

# 继续卸载 module_a
mutobj.unregister_module_impls("module_a")
s.process()  # "default"（恢复为声明中的默认实现）
```

**行为规则**：
- 卸载活跃实现 → 恢复为链中上一层
- 卸载中间层 → 活跃实现不变
- 全部卸载 → 恢复为声明中的默认实现
- 卸载不存在的模块 → 无操作

### 模块 Reload

`@impl` 模块的 reload 支持两种方式：

```python
import importlib

# 方式一：直接 reload（推荐）
importlib.reload(my_app.user_impl)
# 同模块的 @impl 就地替换，链中位置不变

# 方式二：卸载 + reload
mutobj.unregister_module_impls("my_app.user_impl")
importlib.reload(my_app.user_impl)
# 复用首次注册序号，回到链中原位置
```

中间层 reload 不影响活跃实现，链顶 reload 会更新为新函数。

## 最佳实践

1. **声明文件保持简洁**：只包含类型注解和方法签名
2. **实现文件命名约定**：`xxx_impl.py` 与 `xxx.py` 对应
3. **使用 Extension 管理私有状态**：避免在声明类中添加私有属性
4. **显式导入实现**：在包的 `__init__.py` 中导入实现文件
5. **类型注解**：为 `self` 参数添加类型注解以获得 IDE 支持

## 属性默认值

Declaration 属性支持 dataclass 风格的默认值语法：

```python
import mutobj
from mutobj import field

class Config(mutobj.Declaration):
    # 无默认值——构造时必须传入
    host: str

    # 不可变默认值——直接赋值
    port: int = 8080
    debug: bool = False
    greeting: str = "hello"

    # Optional 默认 None
    api_key: str | None = None

    # 可变类型默认值——使用 field(default_factory=...)
    tags: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
```

```python
# 有默认值的属性可以省略
config = Config(host="localhost")
assert config.port == 8080
assert config.tags == []      # 每个实例独立的 list
assert config.api_key is None

# 也可以覆盖默认值
config2 = Config(host="0.0.0.0", port=9090, tags=["prod"])
```

**注意**：可变类型（`list`、`dict`、`set`）不能直接赋值，必须使用 `field(default_factory=...)`：

```python
# 错误——会抛出 TypeError
class Bad(mutobj.Declaration):
    items: list = []  # TypeError!

# 正确
class Good(mutobj.Declaration):
    items: list = field(default_factory=list)
```

继承时，子类可以覆盖父类的默认值：

```python
class Animal(mutobj.Declaration):
    sound: str = "..."

class Dog(Animal):
    sound: str = "woof"  # 覆盖父类默认值

dog = Dog()
assert dog.sound == "woof"
```

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
@mutobj.impl(User.greet, override=True)
def new_greet(self: User) -> str:
    return "New implementation"
```

### Q: Extension 的私有状态是实例级别的吗？

是的，每个 Declaration 实例有独立的 Extension 视图和状态。
