# 工程改名 pyic → mutobj 设计规范

**状态**：✅ 已完成
**日期**：2026-02-16
**类型**：重构

## 1. 背景

项目经历了 pyic → forwardpy 的改名（因 PyPI 名称不可用），现需再次改名为 mutobj，以更好地体现"可变对象声明"的核心概念。同时将核心类型 `Object` 改名为 `Declaration`，更准确地反映声明-实现分离的设计模式。

### 当前状态

- 工作目录代码处于 `pyic` 状态（HEAD 在改名前）
- Git 历史中有两个后续提交需合并：
  - `f92c5ca`: pyic → forwardpy 改名
  - `3118407`: 新增 `unregister_module_impls` 功能
  - `8524c67`: 版本号升至 0.3.0
- 下游项目 `mutagent` 依赖 forwardpy，需要迁移指南
- mutagent 中的 reload（声明重定义）功能需迁移到 mutobj 中

## 2. 设计方案

### 2.1 包名与目录改名

| 原名 | 新名 |
|------|------|
| `src/pyic/` | `src/mutobj/` |
| `import pyic` | `import mutobj` |
| 包名 `pyic` (pyproject.toml) | `mutobj` |

### 2.2 公开类型改名

| 原名 | 新名 | 说明 |
|------|------|------|
| `pyic.Object` | `mutobj.Declaration` | 核心基类，声明接口 |
| `pyic.Extension` | `mutobj.Extension` | 保持不变 |
| `pyic.impl` | `mutobj.impl` | 保持不变 |
| `pyic.unregister_module_impls` | `mutobj.unregister_module_impls` | 保持不变（来自后续提交） |

### 2.3 内部类型改名

| 原名 | 新名 | 说明 |
|------|------|------|
| `ObjectMeta` | `DeclarationMeta` | 元类，跟随 Declaration 改名 |
| `PyicProperty` | `Property` | 去掉 Pyic 前缀 |
| `PyicAttributeDescriptor` | `AttributeDescriptor` | 去掉 Pyic 前缀 |
| `_PyicPropertyGetterPlaceholder` | `_PropertyGetterPlaceholder` | 去掉 Pyic 前缀 |
| `_PyicPropertySetterPlaceholder` | `_PropertySetterPlaceholder` | 去掉 Pyic 前缀 |
| `ExtensionMeta` | `ExtensionMeta` | 保持不变 |

### 2.4 内部属性标记改名

| 原名（变量名 / 字符串值） | 新名 |
|---------------------------|------|
| `_DECLARED_METHODS` = `"__pyic_declared_methods__"` | `"__mutobj_declared_methods__"` |
| `_DECLARED_PROPERTIES` = `"__pyic_declared_properties__"` | `"__mutobj_declared_properties__"` |
| `_DECLARED_CLASSMETHODS` = `"__pyic_declared_classmethods__"` | `"__mutobj_declared_classmethods__"` |
| `_DECLARED_STATICMETHODS` = `"__pyic_declared_staticmethods__"` | `"__mutobj_declared_staticmethods__"` |
| `__pyic_class__` | `__mutobj_class__` |
| `__pyic_is_classmethod__` | `__mutobj_is_classmethod__` |
| `__pyic_is_staticmethod__` | `__mutobj_is_staticmethod__` |
| `_pyic_attr_{name}` (存储前缀) | `_mutobj_attr_{name}` |

### 2.5 错误消息与注释更新

所有错误消息中的 `@pyic.impl(...)` 更新为 `@mutobj.impl(...)`。
所有注释和 docstring 中的 `pyic` 更新为 `mutobj`，`Object` 更新为 `Declaration`。

### 2.6 版本号

最后一次提交统一设置版本号为 `0.4.0`。中间提交不修改版本号。

### 2.7 pyproject.toml 更新

- `name`: `mutobj`
- `description`: 更新描述
- `authors`: `mutobj contributors`
- `project.urls`: 更新 GitHub URLs 为 `tiwb/mutobj`
- `package-data`: `mutobj = ["py.typed"]`

