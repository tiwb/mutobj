# Declaration 子类发现与变更检测 API 设计规范

**状态**：✅ 已完成
**日期**：2026-02-24
**类型**：功能设计

## 1. 背景

mutobj 的 `DeclarationMeta` 元类将所有 `Declaration` 子类注册到 `_class_registry`，但目前没有提供查询该 registry 的公开 API。下游项目需要自行扫描 `_class_registry` 来发现特定基类的子类，导致重复实现和对内部结构的直接依赖。

此外，下游项目在发现子类之后还需要检测变更（热重载场景），目前依赖 `ModuleManager` 的模块级版本号作为代理，存在语义偏差。

### 1.1 现有使用方

| 项目 | 位置 | 用途 | 变更检测方式 |
|------|------|------|-------------|
| mutagent | `builtins/tool_set_impl.py:78` | 发现所有 `Toolkit` 子类，支持热重载 + 版本追踪 | `ModuleManager.get_version(cls.__module__)` |
| mutagent | `builtins/userio_impl.py:324` | 发现所有 `BlockHandler` 子类 | 无（一次性扫描） |
| mutbot（计划） | `runtime/session.py` | 发现所有 `Session` 子类 | 待定 |
| mutbot（计划） | `runtime/menu.py` | 发现所有 `Menu` 子类 | 待定 |

### 1.2 共同模式：子类发现

这些实现的核心发现逻辑完全相同：

```python
from mutobj.core import _class_registry
result = [
    cls for cls in _class_registry.values()
    if cls is not BaseClass and issubclass(cls, BaseClass)
]
```

区别仅在于后续处理（实例化策略、版本追踪等），属于应用层关注点。

### 1.3 版本追踪现状分析

**ToolSet 的变更检测流程**（`tool_set_impl.py:118-200`）：

```
dispatch()/query()/get_tools()
  → _refresh_discovered()
    → _discover_toolkit_classes()          # 每次全量扫描 _class_registry
    → 对每个已发现类:
        module_name = cls.__module__
        current_version = ModuleManager.get_version(module_name)
        if version != state['version']:    # 版本变了 → 重建 ToolEntry
            _make_entries_for_toolkit(...)
```

**语义偏差**：ModuleManager 追踪的是"模块被 patch 的次数"，而 ToolSet 真正关心的是"类的方法实现是否变了"。两者存在以下不一致：

| 场景 | ModuleManager 版本 | 实际类行为 | 结果 |
|------|-------------------|-----------|------|
| 模块 A 的 Toolkit 类，`@impl` 从模块 B 注册 | A 的版本不变 | 方法实现已变 | **漏检** — 不会刷新 |
| 模块 A 被 patch 但只改了辅助函数 | A 的版本 +1 | Toolkit 方法不变 | **误刷** — 不必要的重建 |
| `unregister_module_impls` 移除了实现 | 无版本变化 | 方法回退到链上一层 | **漏检** |

**关键认识**：mutobj 的 `_impl_chain` 和 `_class_registry` 是类变更的**唯一真实来源**。ModuleManager 版本只是一个近似代理。在当前 mutagent 使用场景中这个近似足够（Toolkit 的 `@impl` 通常和类定义在同一模块），但对通用场景并不成立。

### 1.4 mutobj 内部已有的变更信息

mutobj 内部实际上已经追踪了所有变更事件，只是没有对外暴露：

| 内部状态 | 变更时机 | 信息 |
|---------|---------|------|
| `_class_registry[key] = cls` | `DeclarationMeta.__new__` — 类首次定义 | 新类注册 |
| `_update_class_inplace(existing, cls)` | `DeclarationMeta.__new__` — reload 场景 | 类就地更新 |
| `_register_to_chain(cls, key, func, module)` | `@impl` 装饰器执行 | 实现注册/替换 |
| `unregister_module_impls(module_name)` | 模块卸载 | 实现移除，链回退 |
| `_impl_seq` 全局计数器 | 每次 `_register_to_chain` | 单调递增序号 |

## 2. 设计方案

### 2.1 子类发现 API（已确定）

在 `mutobj` 包级别提供 `discover_subclasses` 函数：

```python
def discover_subclasses(base_cls: type[T]) -> list[type[T]]:
    """返回 _class_registry 中 base_cls 的所有子类（不含 base_cls 自身）。

    每次调用重新扫描 registry，结果反映当前注册状态。
    支持运行时新增类（模块加载）和移除类（模块卸载）。

    Args:
        base_cls: 要查找子类的基类，必须是 Declaration 的子类

    Returns:
        base_cls 的所有已注册子类列表（不保证顺序）
    """
```

行为语义：

| 行为 | 说明 |
|------|------|
| 返回值 | `_class_registry` 中所有 `issubclass(cls, base_cls)` 且 `cls is not base_cls` 的类 |
| 调用时机 | 每次调用实时扫描，无缓存 |
| 线程安全 | 与 `_class_registry` 的写入一致（CPython GIL 保护） |
| 模块卸载 | 类从 `_class_registry` 移除后，下次调用不再返回 |
| 热重载 | `DeclarationMeta` 就地更新类对象，discover 返回的是更新后的类引用 |
| 传入非 Declaration | 返回空列表（registry 中只有 Declaration 子类） |

实现：

```python
# mutobj/core.py 中添加

def discover_subclasses(base_cls: type) -> list[type]:
    """返回 _class_registry 中 base_cls 的所有已注册子类。"""
    return [
        cls for cls in _class_registry.values()
        if cls is not base_cls and isinstance(cls, type) and issubclass(cls, base_cls)
    ]
```

在 `mutobj/__init__.py` 中导出：

