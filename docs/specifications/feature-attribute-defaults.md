# Declaration 属性默认值支持 设计规范

**状态**：✅ 已完成
**日期**：2026-02-20
**类型**：功能设计

## 1. 背景

当前 Declaration 类无法为属性声明指定默认值。`DeclarationMeta.__new__` 在处理类型注解时，会创建 `AttributeDescriptor` 覆盖类级别的赋值。用户写 `name: str = "anonymous"` 时，默认值被静默丢弃。

### 1.1 现有代码行为

`DeclarationMeta.__new__`（core.py:394-405）处理属性声明时：

```python
for attr_name, attr_type in annotations.items():
    if attr_name in namespace and not isinstance(namespace[attr_name], AttributeDescriptor):
        if callable(namespace[attr_name]) or isinstance(namespace[attr_name], property):
            continue
        # 非 callable 的值（如 "anonymous"）会穿透到下方
    # 创建 AttributeDescriptor，覆盖掉原始值
    descriptor = AttributeDescriptor(attr_name, attr_type)
    setattr(cls, attr_name, descriptor)  # ← 默认值在此被覆盖
```

### 1.2 mutagent 项目中的绕行模式

在 mutagent 项目中，所有 Declaration 子类都无法使用默认值，被迫采用以下模式：

**lazy-init 模式**（tool_set_impl.py, userio_impl.py, block_handlers.py）：
```python
def _get_entries(self: ToolSet) -> dict[str, ToolEntry]:
    entries = getattr(self, '_entries', None)
    if entries is None:
        entries = {}
        object.__setattr__(self, '_entries', entries)
    return entries
```

**构造时必须显式传入所有属性**（agent.py）：
```python
agent = Agent(client=..., tool_set=..., system_prompt=..., messages=[])
```

**Optional 属性无法默认 None**（client.py）：
```python
api_recorder: ApiRecorder | None  # 想要默认 None，但无法表达
# 访问时被迫用 getattr(self, "api_recorder", None)
```

### 1.3 问题总结

1. **默认值被静默丢弃**——用户写 `name: str = "default"` 不报错也不生效
2. **所有属性必须构造时传入**——无法省略有合理默认值的属性
3. **迫使使用 lazy-init 绕行**——增加样板代码，违反直觉

## 2. 设计方案

### 2.1 用户侧语法

采用 dataclass 风格语法，对 Python 开发者和 AI 最自然：

```python
import mutobj
from mutobj import field

class User(mutobj.Declaration):
    # 无默认值——构造时必须传入
    name: str

    # 不可变默认值——直接赋值
    age: int = 0
    active: bool = True
    greeting: str = "hello"

    # 可变类型默认值——使用 field(default_factory=...)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    # Optional 默认 None
    recorder: Recorder | None = None
```

**使用方式**：

```python
# 有默认值的属性可以省略
user = User(name="Alice")
assert user.age == 0
assert user.active is True
assert user.tags == []        # 每个实例独立的 list
assert user.recorder is None

# 也可以覆盖默认值
user2 = User(name="Bob", age=25, tags=["admin"])
```

**错误防护**——可变对象直接赋值报错（与 dataclass 行为一致）：

```python
class Bad(mutobj.Declaration):
    tags: list = []   # TypeError: 可变默认值不允许，请使用 field(default_factory=list)
    data: dict = {}   # TypeError: 同上
    ids: set = set()  # TypeError: 同上
```

### 2.2 `field()` 函数

```python
def field(*, default: Any = _MISSING, default_factory: Callable[[], Any] | None = None) -> Any:
    """声明属性的默认值

    Args:
        default: 不可变默认值
        default_factory: 可变默认值的工厂函数，每次实例化时调用

    Returns:
        Field 哨兵对象（DeclarationMeta 会识别并提取）
    """
```

`default` 和 `default_factory` 互斥，同时传入报 `TypeError`。

### 2.3 内部实现变更

#### `_MISSING` 哨兵

```python
class _MissingSentinel:
    """默认值缺失哨兵，区分"无默认值"和"默认值为 None" """
    _instance: _MissingSentinel | None = None

    def __new__(cls) -> _MissingSentinel:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False

_MISSING: Any = _MissingSentinel()
```

#### `Field` 类

```python
class Field:
    """属性默认值描述，由 field() 创建"""

    __slots__ = ("default", "default_factory")

    def __init__(
        self,
        default: Any = _MISSING,
        default_factory: Callable[[], Any] | None = None,
    ) -> None:
        if default is not _MISSING and default_factory is not None:
            raise TypeError("不能同时指定 default 和 default_factory")
        self.default = default
        self.default_factory = default_factory
```

#### `AttributeDescriptor` 变更

```python
class AttributeDescriptor:
    def __init__(
        self,
        name: str,
        annotation: Any,
        default: Any = _MISSING,            # 新增
        default_factory: Callable[[], Any] | None = None,  # 新增
    ):
        self.name = name
        self.annotation = annotation
        self.storage_name = f"_mutobj_attr_{name}"
        self.default = default
        self.default_factory = default_factory

    @property
    def has_default(self) -> bool:
        return self.default is not _MISSING or self.default_factory is not None

    # __get__ / __set__ / __delete__ 不变
```