### 2.8 文档目录迁移

将 `doc/` 目录迁移到 `docs/` 下：
- `doc/specs/*` → `docs/specifications/`
- `doc/api/reference.md` → `docs/api/reference.md`
- `doc/guide.md` → `docs/guide.md`
- `doc/migration-guide.md` → `docs/migration-guide.md`（新建）

### 2.9 从 mutagent 迁移 reload 功能

mutagent 中实现的声明重定义（in-place class redefinition）功能将迁移到 mutobj 核心中。迁移后 mutagent 不再需要提供自己的 `Object` 基类和 `MutagentMeta`，直接使用 `mutobj.Declaration`。

#### 迁移内容

从 `mutagent/src/mutagent/base.py` 迁移以下功能到 `src/mutobj/core.py`：

1. **`_class_registry`** - 模块级字典，用 `(module, qualname)` 作为 key 追踪已定义的类
2. **`_update_class_inplace(existing, new_cls)`** - 将新类定义的属性就地更新到已有类对象上
   - 删除新定义中移除的属性
   - 设置/更新新定义中的属性
   - 修复 `__mutobj_class__` 引用（stub/impl 函数、classmethod/staticmethod 包装器、Property.owner_cls）
   - 更新 `__annotations__`
3. **`_migrate_registries(existing, new_cls)`** - 迁移内部注册表条目
   - 方法注册表：合并策略（保留旧 impl）
   - 属性注册表：替换策略（新定义为准）
   - Property 注册表：替换 + 修复 `owner_cls`
   - 重新应用所有已注册的 impl（覆盖 _update_class_inplace 移植过来的 stub）

4. **修改 `DeclarationMeta.__new__`** - 集成重定义逻辑
   - 创建类前检查 `_class_registry`
   - 若已存在，调用 `_update_class_inplace` + `_migrate_registries`，返回已有类
   - 首次定义时注册到 `_class_registry`

#### 公开 API 变化

迁移后 mutobj 新增导出：
- 无新增公开 API。reload 功能内置于 `DeclarationMeta`，用户透明使用。只要使用 `mutobj.Declaration` 作为基类，重定义同名类时自动触发 in-place 更新。

#### mutagent 迁移后的变化

- `mutagent.base.py`：删除 `_update_class_inplace`、`_migrate_forwardpy_registries`、`MutagentMeta`
- `mutagent.base.Object`：直接继承 `mutobj.Declaration`，不再需要 `MutagentMeta`
- `mutagent.__init__.py`：从 `mutobj` 导入 `impl`，不再导出 `MutagentMeta`
- `mutagent` 中所有 `from forwardpy import ...` 改为 `from mutobj import ...`

## 3. 已确认决策

| # | 问题 | 决策 |
|---|------|------|
| Q1 | `DeclarationMeta` 中跳过基类的检测逻辑 | 改为 `name == "Declaration"` |
| Q2 | 迁移指南放置位置 | `docs/migration-guide.md`，同时迁移 `doc/` → `docs/` |
| Q3 | 是否提供 `Object = Declaration` 兼容别名 | 不提供，干净切换 |
| Q4 | mutagent 功能迁移方案 | mutagent 的 reload 功能迁移到 mutobj，mutagent 不再提供 Object 基类 |
| Q5 | reload 功能是否需要可选开关 | 不需要，自动触发，性能影响可忽略 |
| Q6 | `_impl_sources` 在 reload 时的处理 | 在 `_migrate_registries` 中同时迁移条目 |
| Q7 | 版本号递进方案 | 最后一次提交统一设为 `0.4.0` |

## 4. 待定问题

无。

## 5. 实施步骤清单

### 提交 1：改名 pyic → mutobj [✅ 已完成]

- [x] **Task 1.1**: 重命名目录 `src/pyic/` → `src/mutobj/`
  - 状态：✅ 已完成
