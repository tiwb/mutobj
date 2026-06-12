# `mutobj.core` 模块拆分 设计规范

**状态**：✅ 已完成
**日期**：2026-05-27
**类型**：重构

## 需求

1. `mutobj/src/mutobj/core.py` 当前 1890 行，混合了全局注册表、字段系统、property 描述符、覆盖链管理、Declaration 元类、reload 迁移、Extension 系统、反射/发现 API 等多类职责，可读性和维护性下降
2. 期望按职责拆分为多个模块，同时保持公开 API 完全兼容（现有所有导入路径不变）
3. 用户偏好一次性迁移：`core` 变成目录包，旧 `core.py` 删除，实现文件在 `core/` 包内以 `_` 前缀命名（方案 B）

## 关键参考

- `src/mutobj/core.py` — 当前唯一的核心实现文件（1890 行），拆分源
- `src/mutobj/__init__.py` — 公开 API 从 `mutobj.core` 导入，拆分后导入路径需更新
- `pyproject.toml` — `[tool.setuptools.packages.find]` 配置需验证目录包兼容性
- `tests/` — 大量测试从 `mutobj.core` 导入内部符号（`_impl_chain`、`_class_registry`、`AttributeDescriptor` 等）

### 测试的导入路径迁移

测试中现有从 `mutobj.core` 导入的路径需随拆分一并更新：

| 当前导入 | 拆分后导入 |
|---------|-----------|
| `from mutobj.core import _attribute_registry` | `from mutobj.core._state import _attribute_registry` |
| `from mutobj.core import _class_registry` | `from mutobj.core._state import _class_registry` |
| `from mutobj.core import _impl_chain` | `from mutobj.core._state import _impl_chain` |
| `from mutobj.core import _ordered_fields_cache` | `from mutobj.core._fields import _ordered_fields_cache` |
| `from mutobj.core import _MISSING` | `from mutobj.core._fields import _MISSING` |
| `from mutobj.core import AttributeDescriptor` | `from mutobj import AttributeDescriptor`（公开 API） |
| `from mutobj.core import unregister_module_impls` | `from mutobj import unregister_module_impls`（公开 API） |

涉及文件：`test_classvar.py`、`test_discover.py`、`test_class_setattr.py`、`test_defaults.py`、`test_impl.py`、`test_impl_super.py`。

## 设计方案

### 总体方案：`core` 目录包 + `_` 前缀实现模块

```
mutobj/src/mutobj/
├── __init__.py
└── core/                       # 目录包，替代旧 core.py
    ├── __init__.py             # 空包标记，不导出任何符号
    ├── _state.py               # 全局注册表与 generation 状态
    ├── _constants.py           # 内部标记名、dunder 白名单、hook 白名单
    ├── _typing_utils.py        # ClassVar 注解解析工具
    ├── _fields.py              # Field / field / AttributeDescriptor / 字段反射
    ├── _properties.py          # Property / getter/setter placeholder
    ├── _impls.py               # @impl / impl_chain / super / unregister / meta
    ├── _reload.py              # reload in-place 更新与 registry 迁移
    ├── _declaration.py         # DeclarationMeta / Declaration / 类创建逻辑
    ├── _extensions.py          # Extension / extensions / extension_types
    └── _discovery.py           # discover_subclasses / resolve_class / declaration doc API
```

**删除**：`src/mutobj/core.py`。

### 职责划分

#### `_state.py` — 全局注册表与 generation（约 50 行）

所有 mutobj 全局可变状态集中在此，提供统一的读写 helper 函数。

```python
from __future__ import annotations

from typing import Any, Callable

# ---- 实现覆盖链 ----
_impl_chain: dict[tuple[type, str], list[tuple[Callable[..., Any], str, int]]] = {}
_impl_seq: int = 0
_module_first_seq: dict[tuple[type, str, str], int] = {}
_impl_metas: dict[tuple[type, str, int], tuple[object, ...]] = {}

# ---- 类/字段注册表 ----
_attribute_registry: dict[type, dict[str, Any]] = {}
_classvar_registry: dict[type, set[str]] = {}
_property_registry: dict[type, dict[str, Any]] = {}
_class_registry: dict[tuple[str, str], type] = {}

# ---- generation ----
_registry_generation: int = 0


def next_impl_seq() -> int:
    """递增 _impl_seq 并返回新值。"""
    global _impl_seq
    _impl_seq += 1
    return _impl_seq


def bump_registry_generation() -> None:
    """递增 _registry_generation。"""
    global _registry_generation
    _registry_generation += 1


def get_registry_generation() -> int:
    """返回当前 generation 号。"""
    return _registry_generation
```

设计理由：`_impl_seq` 和 `_registry_generation` 是 int 不可变类型，跨模块直接 `from _state import _registry_generation` 后赋值不会更新其他模块的引用。将所有递增操作集中在 helper 函数中消除此隐患。

