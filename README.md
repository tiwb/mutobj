# pyic

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**pyic** (Python Interface Class) - 支持声明与实现分离的 Python 类定义库。

## 特性

- **声明与实现分离** - 类似 C/C++ 头文件模式
- **Extension 机制** - 为类添加私有状态而不污染接口
- **IDE 友好** - 完整支持 mypy/pyright 和 IDE 跳转
- **继承支持** - 完整的类继承和方法覆盖
- **零依赖** - 纯 Python 实现，无外部依赖

## 安装

```bash
pip install pyic
```

## 快速开始

**声明文件 (`user.py`)**

```python
import pyic

class User(pyic.Object):
    name: str
    age: int

    def greet(self) -> str:
        """返回问候语"""
        ...
```

**实现文件 (`user_impl.py`)**

```python
import pyic
from .user import User

@pyic.impl(User.greet)
def greet(self: User) -> str:
    return f"Hello, I'm {self.name}!"
```

**使用**

```python
from user import User
import user_impl  # 导入以注册实现

user = User(name="Alice", age=25)
print(user.greet())  # "Hello, I'm Alice!"
```

## Extension 机制

为类添加私有状态：

```python
class UserExt(pyic.Extension[User]):
    _login_count: int = 0

    def __extension_init__(self):
        self._login_count = 0

@pyic.impl(User.greet)
def greet(self: User) -> str:
    ext = UserExt.of(self)
    ext._login_count += 1
    return f"Hello, {self.name}! (login #{ext._login_count})"
```

## 支持的功能

| 功能 | 状态 |
|------|------|
| 属性声明 | ✅ |
| 方法声明与实现 | ✅ |
| Property | ✅ |
| classmethod | ✅ |
| staticmethod | ✅ |
| 继承 | ✅ |
| Extension | ✅ |
| 类型检查 | ✅ |

## 文档

- [使用指南](doc/guide.md)
- [API 参考](doc/api/reference.md)

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 类型检查
mypy src/pyic
```

## License

MIT License - 详见 [LICENSE](LICENSE)
