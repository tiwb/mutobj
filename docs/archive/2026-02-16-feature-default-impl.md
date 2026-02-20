# 移除 AST 桩检测，简化核心机制 设计规范

**状态**：✅ 已完成
**日期**：2026-02-16
**类型**：重构

## 1. 背景

当前 mutobj 通过 `_is_stub_method` 函数对每个方法执行 `inspect.getsource` + `ast.parse`，检测 `...` 和 `pass` 桩方法。存在以下问题：

1. **pyc 兼容性**：编译后的 `.pyc` 文件没有源码，`inspect.getsource` 会失败，导致所有桩检测失效
2. **不必要的复杂性**：Declaration 本身的语义就是"声明类/接口"，其中**所有**公开方法都应视为声明，不需要逐方法做 AST 分析来判断是否为桩

此外，经过对 IDE 跳转和默认实现自动加载的讨论，得出：
- **IDE 跳转**：Python 原生机制即可（`TYPE_CHECKING` 导入、函数体内 import，Ctrl+Click 跳转到实现模块）
- **延迟加载**：Python 原生语法即可（模块级 import 或函数体内 import + 转发）

同时，当前的 `unregister_module_impls` 过于暴力——卸载后直接恢复为 stub，丢失了中间层实现。需要支持完整的覆盖链条。

## 2. 设计方案

### 2.1 移除 AST，改为类型检查收集声明

**核心变化**：Declaration 是接口类，其中**所有公开方法**都是声明。不需要检查方法体是否为 `...` / `pass`，只需检查类型（callable / classmethod / staticmethod / property）。

**移除项**：

| 移除项 | 说明 |
|--------|------|
| `_is_stub_method()` | AST 桩方法检测函数（~50 行） |
| `import ast, inspect, textwrap` | 不再需要的标准库导入 |

**保留项**（逻辑调整）：

| 保留项 | 变化 |
|--------|------|
| `_make_stub_method()` 等 | 保留作为安全回退（覆盖链异常为空时使用） |
| `_DECLARED_METHODS` 等 | 保留，改为收集所有公开方法（移除 `_is_stub_method` 条件判断） |
| `Property` 桩替换 | 保留，所有 `@property` 自动转为 `mutobj.Property`（移除 AST 条件） |

**DeclarationMeta.__new__ 变更**：

```python
# 现有（AST 检测）：
if callable(method_value) and not isinstance(method_value, (classmethod, staticmethod, property)):
    if _is_stub_method(method_value):      # ← 移除此条件
        declared_methods.add(method_name)
        stub = _make_stub_method(method_name, cls)
        setattr(cls, method_name, stub)

# 改为（类型检查，无 AST）：
if callable(method_value) and not isinstance(method_value, (classmethod, staticmethod, property)):
    declared_methods.add(method_name)
    # 保存原始函数作为默认实现到覆盖链（seq=0）
    _impl_chain.setdefault((cls, method_name), []).append(
        (method_value, "__default__", 0)
    )
    # 标记类引用，便于 @impl 查找目标类
    method_value.__mutobj_class__ = cls
```

classmethod、staticmethod、property 同理——移除 `_is_stub_method` 条件，保存原始函数作为默认实现到覆盖链。

### 2.2 实现覆盖链（impl chain）

**问题**：当前 `_method_registry` 和 `_impl_sources` 只记录最新实现。卸载中间模块时，无法恢复到上一层。

**场景**：
```
default → Module A impl → Module B override → Module C override
卸载 B → 应恢复为 [default, A, C]，C 仍为活跃实现
卸载 C → 应恢复为 [default, A]，A 为活跃实现
卸载全部外部 impl → 应恢复为 [default]，default 为活跃实现
Reload B → B 的函数更新，但 C 仍为活跃实现（中间层 reload 不影响活跃方法）
```

**新数据结构**：用 `_impl_chain` 替换 `_method_registry` 和 `_impl_sources`。

```python
# 实现覆盖链：{(类, 方法名或属性访问器): [(实现函数, 来源模块, 注册序号), ...]}
# 按注册序号排序，列表尾部（最高序号）= 当前活跃实现
_impl_chain: dict[tuple[type, str], list[tuple[Callable[..., Any], str, int]]] = {}

# 全局注册序号计数器
_impl_seq: int = 0

# 模块首次注册序号（reload 时复用，保持链中位置不变）
_module_first_seq: dict[tuple[type, str, str], int] = {}  # (cls, key, module) -> seq
```

