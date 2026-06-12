# Extension / Implementation 严格声明 设计规范

**状态**：✅ 已完成
**日期**：2026-06-10
**类型**：重构

## 需求

1. **Extension 无严格约束**：Extension 当前使用普通 `__dict__`，允许任意 `setattr`。字段通过 annotations + `Field()` 声明，但框架不阻止写入未声明属性，与 Declaration 已建立"声明即承诺"的理念不一致。

2. **Implementation 无严格约束**：Implementation 同样使用普通 `__dict__`，实例可任意 `setattr`。内部状态无结构约束，且可能意外覆盖桥接方法名。

3. **机制分散不统一**：Declaration 有 `__slots__` + `AttributeDescriptor` + `_mutobj_storage` 的完整体系；Extension 在 `__init_subclass__` 中手工遍历 MRO 收集 annotations、在 `get_or_create()` 中手工求值 `Field()` 默认值、然后 `setattr` 写入 `__dict__`。两套代码做类似的事，但路径完全不共享。

4. **Implementation 需要支持 `__dict__`**：Implementation 的典型使用场景（如 `MCPConnectionImpl`）需要在 `__init__` 中动态创建大量内部状态。完全禁止 `setattr` 会导致每个字段都需预先声明，与"实现类侧重方法桥接、数据是次要"的定位矛盾。需允许子类显式 `__slots__ = ("__dict__",)` 附加 `__dict__`，与 descriptor 共存。

## 关键参考

- `src/mutobj/core/_declaration.py:20-23` — `_validate_declaration_field()`，字段完整性校验（必填 + init=False 合法性）
- `src/mutobj/core/_declaration.py:58-68` — `DeclarationMeta.__new__` 中 `__slots__ = ()` 注入逻辑
- `src/mutobj/core/_declaration.py:90-150` — `DeclarationMeta.__new__` 中 annotations 循环，ClassVar 过滤 + Field 处理 + AttributeDescriptor 创建
- `src/mutobj/core/_declaration.py:150-185` — 父类字段覆写循环
- `src/mutobj/core/_declaration.py:470-476` — `Declaration.__new__`，`_mutobj_storage = {}` 初始化
- `src/mutobj/core/_fields.py:58-107` — `AttributeDescriptor`，含 `_storage_get/_storage_set` 存储协议、lazy 默认值求值
- `src/mutobj/core/_fields.py:25-50` — `Field` 类，`default/default_factory/init`
- `src/mutobj/core/_extensions.py:16-68` — `Extension` 类，`__init_subclass__` 注册 + `get_or_create()` 的字段默认值手工求值
- `src/mutobj/core/_implementation.py:274-282` — `Implementation` 类，`__init_subclass__` 注册，无字段概念
- `src/mutobj/core/_constants.py:3-4` — `_MUTABLE_TYPES = (list, dict, set, bytearray)`
- `src/mutobj/core/_typing_utils.py` — `_is_classvar()`，ClassVar 检测
- `tests/test_extension.py:456-510` — `TestExtensionSetattr`，当前 Extension 允许任意 setattr 的测试
- `mutagent/src/mutagent/sandbox/_mcp_impl.py:474-515` — `MCPConnectionImpl.__init__`，Implementation 动态创建大量内部属性的典型场景

## 设计方案

### 总体思路

**不给 Declaration / Extension / Implementation 增加公共基类。** 三个类的语义差异太大（见下文对比），共享的只是字段处理层面的工具函数。这些函数放入 `_fields.py`（不是新文件），因为共享代码全属字段描述符层面。

| 差异维度 | Declaration | Extension | Implementation |
|---|---|---|---|
| 实例与 Declaration 的关系 | 自身就是 | 1:N（多个 Extension 可挂一个） | 1:1 桥接 |
| 方法链（impl chain） | ✅ | ❌ | ❌（桥接方法另一端参与） |
| 字段系统 | annotations → `AttributeDescriptor` → `_mutobj_storage` | 同 Declaration | 同 Declaration |
| 创建方式 | `ClassName(field=value)` | `Ext.get_or_create(decl)` | 自动（`Declaration.__call__`） |
| 元类 | `DeclarationMeta`（300+ 行） | `ExtensionMeta`（轻量） | `ImplementationMeta`（轻量） |

### Extension 严格化

**目标**：Extension 与 Declaration 使用一致的字段声明 → 存储体系。

**方案**：

