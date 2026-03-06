# `@impl` 继承桩方法冲突 设计规范

**状态**：✅ 已完成
**日期**：2026-02-25
**类型**：Bug修复

## 1. 背景

在 mutagent LLMProvider 抽象实施过程中（见 `mutbot/docs/specifications/feature-llm-api-proxy.md`），发现 `@impl` 装饰器在多个子类对继承的桩方法分别提供实现时，所有实现注册到同一条覆盖链，后注册者覆盖前者。

### 复现代码

```python
import mutobj

class Base(mutobj.Declaration):
    def process(self, data: str) -> str: ...

class DriverA(Base):
    pass

class DriverB(Base):
    pass

@mutobj.impl(DriverA.process)
def process_a(self, data):
    return "A: " + data

@mutobj.impl(DriverB.process)
def process_b(self, data):
    return "B: " + data

a = DriverA()
b = DriverB()
print(a.process("x"))  # 期望 "A: x"，实际 "B: x" ← 被覆盖
print(b.process("x"))  # "B: x"
```

### 发现场景

`LLMProvider` 声明 `send()` 桩方法，`AnthropicProvider` 和 `OpenAIProvider` 各自通过 `@impl` 提供实现。当两者的模块同时被 import（测试运行时），后 import 的实现覆盖前者，导致 `AnthropicProvider.send()` 实际执行 `OpenAIProvider` 的逻辑。

## 2. 设计方案

### 2.1 根本原因

**代码路径**：`core.py:754` → `core.py:118` → `core.py:210`

`@impl` 装饰器通过方法对象的 `__mutobj_class__` 属性确定目标类：

```python
# core.py:754
target_cls = getattr(method, "__mutobj_class__", None)
```

当子类**继承**父类的桩方法而未在自身类体内重新定义时，`SubClass.method` 通过 Python 的 MRO 查找返回的是**父类的方法对象**。该对象的 `__mutobj_class__` 在桩方法创建时已绑定为父类（`core.py:118`）：

```python
# core.py:109-119  _make_stub_method
stub.__mutobj_class__ = cls  # cls = Base（声明桩方法的类）
```

因此：

```
@impl(DriverA.process)  →  target_cls = Base  →  key = (Base, "process")
@impl(DriverB.process)  →  target_cls = Base  →  key = (Base, "process")  ← 同一条链！
```

两个实现注册到 `_register_to_chain`（`core.py:210`）的同一个链条 key `(Base, "process")`，按 `_impl_seq` 排序后，后注册者成为链顶（活跃实现），覆盖前者。

### 2.2 为什么类体内定义方法不受影响

当子类在类体内定义方法时（即使方法体是 `...`），`DeclarationMeta.__new__` 在处理 `namespace` 时会为该方法设置正确的 `__mutobj_class__`（`core.py:565-568`）：

```python
# core.py:559-568
for method_name, method_value in namespace.items():
    ...
    _impl_chain.setdefault((cls, method_name), []).append(
        (method_value, "__default__", 0)
    )
    method_value.__mutobj_class__ = cls  # cls = DriverA（当前子类）
```

此时 `DriverA.process` 和 `DriverB.process` 是各自独立的方法对象，拥有独立的链条 key：
- `(DriverA, "process")` — DriverA 的覆盖链
- `(DriverB, "process")` — DriverB 的覆盖链

### 2.3 影响范围

此问题影响所有满足以下全部条件的使用模式：

1. 父类声明桩方法（`def method(self): ...`）
2. 多个子类继承该方法，**不在自身类体内重新定义**
3. 通过 `@impl(SubClass.method)` 分别为各子类提供实现
4. 多个子类的模块**同时被 import**（同一进程中）

典型模式：Provider / Driver / Plugin / Strategy 等多实现抽象。

仅有一个子类使用 `@impl` 时不会触发此问题。

### 2.4 修复方案

#### 方案 A：`impl` 装饰器识别子类上下文

在 `impl` 装饰器中，当 `__mutobj_class__` 指向的类与用户实际访问的类不同时，尝试推断正确的目标类。

**思路**：`@impl(DriverA.process)` 中，`DriverA.process` 虽然返回父类的方法对象，但装饰器接收的参数 `method` 无法保留 "从 DriverA 访问" 这个上下文——Python 的属性访问 `DriverA.process` 在到达 `impl()` 时已丢失了 `DriverA` 信息。

**结论**：仅靠方法对象**无法**推断出用户意图的目标子类。此方案不可行。

