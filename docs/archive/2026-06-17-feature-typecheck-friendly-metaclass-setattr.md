# Pyright 友好的元类 `__setattr__` 设计规范

**状态**：✅ 已完成
**日期**：2026-06-17
**类型**：功能设计

## 关键参考

- `src/mutobj/core/_declaration.py:344` — `DeclarationMeta.__setattr__`，含 `FieldSpec` / `AttributeDescriptor` 分支处理
- `src/mutobj/core/_extensions.py:117` — `ExtensionMeta.__setattr__`，仅 descriptor 分支 + 通用校验
- `src/mutobj/core/_implementation.py:362` — `ImplementationMeta.__setattr__`，结构与 Extension 相同
- `src/mutobj/core/_fields.py:454` — `validate_class_setattr`，三处元类共享的运行时校验函数
- mutobj `__init__.py` 不导出 Meta 类，三个元类均为内部实现细节
- pyright `reportAttributeAccessIssue` — 类对象属性赋值的内置检测规则
- `src/mutobj/core/_fields.py:488` — `handle_field_setattr()`，三个元类 `__setattr__` 共享的字段赋值处理函数
- `src/mutobj/core/_classmeta.py:23` — `MutobjClassMeta`，共享基类，含 `fields` / `ordered_descriptors`
- `tests/type_check/` — pyright 回归测试框架（正向 fixtures + 反向 expected_errors）

## 背景

### 现象

`mutbot/src/mutbot/web/server.py` 出现运行时错误：

```
TypeError: Cannot set '_app' on class 'PySandboxTools':
class-level data must be declared with ClassVar[...] annotation.
```

来源：mutagent 把 `PySandboxTools` 的属性从 `_app` 改名为 `env`，但 mutbot 未同步，仍写 `PySandboxTools._app = sandbox_app`。该错误本可在 pyright 阶段拦下，但 pyright 没报，直到运行时由 mutobj 元类 `__setattr__` 拦截。

### 根本原因

pyright 默认开启 `reportAttributeAccessIssue`，能检测类对象未声明属性的赋值。但**遇到自定义元类 `__setattr__` 时，pyright 主动放弃此检查**——元类 `__setattr__` 可以做任意事情（允许任意名字、转发、抛错），静态推断保守地选择不报。

mutobj 的三个元类都重写了 `__setattr__` 用于运行时严格校验（`validate_class_setattr`），副作用是 pyright 在所有 `Declaration` / `Extension` / `Implementation` 子类上失去了类属性赋值的静态检查。

### 实验验证

5 种场景对照（用同一个 `Cls.y = 2` 测试，`y` 未在类上声明）：

| 场景 | pyright 报错 |
|---|---|
| 普通类 | ✅ |
| 类自身 `__slots__` | ✅ |
| 元类 `__slots__`（无 `__setattr__`） | ✅ |
| 自定义元类（无 `__setattr__`） | ✅ |
| **自定义元类 + 重写 `__setattr__`** | ❌ |

确认：**触发 pyright 放弃的唯一条件是元类有 `__setattr__`**，与 `__slots__` 无关。

## 设计方案

### 核心思路

让 pyright 在静态层"看不到"元类的 `__setattr__`，但运行时仍然存在并生效。利用 `typing.TYPE_CHECKING` 实现：

```python
from typing import TYPE_CHECKING

class DeclarationMeta(type):
    # ... 其他逻辑

    if not TYPE_CHECKING:
        def __setattr__(cls, name, value):
            # 现有运行时逻辑保持不变
            ...
```

效果：
- **静态层**：pyright 看到的元类没有 `__setattr__`，恢复 `reportAttributeAccessIssue` 检查
- **运行时层**：`__setattr__` 照常存在，`validate_class_setattr` / `FieldSpec` 等所有现有拦截逻辑无变化

### 二次实验验证

```python
class MetaB(type):
    if not TYPE_CHECKING:
        def __setattr__(cls, name, value):
            super().__setattr__(name, value)

class B(metaclass=MetaB):
    x: int = 1

B.y = 2  # ✅ pyright 报错（恢复检查）
B.x = 3  # ✅ pyright 通过（已声明）
```

实测结论：方案有效，且不误报已声明属性的合法赋值。

### 受影响的元类

三处元类对称改造：

