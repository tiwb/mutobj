# mutobj 迁移指南

本指南帮助从 `pyic` 或 `forwardpy` 迁移到 `mutobj`。

## 包名变更

```bash
# 旧
pip install pyic
pip install forwardpy

# 新
pip install mutobj
```

## 导入变更

```python
# 旧
import pyic
# 或
import forwardpy

# 新
import mutobj
```

## 类型改名对照表

### 公开 API

| 旧名 | 新名 | 说明 |
|------|------|------|
| `pyic.Object` / `forwardpy.Object` | `mutobj.Declaration` | 核心基类 |
| `pyic.Extension[T]` / `forwardpy.Extension[T]` | `mutobj.Extension[T]` | 保持不变 |
| `@pyic.impl(...)` / `@forwardpy.impl(...)` | `@mutobj.impl(...)` | 保持不变 |
| `pyic.unregister_module_impls` / `forwardpy.unregister_module_impls` | `mutobj.unregister_module_impls` | 保持不变 |

### 内部类型（仅深度集成项目需要关注）

| 旧名 | 新名 |
|------|------|
| `ObjectMeta` | `DeclarationMeta` |
| `PyicProperty` / `ForwardpyProperty` | `Property` |
| `PyicAttributeDescriptor` | `AttributeDescriptor` |
| `_PyicPropertyGetterPlaceholder` | `_PropertyGetterPlaceholder` |
| `_PyicPropertySetterPlaceholder` | `_PropertySetterPlaceholder` |

### 内部属性标记

| 旧名 | 新名 |
|------|------|
| `__pyic_declared_methods__` / `__forwardpy_declared_methods__` | `__mutobj_declared_methods__` |
| `__pyic_declared_properties__` / `__forwardpy_declared_properties__` | `__mutobj_declared_properties__` |
| `__pyic_declared_classmethods__` / `__forwardpy_declared_classmethods__` | `__mutobj_declared_classmethods__` |
| `__pyic_declared_staticmethods__` / `__forwardpy_declared_staticmethods__` | `__mutobj_declared_staticmethods__` |
| `__pyic_class__` / `__forwardpy_class__` | `__mutobj_class__` |
| `__pyic_is_classmethod__` / `__forwardpy_is_classmethod__` | `__mutobj_is_classmethod__` |
| `__pyic_is_staticmethod__` / `__forwardpy_is_staticmethod__` | `__mutobj_is_staticmethod__` |
| `_pyic_attr_{name}` / `_forwardpy_attr_{name}` | `_mutobj_attr_{name}` |

## 代码迁移示例

### Before (pyic/forwardpy)

```python
import pyic

class User(pyic.Object):
    name: str
    age: int

    def greet(self) -> str:
        ...

class UserExt(pyic.Extension[User]):
    _count: int = 0

@pyic.impl(User.greet)
def greet(self: User) -> str:
    ext = UserExt.of(self)
    ext._count += 1
    return f"Hello, {self.name}!"
```

### After (mutobj)

```python
import mutobj

class User(mutobj.Declaration):
    name: str
    age: int

    def greet(self) -> str:
        ...

class UserExt(mutobj.Extension[User]):
    _count: int = 0

@mutobj.impl(User.greet)
def greet(self: User) -> str:
    ext = UserExt.of(self)
    ext._count += 1
    return f"Hello, {self.name}!"
```

### 迁移步骤

1. 将所有 `import pyic` / `import forwardpy` 替换为 `import mutobj`
2. 将所有 `pyic.Object` / `forwardpy.Object` 替换为 `mutobj.Declaration`
3. 将所有 `pyic.Extension` / `forwardpy.Extension` 替换为 `mutobj.Extension`
4. 将所有 `@pyic.impl` / `@forwardpy.impl` 替换为 `@mutobj.impl`
5. 将所有 `from pyic.core import ...` / `from forwardpy.core import ...` 替换为 `from mutobj.core import ...`
6. 更新内部类型名引用（如果有直接使用 `ObjectMeta`、`PyicProperty` 等）

## 新增功能

### Declaration reload（in-place 类重定义）

mutobj 0.4.0 内置了 in-place 类重定义支持。当同一模块中的同名类被重新定义时（例如模块 reload），已有的类对象会被就地更新，而不是创建新对象。

特性：
- 类身份（`id(cls)`）保持不变
- `isinstance()` 检查在重定义后仍然有效
- `@impl` 注册在重定义后存活
- 已有实例自动看到新的方法和属性

这意味着使用 `mutobj.Declaration` 作为基类的类自动获得此功能，无需额外的元类。

## mutagent 项目迁移要点

mutagent 之前依赖 `forwardpy` 并提供了自己的 `MutagentMeta` 元类来支持 in-place 类重定义。迁移到 `mutobj` 后：

### 需要删除的代码

- `mutagent.base._update_class_inplace` - 已内置到 mutobj
- `mutagent.base._migrate_forwardpy_registries` - 已内置到 mutobj
- `mutagent.base.MutagentMeta` - 不再需要自定义元类

### 需要修改的代码

```python
# 旧 (mutagent/base.py)
from forwardpy import Object as _ForwardpyObject
from forwardpy.core import ObjectMeta, ForwardpyProperty, ...

class MutagentMeta(ObjectMeta):
    _class_registry = {}
    def __new__(mcs, name, bases, namespace):
        ...

class Object(_ForwardpyObject, metaclass=MutagentMeta):
    pass

# 新 (mutagent/base.py)
from mutobj import Declaration

class Object(Declaration):
    """mutagent 基类，直接继承 mutobj.Declaration"""
    pass
```

```python
# 旧 (mutagent/__init__.py)
from forwardpy import impl

# 新 (mutagent/__init__.py)
from mutobj import impl
```

```python
# 旧 (mutagent/runtime/module_manager.py)
from forwardpy import unregister_module_impls

# 新 (mutagent/runtime/module_manager.py)
from mutobj import unregister_module_impls
```

### 属性标记变更

如果 mutagent 的代码中直接引用了内部属性标记：

| 旧名 | 新名 |
|------|------|
| `__forwardpy_class__` | `__mutobj_class__` |
| `ForwardpyProperty` | `Property` |
| `ObjectMeta` | `DeclarationMeta` |

### 迁移后的好处

- 不再需要维护 `MutagentMeta`、`_update_class_inplace`、`_migrate_forwardpy_registries`
- reload 功能由 mutobj 统一管理
- 减少 mutagent 的代码量和维护负担