1. **Extension 基类加 `__slots__`**，去掉 `__dict__`：
   ```python
   class Extension(Generic[T]):
       __slots__ = ("target", "_mutobj_storage")
       # _target_class 是类属性（在 __init_subclass__ 中 cls._target_class = ... 赋值），
       # 不能列入 __slots__——否则与同名类级默认值冲突，import 期 ValueError。
       # __weakref__ 也不需要：_extension_cache 是 WeakKeyDictionary，弱引用的是 Declaration（key），
       # ext 实例本身只被 cache 的 value dict 强引用，不需要支持弱引用。
       _target_class: type | None = None
       target: Declaration | None = None
   ```

2. **新增轻量元类 `ExtensionMeta`**（~50 行），职责：
   - 注入 `__slots__ = ()` 到子类（复用 DeclarationMeta 的同一行逻辑）
   - 扫描 `__annotations__`，过滤 `ClassVar`
   - 为每个字段创建 `AttributeDescriptor`，调用共享的字段处理函数
   - `setattr(cls, attr_name, descriptor)`

3. **`get_or_create()` 重写**：不再手工遍历 MRO 求值 `Field()`、不再 `setattr` 写入 `__dict__`。改为：
   - `obj = cls.__new__(cls)` → 分配 `_mutobj_storage = {}`
   - `obj.target = instance`
   - `obj.__init__()` — 用户的 `__init__` 可通过 `self.field_name = value` 覆盖默认值
   - 字段值由 `AttributeDescriptor._storage_get()` 在首次访问时 lazy 求值（与 Declaration 一致，避免不必要的工厂调用）

4. **`get_or_create()` 不接受传参**：保持单例语义——同一 instance 多次调用必须返回同一对象。用户如有初始化逻辑，写在 `__init__` 中即可，`__init__` 只在首次创建时执行。

5. **字段完整性检查**：`get_or_create()` 中 `ext.__init__()` 执行完毕后，调 `_get_missing_construction_fields(ext)`，检查所有必填字段是否已赋值。行为对标 Declaration 构造函数末尾的同类检查。

6. **共享的字段处理函数**放入 `_fields.py`（见下方「共享机制」节）。

### Implementation 严格化 + 字段系统 + `__dict__` 支持

**目标**：Implementation 支持 annotations 字段声明（与 Declaration/Extension 同体系），默认严格。允许子类显式 `__slots__ = ("__dict__",)` 附加 `__dict__`，实现 descriptor 与 `__dict__` 共存（声明字段走 descriptor，未声明走 `__dict__`）。

**方案**：

1. **Implementation 基类加 `__slots__`**，含 `_mutobj_storage`，不含 `__dict__`：
   ```python
   class Implementation(Generic[T], metaclass=ImplementationMeta):
       __slots__ = ("_mutobj_storage",)
       # _target_class 同 Extension，是类属性（_register_implementation_class 中
       # impl_cls._target_class = target_cls 赋值），不能入 slots。
       # __weakref__ 也不需要：_implementation_owner_registry 用 id(impl) 做 key、
       # weakref.finalize 绑在 decl 上，impl 实例不需要支持弱引用。
       _target_class: type[T] | None = None
   ```

2. **正常写法（推荐）**：annotations 声明字段 → `AttributeDescriptor` → `_mutobj_storage`，与 Declaration 体验一致：
   ```python
   class MyImpl(mutobj.Implementation[MyDecl]):
       _name: str                     # 必填字段
       _count: int = 0                # 带默认值
       _cache: dict = field(default_factory=dict)

       def __init__(self, name: str):
           self._name = name          # → AttributeDescriptor → _mutobj_storage
           self._bad = 1              # ❌ 未声明字段，AttributeError
   ```

3. **附加 `__dict__`（与 descriptor 共存）**：子类可显式 `__slots__ = ("__dict__",)` 附加 `__dict__`：
   ```python
   class LegacyImpl(mutobj.Implementation[MyDecl]):
       __slots__ = ("__dict__",)      # 附加 __dict__
       _name: str                      # annotation → descriptor → _mutobj_storage

       def __init__(self, ns_name):
           self._name = ns_name        # ✅ 走 descriptor
           self._extra = 42            # ✅ 未声明，走 __dict__
   ```
   检测到 `__dict__` 在 `__slots__` 中时，`ImplementationMeta` 跳过 `__slots__ = ()` 注入（避免覆盖用户声明），annotations 照常处理为 `AttributeDescriptor`。两套存储各行其道：声明字段 → `_mutobj_storage`，未声明 → `__dict__`。

