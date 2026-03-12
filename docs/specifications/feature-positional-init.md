# Declaration 位置参数初始化 设计规范

**状态**：📝 设计中
**日期**：2026-03-12
**类型**：功能设计

## 背景

Declaration 当前只支持关键字参数初始化：

```python
class User(mutobj.Declaration):
    name: str
    age: int

user = User(name="Alice", age=30)  # ✅ 唯一写法
user = User("Alice", 30)           # ❌ TypeError
```

`__init__` 签名是 `**kwargs`，不接受位置参数。这在大多数场景下够用，但对某些类型不够自然：

```python
# 自然的写法应该是
resp = Response(200, b"hello")

# 而非
resp = Response(status=200, body=b"hello")
```

### 动机

mutagent.net Declaration 化重构中，`Request`、`Response` 等协议类型需要 Declaration 化。这些类型的构造场景（框架内部高频创建）需要简洁的位置参数写法。同时，位置参数是 Python 类的基本能力，Declaration 作为"结构化的 Python 类"应该支持。

## 设计原则

**`__init__` 遵循标准 Python 行为，Declaration 不添加任何 `__init__` 特殊规则。**

参照 dataclass 的处理方式：
- dataclass：不写 `__init__` → 自动生成；写了 → 被覆盖（需 `init=False` opt-out）
- Declaration：不写 `__init__` → 自动生成（含位置参数）；写了 → 你的，Declaration 不碰

Declaration 的写法必须完全兼容标准 Python。`__init__` 走 Declaration 的标准方法流程（桩/impl/覆盖链），不添加 `__init__` 专属的额外规则。桩 `__init__` 和其他桩方法行为完全一致，无特殊化。

## 已确定的设计

### 场景一：不写 `__init__` — 自动生成（dataclass 行为）

```python
class Response(mutobj.Declaration):
    status: int = 200
    body: bytes = b""

Response(404, b"hello")     # ✅ 位置参数，按字段声明顺序
Response(status=404)        # ✅ 关键字（现有行为不变）
Response(404, body=b"hello") # ✅ 混合
```

字段声明顺序自动成为位置参数顺序，与 dataclass 一致。向后兼容：现有纯 kwargs 写法不受影响（`**kwargs` → `*args, **kwargs`）。

### 场景二：写了 `__init__` — 标准 Python 行为

无论 `__init__` 内容是什么（实现体、桩、`pass`），Declaration 都不干预。它就是一个普通的 Python 方法。

**有实现体 — 跑用户的代码**：

```python
class Request(mutobj.Declaration):
    method: str = "GET"
    path: str = "/"

    def __init__(self, scope: dict, receive: Any):
        self.method = scope.get("method", "GET")
        self.path = scope.get("path", "/")
```

用户完全控制构造逻辑。构造签名可以与字段不同（如 `scope, receive` vs `method, path`）。

**桩 + `@impl` — Declaration 模式**：

```python
class Request(mutobj.Declaration):
    method: str = "GET"
    path: str = "/"

    def __init__(self, scope: dict, receive: Any): ...

# _impl.py
@mutobj.impl(Request.__init__)
def _request_init(self: Request, scope: dict, receive: Any):
    self.method = scope.get("method", "GET")
    self.path = scope.get("path", "/")
```

桩声明构造签名，`@impl` 提供实现。与其他声明方法一致的模式。

**桩无 `@impl` — 与其他桩方法一致**：

桩 `__init__` 没有 `@impl` 时，行为与其他桩方法一致：空操作，字段拿默认值（metaclass 保证）。这种写法通常无意义——想要自动位置参数应该不写 `__init__`（场景一），想要自定义构造逻辑应该写实现体或 `@impl`。

### 字段默认值与 `__init__` 的关系

当前实现中，字段默认值在 `Declaration.__init__` 中应用。自定义 `__init__` 绕过了这一机制，未赋值的字段无值。

未来可能将默认值应用提升到 metaclass 层面（`__new__` 或 `__init_subclass__`），使默认值始终可用，不依赖 `__init__` 的调用。这是独立的优化方向，不影响本次位置参数功能。

## 实施方案（场景一：自动生成）

不写 `__init__` 时的自动位置参数支持，修改 `Declaration.__init__`：

```python
def __init__(self, *args: Any, **kwargs: Any) -> None:
    # 1. 收集有序字段列表（沿 MRO，基类在前，子类在后，去重）
    fields = _get_ordered_fields(type(self))

    # 2. 位置参数映射到字段名
    if args:
        if len(args) > len(fields):
            raise TypeError(...)
        for i, value in enumerate(args):
            name = fields[i]
            if name in kwargs:
                raise TypeError(f"got multiple values for '{name}'")
            kwargs[name] = value

    # 3. 后续逻辑不变——遍历 MRO 应用 kwargs + 默认值
    ...
```

字段顺序缓存在类级别（`_ordered_fields_cache`），`DeclarationMeta.__new__` 末尾构建。

### 向后兼容性

完全向后兼容：
- 现有纯 kwargs 写法不受影响
- `__init__` 签名从 `(**kwargs)` 变为 `(*args, **kwargs)`
- 无需修改任何现有 Declaration 子类

## 未来预留

当前自动生成的位置参数（场景一）已覆盖实际需求（`Response(404, b"hello")`）。对于构造签名与字段不同的场景（`Request(scope, receive)`），用户写自定义 `__init__` 即可。

未来可能需要一种方式来"声明自定义位置参数签名但不写完整实现"——即在不写 `__init__` 实现体的前提下定制构造签名。具体形式待需求驱动，当前不设计。

### 继承时字段顺序

与 dataclass 一致：**父类字段在前，子类字段在后**。多继承按 Python C3 线性化（MRO）顺序。

```python
class Base(Declaration):
    x: int = 0

class Child(Base):
    y: str = ""

Child(1, "hello")  # x=1, y="hello" — 父类在前

# 多继承
class A(Declaration):
    x: int = 0

class B(Declaration):
    y: str = ""

class C(A, B):
    z: float = 0.0

# MRO: C → A → B，字段顺序：x, y, z
C(1, "hello", 3.14)
```

注：Declaration 当前 `__init__` 的 MRO 遍历是子类优先（覆盖优先级），这和位置参数顺序是两回事。位置参数顺序沿 MRO 从基类到派生类收集（去重，先出现的保留）。

## 关键参考

### 源码
- `mutobj/src/mutobj/core.py:713-733` — 当前 `Declaration.__init__` 实现（`**kwargs` only）
- `mutobj/src/mutobj/core.py:437-544` — `DeclarationMeta.__new__`，字段注册逻辑
- `mutobj/src/mutobj/core.py:240-280` — `AttributeDescriptor`，字段描述符
- `mutobj/src/mutobj/core.py:110-148` — 桩方法创建（`_make_stub_method`），当前不做 AST 解析
- `mutobj/src/mutobj/core.py:600-611` — 声明方法注册，所有公开方法（含 `...` 体）作为默认实现

### 相关规范
- `mutobj/docs/design/architecture.md` — "阶段 N 的 API 写法不能和阶段 N+1 的优化冲突"
- `mutagent/docs/specifications/refactor-net-declarations.md` — net 层 Declaration 化（本功能的直接需求方）
