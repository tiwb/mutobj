# mutobj

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**mutobj** (Mutable Object Declaration) - 支持声明与实现分离的 Python 类定义库。

## 特性

- **声明与实现分离** - 类似 C/C++ 头文件模式
- **Extension 机制** - 为类添加私有状态而不污染接口
- **IDE 友好** - 完整支持 mypy/pyright 和 IDE 跳转
- **继承支持** - 完整的类继承和方法覆盖
- **零依赖** - 纯 Python 实现，无外部依赖

## 安装

```bash
pip install mutobj
```

## 快速开始

**声明文件 (`user.py`)**

```python
import mutobj

class User(mutobj.Declaration):
    name: str
    age: int

    def greet(self) -> str:
        """返回问候语"""
        ...
```

**实现文件 (`user_impl.py`)**

```python
import mutobj
from .user import User

@mutobj.impl(User.greet)
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
class UserExt(mutobj.Extension[User]):
    _login_count: int = 0

    def __extension_init__(self):
        self._login_count = 0

@mutobj.impl(User.greet)
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

- [使用指南](docs/guide.md)
- [API 参考](docs/api/reference.md)

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 类型检查
mypy src/mutobj
```

## 发布

Tag 触发自动发布（PyPI Trusted Publishers，无需 token）：

```bash
git tag v0.2.x
git push origin v0.2.x
```

源码版本保持 `x.y.999`，CI 从 tag 提取正式版本号替换后构建发布。

## License

MIT License - 详见 [LICENSE](LICENSE)