#### `_constants.py` — 内部标记和白名单（约 20 行）

```python
# 声明方法标记
_DECLARED_METHODS: str = "__mutobj_declared_methods__"
_DECLARED_PROPERTIES: str = "__mutobj_declared_properties__"
_DECLARED_CLASSMETHODS: str = "__mutobj_declared_classmethods__"
_DECLARED_STATICMETHODS: str = "__mutobj_declared_staticmethods__"

# 可变类型黑名单
_MUTABLE_TYPES = (list, dict, set, bytearray)

# 不参与声明-实现机制的保留 dunder
_MUTOBJ_RESERVED_DUNDERS = frozenset({
    "__new__", "__init_subclass__", "__class_getitem__",
    "__set_name__", "__subclasshook__", "__instancecheck__", "__subclasscheck__",
})

# Declaration 基类上允许被标准注册流程处理的用户钩子白名单
_DECLARATION_USER_HOOKS = frozenset({
    "__post_init__",
})
```

#### `_typing_utils.py` — ClassVar 注解解析（约 40 行）

抽出 `_resolve_annotation_name()` 和 `_is_classvar()`。依赖 `importlib`、`sys`、`typing.get_origin`，不依赖 mutobj 内部对象。

#### `_fields.py` — 字段系统（约 300 行）

```python
from __future__ import annotations

from typing import Any, Callable

from ._constants import _MUTABLE_TYPES
from ._state import _attribute_registry

# _MissingSentinel
# MISSING / _MISSING
# Field
# field()
# AttributeDescriptor
# _ordered_fields_cache
# _invalidate_ordered_fields_cache_for()
# _get_ordered_fields()
# _get_attribute_descriptor()
# _get_init_fields()
# field_default()
# field_info()
# fields()
```

`DeclarationMeta.__new__` 中的字段解析逻辑保留在 `_declaration.py`（不迁入 `_fields.py`），仅迁出字段数据类型、描述符和反射 API。

#### `_properties.py` — mutobj Property 描述符（约 60 行）

```python
# Property
# _PropertyGetterPlaceholder
# _PropertySetterPlaceholder
```

#### `_impls.py` — 实现链和 @impl 装饰器（约 550 行）

```python
from __future__ import annotations

from typing import Any, Callable, TypeVar
import sys
import warnings

from ._state import _impl_chain, _impl_metas, _module_first_seq, _impl_seq
from ._state import _property_registry, _registry_generation
from ._state import next_impl_seq, bump_registry_generation, get_registry_generation
from ._constants import (
    _DECLARED_METHODS, _DECLARED_CLASSMETHODS, _DECLARED_STATICMETHODS,
    _DECLARATION_USER_HOOKS,
)
from ._properties import Property, _PropertyGetterPlaceholder, _PropertySetterPlaceholder

# _make_stub_method / _make_stub_classmethod / _make_stub_staticmethod
# _apply_impl / _restore_stub
# _register_to_chain / _store_metas
# _resolve_impl_key
# impl_has / impl_has_override / impl_is_own / impl_is_inherited / impl_chain
# _resolve_chain_top_meta_key / impl_meta / impl_meta_of
# impl_call_super / call_super_impl
# impl()
# unregister_module_impls / register_module_impls
```

**循环依赖处理**：`_resolve_impl_key()` 当前引用 `Declaration` 和 `_class_registry`。`_class_registry` 在 `_state` 中可直接导入；`Declaration` 在 `_declaration.py` 中会产生循环依赖。解决方式：在 `_resolve_impl_key()` 函数体内懒导入：

```python
def _resolve_impl_key(method: Any) -> tuple[type, str]:
    from ._declaration import Declaration  # 懒导入避免循环依赖
    ...
```

#### `_reload.py` — reload/in-place 更新逻辑（约 80 行）

```python
from ._state import _impl_chain, _class_registry, _attribute_registry, \
    _classvar_registry, _property_registry, _module_first_seq, bump_registry_generation
from ._fields import AttributeDescriptor, _invalidate_ordered_fields_cache_for
from ._properties import Property
from ._impls import _apply_impl

# _update_class_inplace()
# _migrate_registries()
```

#### `_declaration.py` — Declaration 元类和基类（约 650 行）

```python
from __future__ import annotations

from typing import Any, Callable, Self, TypeVar

from ._state import (
    _impl_chain, _class_registry, _attribute_registry, _classvar_registry,
    _property_registry, bump_registry_generation,
)
from ._constants import (
    _DECLARED_METHODS, _DECLARED_PROPERTIES, _DECLARED_CLASSMETHODS, _DECLARED_STATICMETHODS,
    _MUTABLE_TYPES, _MUTOBJ_RESERVED_DUNDERS, _DECLARATION_USER_HOOKS,
)
from ._fields import (
    Field, AttributeDescriptor, _MISSING, _get_attribute_descriptor,
    _get_init_fields, _invalidate_ordered_fields_cache_for,
)
from ._properties import Property
from ._typing_utils import _is_classvar
from ._impls import _apply_impl
from ._reload import _update_class_inplace, _migrate_registries

T = TypeVar("T", bound="Declaration")

# DeclarationMeta
# Declaration
```