Property getter/setter 使用与现有 `_impl_sources` 一致的键格式：`(cls, "prop.getter")` / `(cls, "prop.setter")`。

**默认实现**：DeclarationMeta.__new__ 在处理每个公开方法时，将原始函数保存到覆盖链作为默认实现（seq=0, source=`"__default__"`）。原始函数保留在类上，不替换为 stub。当所有外部 @impl 被卸载后，自动恢复为默认实现。`unregister_module_impls` 不会移除 `"__default__"` 条目，因此覆盖链在正常流程下不会为空。

**@impl 注册时**：

```python
key = (target_cls, method_name)
chain = _impl_chain.setdefault(key, [])
seq_key = (target_cls, method_name, source_module)

# 1. 检查同模块已有注册（importlib.reload 直接重新执行，未卸载）
existing_idx = next((i for i, (_, m, _) in enumerate(chain) if m == source_module), None)

if existing_idx is not None:
    # 就地替换，保持序号和位置
    old_seq = chain[existing_idx][2]
    chain[existing_idx] = (func, source_module, old_seq)
    if existing_idx == len(chain) - 1:
        setattr(target_cls, method_name, func)  # 仅链顶更新类方法
    return

# 2. 检查卸载后重新注册（unregister + reimport）
if seq_key in _module_first_seq:
    seq = _module_first_seq[seq_key]  # 复用首次序号，回到原位置
else:
    # 3. 全新注册
    if chain and not override:
        raise ValueError(f"Method '{method_name}' already implemented ...")
    _impl_seq += 1
    seq = _impl_seq
    _module_first_seq[seq_key] = seq

chain.append((func, source_module, seq))
chain.sort(key=lambda x: x[2])  # 按序号排序
# 仅当新条目成为链顶时才更新类方法
if chain[-1][1] == source_module:
    setattr(target_cls, method_name, func)  # classmethod/staticmethod 需包装
```

**unregister_module_impls 卸载时**：

```python
for key in list(_impl_chain):
    cls, impl_key = key
    chain = _impl_chain[key]
    was_top_module = chain[-1][1] == module_name if chain else False

    # 移除指定模块的所有条目（不删除 _module_first_seq，reload 时复用）
    before = len(chain)
    chain[:] = [(f, m, s) for f, m, s in chain if m != module_name]
    removed += before - len(chain)

    if not chain:
        # 链为空（无默认实现的异常情况），恢复 stub
        _restore_stub(cls, impl_key)
        del _impl_chain[key]
    elif was_top_module:
        # 活跃实现被卸载，恢复为新链顶
        _apply_impl(cls, impl_key, chain[-1][0])
    # 若卸载的是中间层，活跃实现不变，无需操作
```

**Reload 工作流**：impl 模块的 reload 有两种方式，均保证中间层 reload 不影响活跃方法：

1. **直接 reimport**：`importlib.reload(module)` → @impl 检测同模块已有注册，就地替换函数，位置不变
2. **卸载 + reimport**：`unregister_module_impls(name)` + `importlib.reload(module)` → @impl 通过 `_module_first_seq` 复用首次序号，回到链中原位置

```python
# 方式1：直接 reload
importlib.reload(my_app.user_impl)

# 方式2：卸载 + reload
unregister_module_impls("my_app.user_impl")
importlib.reload(my_app.user_impl)
```

**_migrate_registries（Declaration reload）**：

Declaration 模块被 reload 时，DeclarationMeta.__new__ 为 new_cls 创建新的默认实现条目。`_migrate_registries` 需要将新默认实现合并到 existing 的覆盖链中：

