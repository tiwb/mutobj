# 安全子集类型系统

## 概述

mutobj 的 Declaration 声明了用户定义类型的数据和接口——"User 有 name、email，能 greet"。但对 Python 基础类型（int、str、list、dict 等），mutobj 一无所知。TypeSpec 补全这个缺口：用同样的 Declaration 模式，声明基础类型的可用操作。

这不是安全特性，而是类型系统的完备化。mutobj 的对象模型从"只知道用户类型"扩展为"知道所有类型"。

## 动机

### 两个消费场景

同一套类型声明支撑不同的消费模式：

**运行时检查**：验证代码执行时的属性访问是否在声明范围内。上层应用可据此构建受控执行环境——代码只能访问声明了的操作。

**静态验证**（远期）：验证 @impl 函数体内的所有访问路径是否在 Declaration 范围内。这是编译优化的前提——如果函数体的类型操作完全已知，就可以生成等价的非 Python 代码。

两者从同一个基础出发，差异只在消费方式。

### 与 Declaration 的统一

```
Declaration 子类  →  声明用户类型的接口      →  mutobj 可内省
TypeSpec 子类     →  声明基础类型的接口      →  mutobj 可内省
```

Declaration 子类的实例天然拥有白名单（`_DECLARED_METHODS` 等已有完整的声明信息）。TypeSpec 只为 Declaration 体系外的类型（Python 基础类型、第三方库类型）补充同等的声明信息。

运行时的类型内省从"知道 User 有哪些方法"扩展为"知道 str 有哪些方法"。这为所有基于类型内省的能力（验证、优化、AI 辅助）提供统一的基础。

## 安全子集语言

TypeSpec 的运行时消费场景之一是沙箱的属性访问白名单。完整的安全模型（封闭性定理、威胁分析、builtin 安全分析）见 [mutagent sandbox.md](../../../mutagent/docs/design/sandbox.md)。

## TypeSpec 框架

### 设计

```python
class TypeSpec(mutobj.Declaration):
    """基础类型接口声明的基类"""
    ...

class StrSpec(TypeSpec):
    """声明 str 类型上的可用操作"""
    def upper(self) -> str: ...
    def lower(self) -> str: ...
    def split(self, sep: str = ...) -> list[str]: ...
    # ...
```

**关键设计点**：

- **继承 Declaration**：利用 mutobj 的方法注册、内省、热重载机制
- **dunder 和非 dunder 统一**：白名单中有就能访问，没有就不能。`__len__` 和 `upper` 没有本质区别
- **上层可扩展**：mutagent 或其他应用可以定义额外的 TypeSpec 子类，为自定义类型注册白名单
- **具体白名单内容不在此定义**：具体哪些方法在白名单中是实施决策，由应用层的 spec 文档定义

### 与 Declaration 的统一查找

白名单检查时，Declaration 子类和 TypeSpec 子类走统一的查找逻辑：

```
type(obj) 是 Declaration 子类？→ 查其声明的方法集合（_DECLARED_METHODS 等）
type(obj) 有对应的 TypeSpec？   → 查 TypeSpec 声明的方法集合
都没有                          → 拒绝
```

Declaration 子类天然拥有完整的接口声明，不需要额外定义 TypeSpec。TypeSpec 只为 Declaration 体系外的类型补充声明。

### 双重角色：白名单 + 类型规范

TypeSpec 不只是方法名集合。Declaration 的方法声明包含完整的签名（参数类型 + 返回类型），TypeSpec 同样：

```python
class StrSpec(TypeSpec):
    def split(self, sep: str = ...) -> list[str]: ...
    #         ↑ 参数类型               ↑ 返回类型
```

不同消费模式从同一个 TypeSpec 提取不同层面的信息：

| 消费模式 | 提取的信息 | 用途 |
|---------|-----------|------|
| 运行时检查（沙盒） | 方法**名集合** | `.getattr` 白名单 |
| 静态验证 | 方法**签名** | @impl 函数体的访问路径验证 |
| 编译 | 完整**类型规范** | 类型推断 + 代码生成 |

编译场景示例：

```python
x = "hello".split(",")   # 查 StrSpec → split() → list[str] → x: list[str]
y = x[0].upper()          # list[str][0] → str → 查 StrSpec → upper() → str → y: str
z = len(x)                # len(list[str]) → int → z: int
```

TypeSpec 的签名为编译器提供了完整的类型推断链。Declaration 子类的方法签名同样如此——两者在编译器眼中是同一种东西。

### 白名单的构建

运行时通过内省 TypeSpec 子类构建白名单：

```
TypeSpec 子类 → 遍历声明的方法名 → {type: set[str]} 映射
```

这利用了 mutobj 已有的 `_DECLARED_METHODS` 机制。TypeSpec 的方法声明和 Declaration 的方法声明走完全相同的代码路径。

### 宿主自定义类型

宿主注入的自定义对象，如果是 Declaration 子类的实例，天然拥有白名单，无需额外声明。

如果是非 Declaration 类型（第三方库对象等），宿主需注册对应的 TypeSpec 子类。这和 mutagent 中为新的 Declaration 子类提供 @impl 是同一模式——"新类型 = 新的声明"。

## 渐进路径

| 阶段 | 消费方式 | 检查时机 | 类型信息来源 |
|------|---------|---------|-------------|
| 运行时检查 | `.getattr` 守卫查白名单 | 执行时 | `type(obj)` |
| 静态验证 | AST 分析 + 类型推断 | 执行前 | 函数签名 + TypeSpec 返回类型注解 |
| 编译 | 完整类型分析 + 代码生成 | 构建时 | 完整类型系统（TypeSpec + Declaration 签名） |

三个阶段消费同一套 TypeSpec/Declaration 定义，差异在检查时机和类型信息的获取方式。运行时检查是当前可落地的方案，静态验证和编译是远期方向。

## 与 architecture.md 的关系

architecture.md 描述了 Declaration/Extension/@impl 的设计理念——"语义层 OOP，基础设施层可优化"、"强约束换取运行时能力"。

TypeSpec 是这些理念的自然延伸：

- **强约束换取运行时能力**：要求属性访问经过白名单（约束），换取可证明的封闭性（能力）
- **语义层 OOP，基础设施层可优化**：开发者写的是自然的 Python（语义层），AST 转换和白名单检查在基础设施层透明运行
- **阶段 N 的写法不和阶段 N+1 冲突**：运行时检查阶段的代码，无需改写就能进入静态验证或编译阶段