#### `_extensions.py` — Extension 系统（约 130 行）

```python
import weakref
from typing import Any, Generic, Self

from ._fields import Field, _MISSING

# _extension_cache
# _extension_registry
# Extension
# extension_types()
# extensions()
```

#### `_discovery.py` — 发现和反射 API（约 100 行）

```python
import importlib
from typing import Any, Callable

from ._state import _class_registry, _impl_chain, get_registry_generation

# discover_subclasses()
# resolve_class()
# get_declaration_func()
# get_declaration_doc()
```

### 依赖方向

依赖关系严格单向，杜绝循环。`core/__init__.py` 不参与依赖链（空包标记）：

```text
_state ← _constants ← _typing_utils
   ↓
_properties
   ↓
_fields
   ↓
_impls  (懒导入 _declaration.Declaration 仅在 _resolve_impl_key 内)
   ↓
_reload
   ↓
_declaration
   ↓
_extensions  _discovery
```

### 公开 API 兼容策略

`core` 包是内部实现，**不在 `core/__init__.py` 中 re-export 任何符号**。`core/__init__.py` 仅作为空包标记存在。

所有公开 API 统一由 `mutobj/__init__.py` 从内部模块直接导入，是唯一的外部使用入口。外部代码不应出现 `from mutobj.core import ...` 的导入路径。

#### `core/__init__.py` — 空包标记

```python
# 内部实现包，不对外导出任何符号
```

#### `mutobj/__init__.py` — 唯一公开 API 入口

```python
from .core._declaration import Declaration
from .core._extensions import Extension, extensions, extension_types
from .core._impls import (
    impl, impl_call_super, call_super_impl,
    impl_has, impl_has_override, impl_is_own, impl_is_inherited,
    impl_chain, impl_meta, impl_meta_of,
    unregister_module_impls, register_module_impls,
)
from .core._fields import (
    field, MISSING, AttributeDescriptor,
    field_default, field_info, fields,
)
from .core._discovery import (
    discover_subclasses, get_registry_generation, resolve_class,
    get_declaration_func, get_declaration_doc,
)

__all__ = [
    "Declaration",
    "Extension",
    "impl",
    "impl_call_super",
    "call_super_impl",
    "impl_has",
    "impl_has_override",
    "impl_is_own",
    "impl_is_inherited",
    "impl_chain",
    "impl_meta",
    "impl_meta_of",
    "unregister_module_impls",
    "register_module_impls",
    "field",
    "MISSING",
    "AttributeDescriptor",
    "discover_subclasses",
    "get_registry_generation",
    "resolve_class",
    "extensions",
    "extension_types",
    "get_declaration_func",
    "get_declaration_doc",
    "field_default",
    "field_info",
    "fields",
]
```

> **补齐项**：相对当前 `mutobj/__init__.py`，新增 `AttributeDescriptor`。

#### 兼容性要点

1. **`core/__init__.py` 不导出公开 API** — 外部代码应通过 `from mutobj import ...` 使用，不应出现 `from mutobj.core import ...`
2. **已有外部引用需要修正** — `mutagent/src/mutagent/webui/_settings_page_impl.py` 中有 `from mutobj.core import AttributeDescriptor`，需改为 `from mutobj import AttributeDescriptor`
3. **测试可继续访问内部模块** — 测试中 `from mutobj.core import _impl_chain` 等改为从 `mutobj.core._state` 等实现模块直接导入
4. **`__module__` 不修正** — `Declaration.__module__` 变为 `"mutobj.core._declaration"` 不影响外部用法，无需修正
5. **`setuptools` 包发现** — `where = ["src"]` 配置不变，`mutobj.core` 目录包自动被 `find` 发现

## 实施步骤清单

- [x] 将 `src/mutobj/core.py` 拆分为 `src/mutobj/core/` 目录包，并按职责迁移状态、字段、实现链、reload、Declaration、Extension、发现 API
- [x] 更新 `src/mutobj/__init__.py`，让公开 API 直接从内部子模块导入，并补齐 `AttributeDescriptor`
- [x] 迁移 `mutobj` 测试中的内部导入路径，使其改为从 `mutobj.core._state`、`mutobj.core._fields`、`mutobj.core._constants`、`mutobj.core._declaration` 读取
- [x] 修正工作区内受影响的 `mutagent` 导入路径，移除对 `mutobj.core` 公开 re-export 的依赖
- [x] 完成 `mutobj` 回归测试，并确认新增拆分模块没有引入额外的 pyright 问题