```python
def _migrate_registries(existing: type, new_cls: type) -> None:
    # 合并 _impl_chain：
    for key in list(_impl_chain):
        cls, impl_key = key
        if cls is not new_cls:
            continue

        new_chain = _impl_chain.pop(key)
        existing_key = (existing, impl_key)
        existing_chain = _impl_chain.get(existing_key, [])

        # 从新链中提取新的默认实现
        new_default = next(((f, m, s) for f, m, s in new_chain if m == "__default__"), None)

        if existing_chain:
            # 替换已有链中的默认实现条目
            for i, (f, m, s) in enumerate(existing_chain):
                if m == "__default__":
                    if new_default is not None:
                        existing_chain[i] = new_default
                    break
        else:
            # 无已有链，直接使用新链
            existing_chain = new_chain

        _impl_chain[existing_key] = existing_chain

        # 重新应用链顶实现到类上
        if existing_chain:
            _apply_impl(existing, impl_key, existing_chain[-1][0])

    # 迁移 _module_first_seq 条目
    keys_to_migrate = [k for k in _module_first_seq if k[0] is new_cls]
    for k in keys_to_migrate:
        _module_first_seq[(existing, k[1], k[2])] = _module_first_seq.pop(k)
```

### 2.3 @impl 校验变更

移除 `_DECLARED_METHODS` 等集合的校验（因为 Declaration 中所有公开方法都是声明），改为检查方法是否存在于类上：

```python
if not hasattr(target_cls, method_name):
    raise ValueError(f"Method '{method_name}' does not exist in {target_cls.__name__}")
```

classmethod/staticmethod 类型判断改为检查类的 `__dict__`：

```python
existing = target_cls.__dict__.get(method_name)
is_classmethod = isinstance(existing, classmethod)
is_staticmethod = isinstance(existing, staticmethod)
```

### 2.4 用户侧写法

**声明文件**（不变，但语义更清晰）：

```python
class User(Declaration):
    name: str
    email: str

    def greet(self) -> str:
        """返回问候语"""
        ...                        # 方法体作为默认实现保存到覆盖链

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        ...

    @property
    def display_name(self) -> str:
        ...
```

**IDE 跳转推荐约定**（Python 原生模式，不需要 mutobj 代码支持）：

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from . import user_impl

class User(Declaration):

    # 方式1：TYPE_CHECKING 导入
    def greet(self) -> str:
        impl: user_impl.greet # IDE 可识别类型，跳转到实现

    # 方式2：函数体内 import + 转发（精确到函数 + 延迟加载）
    def greet(self) -> str:
        from .user_impl import greet
        return greet(self)
```

**延迟加载推荐模式**：

```python
# 模块级 import（放文件末尾避免循环）
from . import user_impl

