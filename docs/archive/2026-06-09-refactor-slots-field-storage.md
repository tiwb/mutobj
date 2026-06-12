# Declaration __slots__ + 内部 dict 字段存储 设计规范

**状态**：✅ 已完成
**日期**：2026-06-09
**类型**：重构

## 需求

1. **杜绝 Declaration 实例的任意 `setattr`**：当前实例 `__dict__` 完全敞开，`decl.unknown_field = 42` 可以随时往里塞东西。所有 Declaration 实例的公开成员都必须在类型上定义（字段、property、方法）。

2. **消除 `__dict__` 绕过路径**：`__setattr__` override 无法阻止 `obj.__dict__['x'] = 1`、`object.__setattr__(obj, 'x', 1)` 等底层绕过手段。只有 `__slots__` 能从根本上消除 `__dict__`。

3. **字段默认值 lazy 求值**：当前 `Declaration.__new__` 在构造时热切给所有有默认值的字段赋初值。改 lazy 后，`field(default_factory=list)` 之类只在首次访问时求值，省去无用字段的开销。

## 关键参考

- `src/mutobj/core/_fields.py:90-120` — `AttributeDescriptor.__init__`，`storage_name` 定义，`_storage_get/_storage_set`
- `src/mutobj/core/_fields.py:136-181` — `AttributeDescriptor._storage_get`（当前 `getattr(obj, self.storage_name)`）、`_storage_set`（当前 `setattr(obj, self.storage_name, value)`）、`__delete__`
- `src/mutobj/core/_declaration.py:53-58` — `_get_missing_construction_fields`，当前用 `desc.storage_name not in obj.__dict__` 判缺失
- `src/mutobj/core/_declaration.py:366-373` — `DeclarationMeta.__call__`，构造流程：`__new__ → __init__ → __post_init__ → 完整性检查`
- `src/mutobj/core/_declaration.py:376-400` — `Declaration.__new__`，热切默认值预填循环（本次删除）
- `src/mutobj/core/_declaration.py:402-436` — `Declaration.__init__`，位置参数映射与 `setattr`（本次不变）
- `mutobj/docs/specifications/refactor-declaration-field-completeness.md` — 刚完成的构造完整性重构，`_get_missing_construction_fields` 在此引入
- `tests/test_classvar.py:47-48` — 直接引用 `_mutobj_attr__app` 的测试，需更新

## 设计方案

### 总体方案：`__slots__` + 内部 dict

不为每个字段建独立 slot（避免 metaclass pre-pass 的复杂性），而是声明一个固定的 `__slots__`，字段值统一存在一个内部 dict 中。

```
# 当前
class Declaration:
    pass  # 有 __dict__，字段值存 obj.__dict__['_mutobj_attr_name']

# 目标
class Declaration:
    __slots__ = ('__weakref__', '_mutobj_storage')
    # _mutobj_storage: dict[str, Any] — 按字段名存所有字段值
    # 单下划线（非双下划线）：AttributeDescriptor 和 _get_missing_construction_fields
    # 等模块级函数需要跨类访问存储，name mangling 会导致它们无法通过原名访问
```

**metaclass 辅助**：`DeclarationMeta.__new__` 中强制所有子类拥有空 `__slots__ = ()`（如果子类没有显式定义），防止 Python 自动为无 `__slots__` 的子类加 `__dict__`。

字段值存取路径对比：

```
# 当前
setattr(obj, '_mutobj_attr_name', value)  →  obj.__dict__['_mutobj_attr_name'] = value
getattr(obj, '_mutobj_attr_name')         →  obj.__dict__['_mutobj_attr_name']

# 目标
storage = obj._mutobj_storage
storage['name'] = value
storage['name']
```

### 为什么不用 per-field slots

per-field slots 方案（每个字段一个 `_mutobj_attr_x` slot）理论上内存更优，但：
- 需要 metaclass pre-pass 在 `super().__new__` 前计算 slot 列表，且需适配 Python 3.12/3.13+ 的 annotations 获取差异（`__annotations__` vs `__annotate_func__`）
- `AttributeDescriptor` 的 `_storage_get/_storage_set` 目前走 `setattr(obj, storage_name, value)` 方式——`storage_name` 是字符串变量，无法利用编译器常量优化，实际性能不如 dict 的 `__setitem__`
- 子类需过滤父类 slot 防重复，多个 Declaration 多继承时会冲突

