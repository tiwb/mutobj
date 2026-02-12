# Python 分离式类定义库 设计规范

**状态**：✅ v0.2.0 功能实施完成
**日期**：2026-02-12
**类型**：功能设计

## 1. 背景

希望创建一个 Python 库，支持：
1. 将一个类拆分到多个文件中编写（声明与实现分离）
2. 支持类似"私有成员"的概念，实现文件级别的变量隔离
3. 未来可转换为 C/C++ 代码以提升性能

## 2. 设计方案

### 2.1 已确认的设计决策

| 项目 | 决策 |
|------|------|
| 库名称 | `pyic`（Python Interface Class） |
| Python 版本 | 3.11+ 基线，支持 3.14+ 新特性 |
| C/C++ 转换 | 后续迭代，MVP 不包含，但设计需预留扩展性 |
| 成员变量存储 | 需抽象存储层，与接口设计解耦，便于未来优化 |
| IDE/类型检查 | 必须支持 mypy/pyright 和 IDE 跳转 |
| 实例化方式 | 自动发现（import 时自动注册实现） |
| 实现发现机制 | 显式 import |
| 公开属性访问 | 直接 `self.name`，内部通过 descriptor 拦截 |
| 重复实现处理 | 默认报错，`@pyic.impl(..., override=True)` 允许覆盖 |
| 继承支持 | 继承 + 可覆盖 |
| `__init__` 位置 | 不限制，但建议在实现文件中定义 |
| 声明语法 | docstring + `...`（推荐） |
| 未实现方法行为 | 抛出 `NotImplementedError` |
| property 支持 | MVP 支持，使用 `.getter`/`.setter` 显式语法 |
| classmethod/staticmethod | MVP 支持 |
| 模块结构 | 不限制，文档提供最佳实践 |
| Extension 语法 | `class Ext(pyic.Extension[User])` 泛型基类 |
| Extension 私有函数可见性 | Python 默认行为（`_` 命名约定） |
| Extension 中 self | 指向 Extension 视图 |
| Extension 初始化 | 默认值 + `__extension_init__` 钩子 |
| Extension.of() 缓存 | 是，缓存视图对象 |
| 外部调用私有方法 | 允许（Python 惯例） |
| 未绑定的 Extension | 允许 |
| Native 类型标记 | 类级别 `@pyic.native` + 属性级别类型注解 |
| Native 基本类型映射 | `int`→`int64_t`, `float`→`double`, `str`→`const char*` |
| 类型检查策略 | native 模式严格，非 native 模式宽松 |
| 内存管理 | v2.0 设计，MVP 使用 Python 原生 GC |

### 2.2 语法设计（最终版）

**声明文件 user.py**：
```python
import pyic

class User(pyic.Object):
    name: str
    age: int

    def greet(self) -> str:
        """打招呼方法，返回问候语"""
        ...

    def calculate_score(self, base: int) -> int:
        """计算分数方法"""
        ...

    @property
    def display_name(self) -> str:
        """显示名称（只读）"""
        ...
```

**实现文件 user_impl.py**：
```python
import pyic
from .user import User

class UserExt(pyic.Extension[User]):
    _counter: int = 0

    def _format_greeting(self) -> str:
        return f"Hello, {self.name}"

    def __extension_init__(self):
        """可选：Extension 初始化钩子"""
        self._counter = 0

@pyic.impl(User.greet)
def greet(self: User) -> str:
    ext = UserExt.of(self)
    ext._counter += 1
    return ext._format_greeting()

@pyic.impl(User.display_name.getter)
def display_name(self: User) -> str:
    return f"[{self.name}]"
```

**注**：property 语法如果实现困难，可考虑其他形式，但功能需支持。

### 2.3 Native 类型设计（v2.0 预留）

```python
import pyic
from pyic.native import Int32, Float32, WideString

@pyic.native  # 标记为纯 C 类
class User(pyic.Object):
    age: int              # 默认 int64_t
    small_count: Int32    # 显式 int32_t
    ratio: float          # 默认 double
    precision: Float32    # 显式 float
    name: str             # 默认 const char*
    wide_name: WideString # 显式 wchar_t*

    def greet(self) -> str: ...
```

**默认类型映射（在 `@pyic.native` 类下）**：

| Python 类型 | Native C 类型 | 说明 |
|-------------|---------------|------|
| `int` | `int64_t` | 64位整数 |
| `float` | `double` | 64位浮点 |
| `bool` | `bool` / `int8_t` | 布尔值 |
| `str` | `const char*` | UTF-8 字符串指针 |
| `bytes` | `const uint8_t*` + `size_t` | 字节数组 |
| `None` | `void` / `nullptr` | 空值 |

## 3. 设计总结

### 3.1 核心概念