4. **字段完整性检查**：在 `DeclarationMeta.__call__` 中，`cls.__init__` 执行完毕后，对 impl 实例调 `_get_missing_construction_fields()`，检查所有必填字段是否已赋值。这是 Implementation 字段系统与 Declaration 的对标保障。

5. **加轻量 `ImplementationMeta`**（与 `ExtensionMeta` 对称，~30 行）：
   - **必要性**：Python 子类不显式写 `__slots__` 就自动获得 `__dict__`，与基类 slots 无关；而 `__init_subclass__` 在类创建后才被调用，**无法事后追加 `__slots__`**——必须在元类 `__new__` 的 `super().__new__` 之前写入 namespace。这正是 `DeclarationMeta` 必须存在的核心原因（`_declaration.py:67-68`）。不加元类 → Impl 子类全部静默拥有 `__dict__` → 严格化失效。
   - **职责**：仅两件事——`namespace["__slots__"] = ()` 注入 + 调共享的 `_process_field_annotations`、target_class 解析与注册（沿用现 `_resolve_target_class` / `_register_implementation_class` 逻辑，从 `__init_subclass__` 平移到元类 `__new__`）。
   - **不接管 `__call__`**：Impl 实例通过 `impl_cls.__new__()` 创建（`_prepare_implementation_instance` 内），不走 `ImplCls(...)` 的 `__call__` 路径，元类无须实现 `__call__`。
   - **不接管 `__setattr__`**：Impl 子类极少在类上直接设属性；保持元类轻量，类级保护交由共享函数在字段挂载时一次性校验。

   `__dict__` 在元类下的处理：`__new__` 里检测 `"__dict__" in namespace.get("__slots__", ())`（用户显式声明），仅跳过 `__slots__ = ()` 注入（若注入 `()` 会覆盖用户声明的 `__dict__`），annotations 照常处理为 descriptor。

6. **构造流程**（Impl 实例在 Declaration 构造链中的位置）：
   ```
   DeclarationMeta.__call__ (obj = MyDecl(...))
     ├─ 1. obj.__new__()                                    # Declaration.__new__
     │     └─ _prepare_implementation_instance(obj)         # impl = ImplCls.__new__() → _mutobj_storage = {}
     ├─ 2. cls.__init__(obj, *args, **kwargs)               # bridge → impl.__init__()  ← 用户在此设字段
     ├─ 3. obj.__post_init__()
     ├─ 4. Declaration 字段完整性检查 (obj)
     └─ 5. Implementation 字段完整性检查 (impl)            ← 本次新增
   ```

### 共享机制（放入 `_fields.py`）

从 `DeclarationMeta` 中抽取以下纯函数到 `_fields.py`，供 DeclarationMeta、ExtensionMeta 和 ImplementationMeta 共同调用：

```python
# _fields.py 新增

def _validate_field_descriptor(owner_name: str, descriptor: AttributeDescriptor) -> None:
    """校验字段描述符合法性：init=False 必须有 default、可变默认值检测等。"""
    # 从 DeclarationMeta._validate_declaration_field 抽取

def _process_field_annotations(
    annotations: dict[str, Any],
    namespace: dict[str, Any],
    module: str,
    owner_cls: type,
) -> list[AttributeDescriptor]:
    """扫描 annotations，过滤 ClassVar，为每个字段创建 AttributeDescriptor。

    返回新建的 descriptor 列表，调用方负责 setattr 到类上。
    """
    # 从 DeclarationMeta.__new__ 的注解循环抽取
```

**函数签名设计要点**：
- 返回值是 descriptor 列表而非直接 setattr，让三个调用方各自决定挂载方式：
  - `DeclarationMeta` 走 `__setattr__` 钩子（含 mutable default 二次检查）
  - `ExtensionMeta` 直接 `type.__setattr__`
  - `ImplementationMeta` 直接 `type.__setattr__`
- `_validate_field_descriptor` 作为独立函数导出，DeclarationMeta 的 `__setattr__` 中也可复用
- `_format_field_names()` 一并移入到 `_fields.py`（目前是 Declaration 内部函数，Extension / Implementation 构造校验时都需要）
- `_get_missing_construction_fields()` 一并移入到 `_fields.py`，签名为 `(obj: Any) -> list[str]`（访问 `obj._mutobj_storage`），供 Declaration / Extension / Implementation 三处字段完整性检查共用

### 对现有代码的影响

**Extension（16 个子类，零破坏）**：现有子类全部在 annotations 中声明字段，且都通过 `self._field = value` 访问。切换到 `AttributeDescriptor` 存储后，`self._field = value` 和 `self._field` 的行为完全透明兼容。