单内部 dict 方案避免了以上全部复杂度，且实测 `dict[key] = val` 快于 `setattr(obj, key_name_str, val)`。

### 性能对比

在 Python 3.14 下实测（每字段 500 万次读写）：

| 方式 | 单字段 | 5 字段 |
|------|--------|--------|
| slots (`setattr`/`getattr`) | 1.11s | 4.88s |
| **inner dict (`dict[key]`)** | **0.46s** | **1.89s** |
| slots (直接 `.attr`) | 0.40s | 1.55s |

直接属性访问 (`.attr`) 最快，但 descriptor 只能用 `setattr/getattr`（storage_name 是变量，编译器无法优化）。在这个约束下 inner dict 更快。

### `_mutobj_storage` 为何用单下划线

- `_mutobj_storage`（单下划线）：约定私有。`AttributeDescriptor` 和 `_get_missing_construction_fields` 等模块级函数需要跨类访问存储，双下划线 name mangling 会导致它们无法通过原名访达——`__mutobj_storage` 在 `Declaration` 类中 mangled 为 `_Declaration__mutobj_storage`，在其他函数上下文中则不是这个名。
- `__mutobj_storage__`（双下划线两头包）：❌ Python 语言保留格式，禁止使用

### 变更清单

#### `_fields.py` — `AttributeDescriptor`

`storage_name` 完全移除（从 `__slots__` 和构造函数参数中删除）。内部 dict 与属性空间隔离，无命名冲突风险，不再需要带前缀的存储名。

`_storage_get` 与 `_storage_set` 改为读写 `obj.__mutobj_storage`，同时加入 lazy default：

```python
def _storage_get(self, obj):
    storage = obj._mutobj_storage
    try:
        return storage[self.name]
    except KeyError:
        if self.default_factory is not None:
            value = self.default_factory()
            storage[self.name] = value  # 缓存在 storage
            return value
        if self.default is not MISSING:
            return self.default  # 不可变 default 不缓存（每次都返回 self.default）
        raise AttributeError(...)

def _storage_set(self, obj, value):
    obj._mutobj_storage[self.name] = value
```

`__delete__` 改为 `del obj._mutobj_storage[self.name]`。

`storage_name` 属性移除（非别名保留，无外部引用）。

#### `_declaration.py` — `Declaration` 基类

- 类体加 `__slots__ = ('__weakref__', '_mutobj_storage')`
- `DeclarationMeta.__new__`：对非 Declaration 基类的子类，若无 `__slots__` 则注入 `__slots__ = ()`，阻止 Python 自动加 `__dict__`
- `__new__`：删除原有的热切默认值预填循环（整个 MRO 遍历 + `setattr` 的代码块），只保留一行 `obj._mutobj_storage = {}`。字段默认值由 descriptor 在首次 `__get__` 时 lazy 求值
- `__init__` 不变：用户传入的 kwargs 仍走 `setattr(self, attr_name, value)` → descriptor `__set__` → 写入 `obj.__mutobj_storage`

> **关于 `__new__` 中的赋值**：当前 `__new__` 只有一处赋值——默认值预填循环内的 `setattr(obj, attr_name, desc.default)`。删除该循环后，`__new__` 不再有任何对字段的赋值操作。所有字段赋值都在 `__init__`（kwargs → `setattr`）和 `__post_init__`（用户代码）中发生，走统一的 descriptor 路径。

#### `_declaration.py` — `_get_missing_construction_fields`

```python
# 改前
if desc.has_storage and desc.storage_name not in obj.__dict__:

# 改后
# 额外排除 has_default 字段（lazy default 不写入 storage，只检查必填字段）
if desc.has_storage and not desc.has_default and desc.name not in storage:
```

#### `DeclarationMeta.__setattr__`（类级别）

不受影响——处理的是类属性赋值，走 `super().__setattr__`，写的是 `cls.__dict__`，与实例 `__slots__` 无关。

### lazy default 对 `__post_init__` 的影响

当前行为：

```
宣言构造 → __new__ 预填所有有默认值的字段 → __init__ 处理传入参数 → __post_init__ 运行
```

lazy 后 `__new__` 不再预填，`__post_init__` 里读一个未显式赋值且未在 `__init__` 传入的字段时，会触发 descriptor 的 `_storage_get` 首次求值，然后值被缓存。