```
┌─────────────────────────────────────────────────────────────┐
│                      pyic 架构                               │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  声明文件 (.py)              实现文件 (.py)                   │
│  ┌──────────────────┐      ┌──────────────────────────┐    │
│  │ class User       │      │ class UserExt            │    │
│  │   (pyic.Object)  │◄─────│   (Extension[User])      │    │
│  │                  │      │   _counter: int          │    │
│  │ - name: str      │      │   _format_greeting()     │    │
│  │ - age: int       │      │                          │    │
│  │ + greet()        │      ├──────────────────────────┤    │
│  │ + display_name   │      │ @pyic.impl(User.greet)   │    │
│  └──────────────────┘      │ def greet(self): ...     │    │
│                             └──────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                    运行时                              │  │
│  │  - metaclass 处理声明                                  │  │
│  │  - descriptor 拦截属性访问                             │  │
│  │  - 方法注册表管理实现                                   │  │
│  │  - Extension 视图缓存                                  │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                  未来: C++ 转换                        │  │
│  │  - 声明 → C struct + vtable                           │  │
│  │  - 实现 → C 函数                                       │  │
│  │  - Extension → 扩展 struct                             │  │
│  │  - @pyic.native → native 类型存储                      │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 API 清单

| API | 说明 |
|-----|------|
| `pyic.Object` | 声明类的基类 |
| `pyic.Extension[T]` | Extension 泛型基类 |
| `@pyic.impl(method)` | 方法实现装饰器 |
| `@pyic.impl(method, override=True)` | 覆盖实现 |
| `Extension.of(instance)` | 获取实例的 Extension 视图 |
| `__extension_init__(self)` | Extension 初始化钩子 |
| `@pyic.native` | 标记为 native C 类（v2.0） |

### 3.3 设计原则

1. **声明与实现分离**：接口清晰，实现可分布
2. **IDE 友好**：完整类型提示，跳转支持
3. **Python 惯例**：遵循 `_` 命名约定，不强制限制
4. **C++ 兼容**：设计预留转换空间
5. **简洁优先**：最小化样板代码

## 4. 实施步骤清单

### 阶段一：核心框架 [✅ 已完成]

- [x] **Task 1.1**: 项目初始化
  - [x] 创建 pyic 包结构
  - [x] 设置 pyproject.toml
  - [x] 配置测试框架（pytest）
  - 状态：✅ 已完成

- [x] **Task 1.2**: pyic.Object 基类
  - [x] 实现 metaclass
  - [x] 属性声明解析
  - [x] 方法声明解析（识别空方法）
  - [x] 单元测试 (8个测试通过)
  - 状态：✅ 已完成

- [x] **Task 1.3**: @pyic.impl 装饰器
  - [x] 方法注册机制
  - [x] 重复实现检测
  - [x] override 参数支持
  - [x] 单元测试 (6个测试通过)
  - 状态：✅ 已完成

### 阶段二：Extension 机制 [✅ 已完成]

- [x] **Task 2.1**: pyic.Extension 泛型基类
  - [x] `__class_getitem__` 实现
  - [x] 目标类绑定
  - [x] 类型检查支持
  - 状态：✅ 已完成

- [x] **Task 2.2**: Extension.of() 方法
  - [x] 视图对象创建
  - [x] 缓存机制
  - [x] 属性代理
  - 状态：✅ 已完成

- [x] **Task 2.3**: Extension 初始化
  - [x] 默认值支持
  - [x] `__extension_init__` 钩子
  - [x] 单元测试 (8个测试通过)
  - 状态：✅ 已完成

### 阶段三：Property 与高级特性 [✅ 已完成]

- [x] **Task 3.1**: Property 支持
  - [x] getter 实现
  - [x] setter 实现
  - [x] 只读 property
  - [x] 单元测试 (7个测试通过)
  - 状态：✅ 已完成

- [x] **Task 3.2**: classmethod/staticmethod
  - [x] 声明支持
  - [x] 实现注册
  - [x] 单元测试 (10个测试通过)
  - 状态：✅ 已完成

- [x] **Task 3.3**: 继承支持
  - [x] 类继承
  - [x] 方法继承与覆盖
  - [x] 单元测试 (9个测试通过)
  - 状态：✅ 已完成

### 阶段四：文档与发布 [待开始]

- [ ] **Task 4.1**: API 文档
- [ ] **Task 4.2**: 使用指南
- [ ] **Task 4.3**: PyPI 发布准备

---

### 实施进度总结

- ✅ **阶段一：核心框架** - 100% 完成 (3/3任务)
- ✅ **阶段二：Extension 机制** - 100% 完成 (3/3任务)
- ✅ **阶段三：Property 与高级特性** - 100% 完成 (3/3任务)
- ⏸️ **阶段四：文档与发布** - 0% 完成 (0/3任务)

**v0.2.0 功能完成度：100%** (9/9任务)
**单元测试覆盖：50个测试全部通过**

---

## 5. 测试验证

### 单元测试

- [x] pyic.Object 基类测试 (8个测试通过)
- [x] @pyic.impl 装饰器测试 (6个测试通过)
- [x] Extension 机制测试 (8个测试通过)
- [x] Property 支持测试 (7个测试通过)
- [x] classmethod/staticmethod 测试 (10个测试通过)
- [x] 继承支持测试 (9个测试通过)

### 集成测试

- [ ] 完整声明/实现分离场景
- [ ] 多文件 Extension 场景
- [ ] IDE 类型检查验证（mypy/pyright）

---

## 6. 版本规划

| 版本 | 内容 |
|------|------|
| v0.1.0 (MVP) | 核心框架 + Extension + Property |
| v0.2.0 | classmethod/staticmethod + 继承 |
| v1.0.0 | 完整功能 + 文档 + PyPI 发布 |
| v2.0.0 | @pyic.native + C++ 代码生成 |

---

**设计状态**：✅ v0.2.0 功能实施完成

**完成情况**：
- 核心框架 + Extension + Property + classmethod/staticmethod + 继承 全部完成
- 50个单元测试全部通过

**下一步**：开始阶段四（文档与发布），或确认完成进行归档