```python
from mutobj.core import Declaration, Extension, impl, field, \
    register_module_impls, unregister_module_impls, discover_subclasses
```

### 2.2 变更检测 API：全局 generation 计数器

下游在发现子类后，还需检测类是否发生了变更（新增/移除/实现更新），以决定是否刷新缓存。当前方案依赖 `ModuleManager` 模块级版本号，存在语义偏差（见 §1.3）。

采用全局 generation 计数器方案：在 `_class_registry` 或 `_impl_chain` 发生任何变更时递增一个全局计数器，使用单一计数器（不区分类注册变更和实现变更）。未来如有精确到类级别的需求，可额外实现 per-class 版本号，与 generation 计数器共存。

```python
# core.py 新增
_registry_generation: int = 0

def get_registry_generation() -> int:
    """返回注册表的当前 generation 号。

    任何类注册/更新、@impl 注册/卸载都会导致 generation 递增。
    调用方可通过比较前后 generation 判断是否需要重新扫描。
    """
    return _registry_generation
```

递增点（在现有代码中插入 `_registry_generation += 1`）：
- `DeclarationMeta.__new__` — 类首次注册或就地更新时
- `_register_to_chain` — `@impl` 注册时
- `unregister_module_impls` — 实现卸载时

下游用法：
```python
# ToolSet._refresh_discovered 优化
if mutobj.get_registry_generation() == self._last_generation:
    return  # 短路：注册表没有任何变化
self._last_generation = mutobj.get_registry_generation()
# ... 执行完整扫描和版本检查
```

### 2.3 下游迁移

**mutagent `tool_set_impl.py`**：
```python
# 前
from mutobj.core import _class_registry
from mutagent.tools import Toolkit
def _discover_toolkit_classes() -> list[type]:
    return [cls for (module_name, qualname), cls in _class_registry.items()
            if cls is not Toolkit and issubclass(cls, Toolkit)]

# 后
import mutobj
from mutagent.tools import Toolkit
def _discover_toolkit_classes() -> list[type]:
    return mutobj.discover_subclasses(Toolkit)
```

**mutagent `userio_impl.py`**：
```python
# 前
from mutobj.core import _class_registry
handlers = {}
for cls in _class_registry.values():
    if cls is BlockHandler or not isinstance(cls, type) or not issubclass(cls, BlockHandler):
        continue
    ...

# 后
import mutobj
for cls in mutobj.discover_subclasses(BlockHandler):
    ...
```

**mutbot（新代码，直接使用）**：
```python
import mutobj
from mutbot.runtime.session import Session
session_types = mutobj.discover_subclasses(Session)
```

## 3. 待定问题

（无）

## 4. 实施步骤清单

### 阶段一：mutobj 核心实现 [✅ 已完成]
- [x] **Task 1.1**: 在 `core.py` 中实现 `discover_subclasses`
  - [x] 添加函数实现
  - [x] 添加到 `__all__`
  - 状态：✅ 已完成

- [x] **Task 1.2**: 在 `core.py` 中实现 `get_registry_generation`
  - [x] 添加 `_registry_generation` 全局变量
  - [x] 在 `DeclarationMeta.__new__` 中递增
  - [x] 在 `_register_to_chain` 中递增
  - [x] 在 `unregister_module_impls` 中递增
  - [x] 添加 `get_registry_generation()` 公开函数
  - [x] 添加到 `__all__`
  - 状态：✅ 已完成

- [x] **Task 1.3**: 在 `__init__.py` 中导出
  - [x] 更新 import 和 `__all__`（`discover_subclasses` + `get_registry_generation`）
  - 状态：✅ 已完成

- [x] **Task 1.4**: 添加单元测试
  - [x] `discover_subclasses` 测试（见 §5）
  - [x] `get_registry_generation` 测试（见 §5）
  - 状态：✅ 已完成

### 阶段二：下游迁移 [✅ 已完成]
- [x] **Task 2.1**: 迁移 mutagent `tool_set_impl.py`
  - [x] 替换 `_discover_toolkit_classes()` 为 `mutobj.discover_subclasses(Toolkit)`
  - [x] 用 `get_registry_generation` 短路优化 `_refresh_discovered`
  - [x] 验证 ToolSet auto_discover 功能
  - 状态：✅ 已完成

- [x] **Task 2.2**: 迁移 mutagent `userio_impl.py`
  - [x] 替换 `discover_block_handlers()` 中的扫描逻辑
  - [x] 验证 BlockHandler 发现
  - 状态：✅ 已完成

## 5. 测试验证

### 单元测试 — discover_subclasses
- [x] `test_discover_basic` — 定义 A(Declaration), B(A), C(A)，discover_subclasses(A) 返回 {B, C}
- [x] `test_discover_deep` — 定义 A, B(A), C(B)，discover_subclasses(A) 返回 {B, C}
- [x] `test_discover_empty` — 无子类时返回空列表
- [x] `test_discover_excludes_base` — base_cls 自身不在结果中
- [x] `test_discover_after_unregister` — 模块卸载后类不再被发现

### 单元测试 — get_registry_generation
- [x] `test_generation_increments_on_class_define` — 定义新 Declaration 子类后 generation 递增
- [x] `test_generation_increments_on_impl` — `@impl` 注册后 generation 递增
- [x] `test_generation_increments_on_unregister` — 模块卸载后 generation 递增
- [x] `test_generation_stable_without_changes` — 无操作时 generation 保持不变
- [x] `test_generation_as_short_circuit` — 验证 generation 不变时可安全跳过扫描

- 执行结果：12/12 通过（含额外 `test_discover_non_declaration` 和 `test_generation_no_increment_on_empty_unregister`）