这意味着 `__post_init__` 的行为变化仅在于：**有默认值的字段如果在 `__post_init__` 中首次被读，会在那一瞬间被求值并缓存**——和预期行为一致。唯一副作用是如果 `__post_init__` 中 `hasattr()` 检查依赖字段是否"有值"来判断是否被传入，需要改为检查内部 dict（`name in obj.__mutobj_storage`）。

### `hasattr` 行为

有 `default` 的字段：`hasattr(obj, 'name')` → descriptor `__get__` 返回默认值 → 不抛异常 → `True` ✅

无 `default` 且未赋值的字段：`hasattr(obj, 'name')` → descriptor `__get__` 抛 `AttributeError` → `False` ✅

与当前行为一致。

### 不变项

- `field()` API、`MISSING` 哨兵、`AttributeDescriptor` 公共接口（`storage_name` 已移除，无外部引用）
- `_attribute_registry`、`fields()` 反射
- `@impl`、Implementation 桥接
- `@property` 计算字段（`has_storage=False` 的不碰内部 dict）
- 构造完整性检查（`_get_missing_construction_fields` 仅改存储检查点）
- 类级别 `DeclarationMeta.__setattr__`

## 实施步骤清单

- [x] `_fields.py` — `AttributeDescriptor`：移除 `storage_name` slot 和构造参数，`_storage_get/_storage_set/__delete__` 改用 `obj._mutobj_storage` dict，lazy default 求值（`default_factory` 缓存、不可变 `default` 不缓存）
- [x] `_declaration.py` — `Declaration` 基类：加 `__slots__ = ('__weakref__', '_mutobj_storage')`，`__new__` 删除热切默认值预填循环，改为 `obj._mutobj_storage = {}`
- [x] `_declaration.py` — `DeclarationMeta.__new__`：对子类强制注入空 `__slots__ = ()`，阻止 Python 自动加 `__dict__`；修复 `__annotations__` 获取方式（改从 `cls.__annotations__` 取而非 `namespace`）
- [x] `_declaration.py` — `_get_missing_construction_fields`：改用 `obj._mutobj_storage` 判缺失，排除 `has_default` 字段
- [x] `DeclarationMeta.__new__` — 移除 `_` 前缀跳过逻辑，`_` 前缀带 annotations 的属性正常作为字段
- [x] 测试更新：`test_class_setattr.py`（lazy default 导致类级 default 修改可见）、`test_classvar.py`（改用 `_mutobj_storage` 检查）、`test_defaults.py`（`_` 前缀不再跳过、init 补充字段声明）
- [x] 全仓库 pytest 通过

## 设计变更记录

实施中以下点偏离原设计方案：

1. **`__mutobj_storage` → `_mutobj_storage`（单下划线）**：双下划线 name mangling 会导致 `AttributeDescriptor` 和 `_get_missing_construction_fields` 等跨类访问失效——`__mutobj_storage` 在不同类中 translates 到不同的 mangled name。单下划线保持原名，所有位置统一访问 `obj._mutobj_storage`。
2. **metaclass 强制 `__slots__ = ()`**：原方案仅在 `Declaration` 基类声明 `__slots__`，但 Python 对无 `__slots__` 的子类会自动加 `__dict__`。metaclass 注入空 slot 彻底杜绝。
3. **`_` 前缀字段不再跳过**：原 metaclass 跳过 `_` 开头的属性不生成 descriptor，但设计文档未提到此行为。该逻辑移除——带 annotations 的 `_` 前缀属性现在正常作为字段。

## 消费者场景

| 消费者 | 场景 | 依赖的输出 | 验收标准 |
|--------|------|-----------|---------|
| mutio / mutagent / mutbot / mutgui | 所有 Declaration 子类构造与字段访问 | 字段值正常存取；无法在实例上新增任意属性 | 全仓库 pytest 通过 |
| mutobj 自身测试 | 构造完整性检查 (`_get_missing_construction_fields`) | 内部 dict 路径替代 `__dict__` 路径 | `test_declaration_field_completeness.py` 通过 |
| 直接操作 `__dict__` 的代码（如有） | 旧代码可能直接读 `obj.__dict__` | 此类代码在 `__slots__` 下会崩 | grep 确认工作区内无实例级 `obj.__dict__` 直接读写 |