| 文件 | 元类 | 现有 `__setattr__` 复杂度 |
|---|---|---|
| `_declaration.py` | `DeclarationMeta` | 含 `AttributeDescriptor` / `FieldSpec` / 父类继承字段查找等多分支 |
| `_extensions.py` | `ExtensionMeta` | descriptor 分支 + `validate_class_setattr` |
| `_implementation.py` | `ImplementationMeta` | 与 Extension 结构相同 |

三处只需把 `def __setattr__` 整个方法体（含所有现有分支）整体放入 `if not TYPE_CHECKING:` 块内，不改逻辑。

### 风险评估

**风险点**：mutobj 内部是否有代码依赖元类 `__setattr__` 的静态签名（例如 `super().__setattr__()` 显式调用、类型注解引用）？

**扫描结果**（`rg -n "__setattr__" src/`）：mutobj 内部所有类属性赋值统一走 `type.__setattr__(cls, ...)` 绕过元类，**没有任何代码依赖元类自身 `__setattr__` 的可见性**。三个元类也都未对外导出（`__init__.py` 不导出）。

风险等级：低。

### 兼容性

- 运行时行为：完全不变（`__setattr__` 在运行时存在）
- 类型检查行为：`Declaration` / `Extension` / `Implementation` 子类的类属性赋值会被 pyright 检查，**这是新增检查**，可能会让原本静默通过的 mutobj 下游项目（mutbot / mutagent / mutgui / mutio）冒出新的 pyright 错误
- 这些新报的错误本身是**真 bug**（mutbot 的 `_app` 即是典型例子），归类为"修复了之前漏报"，不算 breaking change

### 下游消费场景

| 消费者 | 验收标准 |
|---|---|
| mutbot pyright | mutbot 的 `PySandboxTools._app = ...` 在静态阶段被红线标出（已通过手工修复消除该 bug，验收时回退验证） |
| mutagent pyright | 全量 pyright 通过；如冒出新错误，逐个修复（对 `Declaration` 子类的非法类属性赋值视为真 bug） |
| mutio / mutgui pyright | 同上 |
| mutobj 自身 pyright | 全量通过（mutobj 内部不该有这类错误，否则属于自查问题） |

## 实施情况

### 三处 `TYPE_CHECKING` 守卫

`DeclarationMeta`、`ExtensionMeta`、`ImplementationMeta` 的 `__setattr__` 均已
包裹在 `if not TYPE_CHECKING:` 内，三处结构完全一致：

```python
# __setattr__ 对 pyright 隐藏（TYPE_CHECKING=True 时不可见），
# 避免元类自定义 __setattr__ 导致 pyright 放弃 reportAttributeAccessIssue
# 检查。运行时（TYPE_CHECKING=False）方法仍然存在，handle_field_setattr()
# 内的字段校验/转换逻辑照常执行。
if not TYPE_CHECKING:
    def __setattr__(cls, name, value):
        handle_field_setattr(cls, name, value, "Declaration")
```

### 字段赋值逻辑共享

实施过程中发现 `DeclarationMeta.__setattr__` 比另两个元类多了字段重新赋值
逻辑（`FieldSpec` 转换、可变默认拦截、descriptor 包装、cache 更新），而这些
逻辑对三种元类应完全一致。因此提取了共享函数 `handle_field_setattr()`，
统一处理三条分支：

1. `AttributeDescriptor` 直通 → 校验 + set
2. 已有 descriptor → 可变默认拦截、`FieldSpec` 转换/值包装、cache 更新
3. 非字段属性 → `validate_class_setattr` + set

Cache 更新通过 `mutobj_meta_cache`（共享基类）访问，三种 `*ClassMeta` 都继承
`fields` + `ordered_descriptors`，Extension / Implementation 运行时字段重新赋值后
缓存同样正确更新。

### 待定问题决议

- **Q1**：只守卫 `__setattr__`，其他钩子不涉及 `reportAttributeAccessIssue`，无需改动。
- **Q2**：pyright 测试框架已建立，见下方「测试验证」。位置 `tests/type_check/`。
- **Q3**：暂缓。用户文档更新可在后续独立 PR 中完成。

## 测试验证

在已有测试框架（``tests/type_check/``）基础上，扩展了反向 fixture：

- ``declaration_field_errors.py`` — Declaration 子类的 8 条预期错误
- ``extension_field_errors.py`` — Extension 子类的 8 条预期错误（新增）
- ``implementation_field_errors.py`` — Implementation 子类的 8 条预期错误（新增）

覆盖类级 + 实例级的已知字段赋错类型、不存在的字段赋值、字段默认值类型错误。
全部 494 个测试通过。