**Implementation（1 个生产用法）**：`MCPConnectionImpl` 的 `__init__` 中 11 个字段全部改为 annotations 声明，`__init__` 精简为 4 行（仅依赖构造参数的赋值），零破坏。

**测试（1 处需调整）**：`test_extension.py:TestExtensionSetattr` 的测试用例 `ext.callback = lambda: ...`（向未声明字段 setattr）将被拒绝，需改为 annotations 声明或移除。

**Implementation 现有测试**：阶段 A.3 需逐一复核。已知至少 `tests/test_implementation.py:11-23` 的 `LoaderImpl` 在 `__init__` 中 `self._loaded = ...` 是未声明字段，严格化后会 `AttributeError`，应改造为 `_loaded: str` 字段声明（推荐）或加 `__slots__ = ("__dict__",)` 附加 `__dict__`。其他用例（如 line 104、143 的 `self.price` / `self.value`）访问的是 Declaration owner 属性而非 Impl 自身属性，不受影响——但仍需 A.3 全文件 grep 复核。

## 实施步骤清单

### 1 共享机制抽取（重构基础，行为不变）

- [x] 在 `_fields.py` 中新增共享函数：`_validate_field_descriptor` / `_process_field_annotations` / `_format_field_names` / `_get_missing_construction_fields`（签名见「共享机制」节）
- [x] `_declaration.py` 改为调用共享函数，删除原内联实现
- [x] 跑 `pytest tests/` + `pyright` + `mutobj-lint`，确认 100% 行为不变（本步骤的硬验收锚点）

### 2 Extension 严格化

- [x] 新增 `ExtensionMeta`（轻量元类）：`namespace["__slots__"] = ()` 注入 + 调共享字段处理函数 + 沿用现 `__init_subclass__` 的 target_class 解析逻辑
- [x] `Extension` 基类调整：`__slots__ = ("target", "_mutobj_storage")`，`_target_class` 保持类属性，`metaclass=ExtensionMeta`
- [x] 重写 `get_or_create()`：走 `cls.__new__(cls)` + `_mutobj_storage = {}` + 设 `target` + `__init__()`，删除手工 MRO + Field 默认值求值循环
- [x] `get_or_create()` 末尾追加 `_get_missing_construction_fields` 校验必填字段
- [x] 改造 `tests/test_extension.py::TestExtensionSetattr`：未声明字段 setattr 改为 `pytest.raises(AttributeError)`
- [x] 新增 Extension 字段系统测试：lazy 默认值（首次访问求值）、必填字段校验、子类继承父类字段、ClassVar 过滤
- [x] `pytest tests/test_extension.py` + `pyright` + `mutobj-lint` 通过

### 3 Implementation 严格化

- [x] 新增 `ImplementationMeta`（与 `ExtensionMeta` 对称的轻量元类）：注入 `__slots__ = ()` + 调共享字段处理 + `_resolve_target_class` 与 `_register_implementation_class` 从 `__init_subclass__` 平移到元类 `__new__`
- [x] 元类支持 `__dict__`：检测 `"__dict__" in namespace.get("__slots__", ())` → 跳过 `__slots__ = ()` 注入（避免覆盖用户声明），annotations 照常处理为 descriptor
- [x] `Implementation` 基类调整：`__slots__ = ("_mutobj_storage",)`，`_target_class` 保持类属性，`metaclass=ImplementationMeta`
- [x] `_prepare_implementation_instance` 中确保 impl 的 `_mutobj_storage = {}` 初始化（`Implementation.__new__` 或元类 `__call__` 路径择一）
- [x] `DeclarationMeta.__call__` 在 `obj.__post_init__()` 与 Declaration 字段检查之后追加 Impl 字段完整性检查
- [x] 改造 `tests/test_implementation.py::LoaderImpl`：`_loaded` 改为字段声明（推荐路径）；同时全文件 grep 复核其他 Impl 子类的 `self.*` 写入（已知 line 104 / 143 是 owner 属性访问，预期不受影响，仍需复核）
- [x] 新增 Implementation 字段系统测试：lazy 默认值、必填字段校验、`__slots__ = ("__dict__",)` 与 descriptor 共存、严格模式下未声明 setattr 报错
- [x] `pytest tests/test_implementation.py` + `pyright` + `mutobj-lint` 通过

### 4 验收

- [x] mutobj 全 `pytest tests/` 通过
- [x] mutobj `pyright` strict 通过
- [x] mutobj `mutobj-lint` 通过

## 待定问题

（暂无）