#### 方案 B：显式目标类语法

扩展 `@impl` 支持 `(class, method_name)` 形式：

```python
@mutobj.impl(DriverA, "process")
def process_a(self, data):
    return "A: " + data
```

**优点**：语义明确，无歧义
**缺点**：与现有 `@impl(Class.method)` 语法风格不一致，需要同时维护两种 API

#### 方案 C：子类继承时自动创建独立链条

`DeclarationMeta.__new__` 在创建子类时，为每个**继承但未重新定义**的声明方法，自动在子类上创建独立的链条条目和桩方法。

```python
# DeclarationMeta.__new__ 中新增逻辑（伪代码）
for base in bases:
    for method_name in getattr(base, _DECLARED_METHODS, set()):
        if method_name not in namespace:  # 子类未重新定义
            # 为子类创建独立的链条条目
            stub = _make_stub_method(method_name, cls)  # cls = 子类
            _impl_chain.setdefault((cls, method_name), []).append(
                (stub, "__default__", 0)
            )
            setattr(cls, method_name, stub)
```

之后 `@impl(DriverA.process)` 访问的是 DriverA 自己的桩方法，`__mutobj_class__` 正确指向 `DriverA`。

**优点**：
- 无需改变 `@impl` 的 API 或使用方式
- 对已有代码完全透明，修复后 `@impl(SubClass.method)` 自然正确
- 符合 "子类拥有独立实现" 的语义

**缺点**：
- 每个 Declaration 子类都会为继承的声明方法创建新的链条条目，增加 `_impl_chain` 的条目数量
- 需要处理 classmethod / staticmethod / property 等变体

## 3. 待定问题

### Q1: 选择哪个修复方案？
**问题**：方案 B（显式语法）和方案 C（自动创建链条）各有取舍，选哪个？
**建议**：方案 C。对用户透明，不改变 API，符合 "子类继承即拥有独立覆盖链" 的直觉。内存开销在 Declaration 子类数量有限的场景下可忽略。

### Q2: 是否需要向后兼容？
**问题**：修复后，现有使用 `@impl(SubClass.inherited_method)` 的代码（当前仅一个子类的场景）行为是否会改变？
**建议**：不会。单子类场景下，修复前后行为一致——区别仅在于链条 key 从 `(Base, method)` 变为 `(SubClass, method)`，实际调用结果相同。

### Q3: classmethod / staticmethod / property 是否需要同步处理？
**问题**：当前 `_make_stub_classmethod` 和 `_make_stub_staticmethod` 存在同样的继承问题。
**建议**：是，一并处理。逻辑对称，遗漏会造成不一致。

## 4. 实施步骤清单

### 阶段一：修复 [✅ 已完成]

- [x] **Task 1.1**: 子类继承声明方法时自动创建独立链条
  - [x] `DeclarationMeta.__new__` 中，遍历基类的 `_DECLARED_METHODS`，为未重新定义的方法创建子类专属委托函数和链条
  - [x] 同步处理 `_DECLARED_CLASSMETHODS` 和 `_DECLARED_STATICMETHODS`
  - [x] classmethod 委托正确传递子类 cls 参数
  - 状态：✅ 已完成

### 阶段二：测试 [✅ 已完成]

- [x] **Task 2.1**: 继承冲突场景单元测试
  - [x] 多子类继承同一桩方法，各自 `@impl` 后行为独立
  - [x] 单子类场景行为不变（回归）
  - [x] 子类 @impl 不影响父类
  - [x] classmethod / staticmethod 继承场景
  - [x] 深层继承链（A → B → C，C 有自己的实现，B 继承 A 的）
  - [x] 子类未提供 @impl 时委托给基类实现
  - 状态：✅ 已完成

- [x] **Task 2.2**: mutbot 集成验证
  - [x] session_impl.py 生命周期方法改为 per-subclass @impl（TerminalSession.on_create, AgentSession.on_stop 等）
  - [x] 移除 isinstance 分支
  - [x] 381 tests passed
  - 状态：✅ 已完成

## 5. 测试验证

### 单元测试（mutobj 154 passed）
- [x] 多子类 `@impl` 独立性
- [x] 单子类回归
- [x] 子类 @impl 不影响父类
- [x] classmethod / staticmethod 变体
- [x] 深层继承链
- [x] 子类未 @impl 时委托基类

### 集成测试（mutbot 381 passed）
- [x] session_impl.py 生命周期方法改为 per-subclass @impl
- [x] 移除所有 isinstance 分支