# 或在 __init__.py 中统一导入
from .user import User
from . import user_impl
```

## 3. 待定问题

### Q1: _method_registry 是否完全替换
**决定**：完全替换。`_impl_chain` 替代 `_method_registry` 和 `_impl_sources`，类查找改用 `_class_registry.values()`。

确认

### Q2: _module_first_seq 的生命周期
**问题**：`_module_first_seq` 永久保留已卸载模块的序号，以支持 reload 后恢复原位置。如果模块被永久移除（而非 reload），这些条目会持续存在。是否需要清理机制？
**建议**：保留不清理。条目数量等于历史 impl 注册总数，通常很小。如有需要，可提供 `clear_module_history(module_name)` 函数用于显式清理。

确认

## 4. 实施步骤清单

### 阶段一：移除 AST 桩检测 [✅ 已完成]
- [x] **Task 1.1**: 删除 AST 相关代码
  - [x] 移除 `_is_stub_method` 函数
  - [x] 移除 `import ast, inspect, textwrap`
  - 状态：✅ 已完成

- [x] **Task 1.2**: 修改 DeclarationMeta.__new__
  - [x] 普通方法：移除 `_is_stub_method` 条件，所有公开 callable 直接收集 + 保存原始函数为默认实现到覆盖链
  - [x] classmethod/staticmethod：同上
  - [x] property：移除 `_is_stub_method(fget)` 条件，所有 `@property` 转为 `mutobj.Property` 并保存原始 getter/setter 为默认实现
  - 状态：✅ 已完成

### 阶段二：实现覆盖链 [✅ 已完成]
- [x] **Task 2.1**: 引入 `_impl_chain` 数据结构
  - [x] 定义 `_impl_chain`（含注册序号）、`_impl_seq`、`_module_first_seq`
  - [x] 移除 `_method_registry` 和 `_impl_sources`
  - [x] 添加 `_restore_stub` 和 `_apply_impl` 辅助函数
  - 状态：✅ 已完成

- [x] **Task 2.2**: 修改 @impl
  - [x] 注册时处理三种场景：就地替换（reload）/ 复用序号（卸载后 reimport）/ 全新注册
  - [x] 全新注册时检查 chain 是否非空（需 override=True）
  - [x] 用 `hasattr` + `__dict__` 替代 `_DECLARED_*` 校验
  - [x] 目标类查找改用 `_class_registry`
  - 状态：✅ 已完成

- [x] **Task 2.3**: 修改 unregister_module_impls
  - [x] 从 chain 中移除指定模块的条目
  - [x] 活跃实现被卸载时恢复为新链顶
  - [x] 中间层卸载不影响活跃实现
  - [x] 链为空时恢复 stub
  - 状态：✅ 已完成

- [x] **Task 2.4**: 修改 _migrate_registries（Declaration reload 支持）
  - [x] 迁移 `_impl_chain` 和 `_module_first_seq` 条目从 new_cls 到 existing
  - [x] 合并新默认实现：替换 existing 链中的 `"__default__"` 条目为新函数
  - [x] 保留 existing 链中的外部 @impl 条目不变
  - [x] 重新应用链顶实现
  - 状态：✅ 已完成

### 阶段三：更新测试 [✅ 已完成]
- [x] **Task 3.1**: 更新现有测试
  - [x] 验证 `...` / `pass` / 有代码的方法体都保存为默认实现（行为统一）
  - [x] 更新 `test_unregister.py`：适配 `_impl_chain` 替代 `_method_registry` / `_impl_sources`
  - [x] 更新 reload 相关测试
  - 状态：✅ 已完成

- [x] **Task 3.2**: 新增覆盖链测试
  - [x] A impl → B override → 卸载 B → A 恢复
  - [x] A impl → B override → C override → 卸载 B → C 仍活跃
  - [x] 全部外部 impl 卸载 → 默认实现恢复
  - [x] 卸载不存在的模块 → noop
  - [x] A → B → C → reload B → C 仍活跃（中间层 reload）
  - [x] A → B → reload B → B 更新为新函数（链顶 reload）
  - [x] A → B → C → 卸载 B + reimport → B 回到原位置，C 仍活跃
  - [x] Declaration reload（无外部 impl）→ 默认实现更新为新函数
  - [x] Declaration reload（有外部 impl）→ 默认实现更新，外部 impl 保留且仍为活跃
  - [x] Declaration reload（外部 impl 已卸载）→ 默认实现更新并恢复为活跃
  - 状态：✅ 已完成

### 阶段四：文档更新 [✅ 已完成]
- [x] **Task 4.1**: 更新 guide.md
  - [x] 声明文件写法说明
  - [x] IDE 跳转推荐约定
  - [x] 覆盖链和卸载机制说明
  - 状态：✅ 已完成

- [x] **Task 4.2**: 更新 API reference
  - [x] `@impl` 覆盖链语义
  - [x] `unregister_module_impls()` 文档
  - [x] Declaration 默认实现说明
  - [x] 移除过时的 `override=True` 描述
  - 状态：✅ 已完成

---

### 实施进度总结
- ✅ **阶段一：移除 AST 桩检测** - 100% 完成 (2/2任务)
- ✅ **阶段二：实现覆盖链** - 100% 完成 (4/4任务)
- ✅ **阶段三：更新测试** - 100% 完成 (2/2任务)
- ✅ **阶段四：文档更新** - 100% 完成 (2/2任务)

**全部任务完成度：100%** (10/10任务)
**单元测试覆盖：126个测试全部通过**

## 5. 测试验证

### 单元测试
- [x] Declaration 中任意方法体（`...` / `pass` / 有代码）保存为默认实现
- [x] 默认实现作为覆盖链底层（seq=0），不被 `unregister_module_impls` 移除
- [x] `@impl` 注册和调用正常
- [x] 覆盖链：多层 override 和选择性卸载
- [x] `unregister_module_impls` 恢复链上一层或默认实现
- [x] reload 与覆盖链兼容（中间层 reload 不影响活跃实现）
- [x] Declaration reload 正确更新默认实现（链中 `"__default__"` 条目被替换为新函数）
- [x] 卸载 + reimport 复用序号，恢复原位置
- [x] pyc 场景（无源码）正常工作（不再依赖 inspect.getsource）

### 回归测试
- [x] 属性描述符、Extension、继承 不受影响
- 执行结果：91/91 通过