- [x] **Task 1.2**: 更新 `src/mutobj/core.py` 中所有类型名、属性标记、错误消息
  - [x] 类名：`Object` → `Declaration`, `ObjectMeta` → `DeclarationMeta`, `PyicProperty` → `Property` 等
  - [x] 属性标记字符串：`__pyic_*` → `__mutobj_*`
  - [x] 存储前缀：`_pyic_attr_` → `_mutobj_attr_`
  - [x] 错误消息：`@pyic.impl` → `@mutobj.impl`
  - [x] docstring 和注释
  - [x] `DeclarationMeta.__new__` 中的基类检测：`name == "Declaration"`
  - 状态：✅ 已完成
- [x] **Task 1.3**: 更新 `src/mutobj/__init__.py`
  - [x] 导入路径：`from mutobj.core import Declaration, Extension, impl`
  - [x] `__all__` 列表：`["Declaration", "Extension", "impl"]`
  - [x] docstring：更新为 mutobj
  - 状态：✅ 已完成
- [x] **Task 1.4**: 更新 `pyproject.toml`
  - [x] name, description, authors, urls, package-data
  - 状态：✅ 已完成
- [x] **Task 1.5**: 更新所有测试文件（7个）
  - [x] `import pyic` → `import mutobj`
  - [x] `pyic.Object` → `mutobj.Declaration`
  - [x] `from pyic.core import ...` → `from mutobj.core import ...`
  - [x] 内部类型名引用更新
  - 状态：✅ 已完成
- [x] **Task 1.6**: 迁移并更新文档
  - [x] `doc/` → `docs/`（目录结构迁移）
  - [x] `README.md` 更新
  - [x] `docs/api/reference.md` 更新
  - [x] `docs/guide.md` 更新
  - [x] `docs/specifications/design-pyic-project.md` → `design-mutobj-project.md`
  - 状态：✅ 已完成
- [x] **Task 1.7**: 更新 `LICENSE`（如有 pyic 引用）
  - 状态：✅ 已完成
- [x] **Task 1.8**: 运行全部测试，确保通过
  - 状态：✅ 已完成（50 tests passed）
- [x] **Task 1.9**: 提交 - "Rename project from pyic to mutobj"
  - 状态：✅ 已完成（be8a2fc）

### 提交 2：卸载支持 unregister_module_impls [✅ 已完成]

- [x] **Task 2.1**: 在 `src/mutobj/core.py` 中添加卸载功能
  - [x] 添加 `_impl_sources: dict[tuple[type, str], str]` 注册表
  - [x] 在 `impl()` 函数中记录来源模块到 `_impl_sources`
  - [x] 添加 `unregister_module_impls(module_name: str) -> int` 函数
  - 状态：✅ 已完成
- [x] **Task 2.2**: 更新 `src/mutobj/__init__.py` 导出 `unregister_module_impls`
  - [x] `__all__` 添加 `"unregister_module_impls"`
  - 状态：✅ 已完成
- [x] **Task 2.3**: 添加 `tests/test_unregister.py`
  - [x] 基于 git 历史中的测试文件，更新 `forwardpy` → `mutobj`、`Object` → `Declaration`
  - 状态：✅ 已完成（11 tests）
- [x] **Task 2.4**: 运行全部测试，确保通过
  - 状态：✅ 已完成（61 tests passed）
- [x] **Task 2.5**: 提交 - "Add unregister_module_impls for module impl unloading"
  - 状态：✅ 已完成（3de7de7）

### 提交 3：声明 reload 支持 [✅ 已完成]

- [x] **Task 3.1**: 在 `src/mutobj/core.py` 中添加 reload 功能
  - [x] 添加 `_class_registry: dict[tuple[str, str], type]` 模块级注册表
  - [x] 添加 `_update_class_inplace(existing, new_cls)` 函数
    - 删除移除的属性
    - 更新新属性
    - 修复 `__mutobj_class__` 引用
    - 修复 `Property.owner_cls` 引用
    - 更新 `__annotations__`
  - [x] 添加 `_migrate_registries(existing, new_cls)` 函数
    - 合并 `_method_registry`
    - 替换 `_attribute_registry`
    - 替换 `_property_registry` + 修复 `owner_cls`
    - 迁移 `_impl_sources` 条目
    - 重新应用所有 impl
  - [x] 修改 `DeclarationMeta.__new__` 集成重定义逻辑
  - 状态：✅ 已完成