#### `DeclarationMeta.__new__` 属性处理变更

```python
# 可变类型黑名单（直接赋值时报错）
_MUTABLE_TYPES = (list, dict, set, bytearray)

for attr_name, attr_type in annotations.items():
    value = namespace.get(attr_name)

    if isinstance(value, Field):
        # field() 声明
        descriptor = AttributeDescriptor(
            attr_name, attr_type,
            default=value.default,
            default_factory=value.default_factory,
        )
    elif value is not None and attr_name in namespace:
        if callable(value) or isinstance(value, property):
            continue
        if isinstance(value, _MUTABLE_TYPES):
            raise TypeError(
                f"Declaration '{name}' 的属性 '{attr_name}' 使用了可变默认值 "
                f"{type(value).__name__}。请使用 field(default_factory="
                f"{type(value).__name__}) 代替。"
            )
        # 不可变默认值
        descriptor = AttributeDescriptor(attr_name, attr_type, default=value)
    elif not hasattr(cls, attr_name) or not isinstance(
        getattr(cls, attr_name), AttributeDescriptor
    ):
        # 无默认值
        descriptor = AttributeDescriptor(attr_name, attr_type)
    else:
        attr_registry[attr_name] = attr_type
        continue

    setattr(cls, attr_name, descriptor)
    attr_registry[attr_name] = attr_type
```

#### `Declaration.__init__` 变更

```python
def __init__(self, **kwargs: Any) -> None:
    applied: set[str] = set()
    for klass in type(self).__mro__:
        if klass in _attribute_registry:
            for attr_name in _attribute_registry[klass]:
                if attr_name in applied:
                    continue
                if attr_name in kwargs:
                    setattr(self, attr_name, kwargs[attr_name])
                    applied.add(attr_name)
                else:
                    # 查找描述符上的默认值
                    desc = klass.__dict__.get(attr_name)
                    if isinstance(desc, AttributeDescriptor) and desc.has_default:
                        if desc.default_factory is not None:
                            setattr(self, attr_name, desc.default_factory())
                        else:
                            setattr(self, attr_name, desc.default)
                        applied.add(attr_name)
```

**关键变化**：
- 增加 `applied` 集合，避免继承链中重复处理同一属性（MRO 中最派生类优先）
- 未传入 kwargs 的属性，检查描述符是否有默认值并应用

### 2.4 继承行为

```python
class Animal(mutobj.Declaration):
    name: str
    sound: str = "..."

class Dog(Animal):
    breed: str
    sound: str = "woof"  # 覆盖父类默认值

dog = Dog(name="Buddy", breed="Labrador")
assert dog.sound == "woof"  # 子类默认值生效
```

MRO 迭代顺序（Dog → Animal → Declaration → object）确保子类的 `AttributeDescriptor` 先被找到，`applied` 集合防止父类的旧默认值覆盖。

### 2.5 公开 API 变更

| 变更 | 说明 |
|------|------|
| 新增 `field()` | 公开函数，用于声明可变类型默认值 |
| `__all__` | 新增 `"field"` |
| `AttributeDescriptor` | 新增 `default`、`default_factory`、`has_default`（内部 API，不影响用户） |

### 2.6 类型标注

`field()` 的返回类型标注为 `Any`，与 `dataclasses.field()` 一致，避免类型检查器报属性类型不匹配。

## 3. 已确认问题

### Q1: `field()` 参数范围
**决定**：MVP 只支持 `default` 和 `default_factory`。后续按需添加。

### Q2: 自定义 `__init__` 与默认值的交互
**决定**：默认值逻辑在 `Declaration.__init__` 中。用户自定义 `__init__` 时应调用 `super().__init__(**kwargs)` 来应用默认值，与标准 Python 继承行为一致。文档中说明即可。

## 4. 实施步骤清单

### 阶段一：核心实现 [✅ 已完成]

- [x] **Task 1.1**: 新增 `_MISSING`、`Field`、`field()`
  - [x] 定义 `_MissingSentinel` 单例
  - [x] 定义 `Field` 类（`default` + `default_factory`）
  - [x] 定义 `field()` 工厂函数
  - [x] 添加 `"field"` 到 `__all__`
  - 状态：✅ 已完成

- [x] **Task 1.2**: 修改 `AttributeDescriptor`
  - [x] 新增 `default`、`default_factory` 参数
  - [x] 新增 `has_default` 属性
  - 状态：✅ 已完成

- [x] **Task 1.3**: 修改 `DeclarationMeta.__new__` 属性处理
  - [x] 识别 `Field` 实例并提取默认值
  - [x] 识别不可变直接赋值并作为默认值
  - [x] 检测可变类型直接赋值并报 `TypeError`
  - [x] 确保继承场景下描述符正确创建
  - 状态：✅ 已完成

