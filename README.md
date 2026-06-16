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

```python
import mutobj

class User(mutobj.Declaration):
    name: str
    age: int

    def greet(self) -> str: ...

@mutobj.impl(User.greet)
def user_greet(self: User) -> str:
    return f"Hello, I'm {self.name}!"

user = User(name="Alice", age=25)
print(user.greet())  # "Hello, I'm Alice!"
```

字段声明、方法覆盖、继承、Extension 私有状态、Implementation 类等详见 [使用指南](docs/guide.md)。

## Lint 工具

在 pytest 中执行运行时 lint，检查 `@impl` 命名规范、签名一致性等：

```python
from mutobj.lint import check

def test_lint() -> None:
    results = check(["mypkg.*"])
    if results:
        pytest.fail(results.format())
```

详见 [使用指南 §5.4](docs/guide.md#54-mutobjlintcheck)。

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