- [x] **Task 3.2**: 添加 `tests/test_reload.py`
  - [x] 基于 mutagent 的 `test_inplace_update.py` 改写
  - [x] 更新为 mutobj API（`mutobj.Declaration`）
  - [x] 包含 `_exec_class` 辅助函数（linecache 注入）
  - [x] 测试用例：
    - 重定义保持类身份（id 不变）
    - 重定义更新 annotations
    - 重定义更新 stub 方法
    - 重定义删除移除的属性
    - isinstance 在重定义后仍然有效
    - impl 在重定义后存活
    - 已有实例看到新 stub
    - 不同 module 创建独立类
    - 不同 qualname 创建独立类
    - 首次定义注册到 _class_registry
    - 注册表迁移正确
  - 状态：✅ 已完成（11 tests）
- [x] **Task 3.3**: 更新版本号与提交
  - [x] `pyproject.toml` version → `0.4.0`
  - [x] `src/mutobj/__init__.py` version → `0.4.0`
  - 状态：✅ 已完成
- [x] **Task 3.4**: 运行全部测试，确保通过
  - 状态：✅ 已完成（72 tests passed）
- [x] **Task 3.5**: 提交 - "Add Declaration reload support (in-place class redefinition)"
  - 状态：✅ 已完成（4913aba）

### 提交 4：编写迁移指南与收尾 [✅ 已完成]

- [x] **Task 4.1**: 编写 `docs/migration-guide.md`
  - [x] 包名变更说明（pyic/forwardpy → mutobj）
  - [x] 类型改名对照表（完整列表）
  - [x] 内部属性标记变更（针对深度集成项目）
  - [x] 代码迁移示例（before/after）
  - [x] mutagent 迁移要点：
    - 删除 `MutagentMeta`、`_update_class_inplace`、`_migrate_forwardpy_registries`
    - `Object` 直接继承 `mutobj.Declaration`
    - reload 功能已内置，无需额外元类
    - 所有 `from forwardpy import ...` → `from mutobj import ...`
  - 状态：✅ 已完成
- [x] **Task 4.2**: 提交 - "Add migration guide for mutobj rename"
  - 状态：✅ 已完成（9fbd376）

---

### 实施进度总结
- ✅ **提交 1：改名 pyic → mutobj** - 100% 完成 (9/9 任务)
- ✅ **提交 2：卸载支持** - 100% 完成 (5/5 任务)
- ✅ **提交 3：声明 reload 支持** - 100% 完成 (5/5 任务)
- ✅ **提交 4：迁移指南** - 100% 完成 (2/2 任务)

**全部任务完成度：100%** (21/21 任务)
**单元测试覆盖：72 个测试全部通过**

## 6. 测试验证

### 单元测试
- [x] `tests/test_basic.py` - 基础功能（2 tests）
- [x] `tests/test_object.py` - Declaration（原 Object）测试
- [x] `tests/test_impl.py` - impl 装饰器测试
- [x] `tests/test_property.py` - Property 测试
- [x] `tests/test_classmethod_staticmethod.py` - classmethod/staticmethod 测试
- [x] `tests/test_extension.py` - Extension 测试
- [x] `tests/test_inheritance.py` - 继承测试
- [x] `tests/test_unregister.py` - 卸载功能测试（提交 2 新增，11 tests）
- [x] `tests/test_reload.py` - reload 功能测试（提交 3 新增，11 tests）
- 执行结果：72/72 通过

### 集成测试
- [x] `pip install -e .` 安装验证
- [x] `import mutobj` 导入验证
- [x] `mutobj.Declaration` 可用性验证
- 执行结果：全部通过