- [x] **Task 1.4**: 修改 `Declaration.__init__`
  - [x] 增加 `applied` 集合防止重复处理
  - [x] 未传入 kwargs 时应用描述符上的默认值
  - [x] `default_factory` 每次调用生成新实例
  - 状态：✅ 已完成

### 阶段二：测试 [✅ 已完成]

- [x] **Task 2.1**: 基本默认值测试
  - [x] 不可变默认值（str、int、float、bool、None、tuple）
  - [x] `field(default=...)` 等价于直接赋值
  - [x] `field(default_factory=list)` 每实例独立
  - [x] `field(default_factory=dict)` 每实例独立
  - [x] 混合：部分有默认值、部分无默认值
  - [x] 构造时 kwargs 覆盖默认值
  - 状态：✅ 已完成

- [x] **Task 2.2**: 错误检测测试
  - [x] `tags: list = []` 报 `TypeError`
  - [x] `data: dict = {}` 报 `TypeError`
  - [x] `ids: set = set()` 报 `TypeError`
  - [x] `field(default=1, default_factory=int)` 报 `TypeError`
  - 状态：✅ 已完成

- [x] **Task 2.3**: 继承默认值测试
  - [x] 子类继承父类默认值
  - [x] 子类覆盖父类默认值
  - [x] 多级继承默认值传播
  - [x] 子类新增带默认值的属性
  - 状态：✅ 已完成

- [x] **Task 2.4**: 与现有功能交互测试
  - [x] 默认值 + `@impl` 方法正常工作
  - [x] 默认值 + `Extension.of()` 正常工作
  - [x] 默认值 + Property 正常工作
  - [x] 默认值 + reload（Declaration 重定义）正常工作
  - 状态：✅ 已完成

- [x] **Task 2.5**: 回归测试
  - [x] 运行全部现有 92 个测试，确保无回归
  - 状态：✅ 已完成

### 阶段三：文档更新 [✅ 已完成]

- [x] **Task 3.1**: 更新 guide.md
  - [x] 属性默认值使用说明
  - [x] `field()` 使用说明
  - [x] 可变默认值注意事项
  - 状态：✅ 已完成

- [x] **Task 3.2**: 更新 API reference
  - [x] `field()` 函数文档
  - 状态：✅ 已完成

### 阶段四：mutagent 项目适配 [✅ 已完成]

调研发现 mutagent 中 3 个公开属性可直接受益于默认值支持。私有属性（`_entries`、`_buffer`、`_parse_state` 等）的 lazy-init 模式属于合理的内部状态管理，不在此次修改范围内。

- [x] **Task 4.1**: `LLMClient.api_recorder` 添加默认值
  - 文件：`mutagent/src/mutagent/client.py`
  - 变更：`api_recorder: ApiRecorder | None` → `api_recorder: ApiRecorder | None = None`
  - 清理：`claude_impl.py` 中 `getattr(self, "api_recorder", None)` → `self.api_recorder`
  - 状态：✅ 已完成

- [x] **Task 4.2**: `UserIO.block_handlers` 添加默认值
  - 文件：`mutagent/src/mutagent/userio.py`
  - 变更：`block_handlers: dict` → `block_handlers: dict = field(default_factory=dict)`
  - 新增：`from mutagent import field` 导入
  - 状态：✅ 已完成

- [x] **Task 4.3**: `ToolSet.auto_discover` 添加默认值
  - 文件：`mutagent/src/mutagent/tools.py`
  - 变更：`auto_discover: bool` → `auto_discover: bool = False`
  - 清理：`tool_set_impl.py` 中 3 处 `getattr(self, 'auto_discover', False)` → `self.auto_discover`
  - 状态：✅ 已完成

- [x] **Task 4.4**: mutagent 测试验证
  - 运行 mutagent 全部测试，确保适配后无回归
  - 新增：`mutagent/__init__.py` 中导出 `field`
  - 状态：✅ 已完成

---

### 实施进度总结

- ✅ **阶段一：核心实现** - 100% 完成 (4/4任务)
- ✅ **阶段二：测试** - 100% 完成 (5/5任务)
- ✅ **阶段三：文档更新** - 100% 完成 (2/2任务)
- ✅ **阶段四：mutagent 适配** - 100% 完成 (4/4任务)

**核心功能完成度：100%** (15/15任务)

## 5. 测试验证

### mutobj 单元测试
- [x] 不可变默认值正确应用（str、int、float、bool、None、tuple）
- [x] `field(default_factory=...)` 每实例独立
- [x] 可变类型直接赋值报 `TypeError`（list、dict、set、bytearray）
- [x] `field()` 参数互斥校验
- [x] 继承默认值（继承 / 覆盖 / 多级）
- [x] 构造时 kwargs 覆盖默认值
- [x] 无默认值属性未传入时仍报 `AttributeError`
- [x] 与 `@impl`、Extension、Property、reload 交互正常
- [x] 全部现有测试无回归
- 执行结果：126/126 通过（92 旧 + 34 新）

### mutagent 回归测试
- [x] 全部测试通过
- 执行结果：487/487 通过，2 跳过
