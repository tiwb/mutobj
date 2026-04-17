# 子类自定义 __init__ 未调 super 导致属性默认值丢失

**状态**：✅ 已完成
**日期**：2026-04-17
**类型**：Bug修复

## 需求

Declaration 子类定义了自定义 `__init__` 但未调用 `super().__init__()` 时，父类声明的属性默认值未初始化，访问时抛出 `AttributeError`。

```python
class View(Declaration):
    id: str | int = ""

class ChildView(View):
    id = "child"

    def __init__(self):          # 没有 super().__init__()
        self.value = 0

ChildView().id                   # ❌ AttributeError: 'ChildView' has no attribute 'id'
```

加上 `super().__init__()` 就正常，但用户不会想到要加——普通 Python 类不需要。

**注意**：裸值覆盖父类属性默认值的问题（`id = "child"`）已在 2026-03-12 修复（`docs/archive/2026-03-12-bugfix-subclass-attribute-override.md`）。本问题是独立的：属性默认值的初始化时机依赖 `Declaration.__init__` 被调用。

### 影响范围

所有有自定义 `__init__` 的 Declaration 子类。mutgui 的 View 子类是典型场景——几乎每个 View 都有 `__init__` 来初始化业务状态。

## 关键参考

- `mutobj/src/mutobj/core.py` — `Declaration.__init__`（属性默认值在此设置到 `_mutobj_attr_*`）
- `mutobj/src/mutobj/core.py:240-280` — `AttributeDescriptor.__get__`（访问 `_mutobj_attr_*` 存储）
- `mutobj/docs/specifications/feature-positional-init.md:100-104` — 已记录："自定义 `__init__` 绕过了这一机制，未赋值的字段无值"
- `mutgui/src/mutgui/view.py` — 触发场景（View.id 改为无注解 class variable 作为临时方案）

### 修复方向

将属性默认值的初始化从 `Declaration.__init__` 提升到 `__init_subclass__` 或 `__new__` 层面，使默认值始终可用，不依赖 `__init__` 的调用链。`feature-positional-init.md:104` 已预见到这个方向。

## 设计方案

将默认值初始化从 `Declaration.__init__` 拆分到 `Declaration.__new__`：

- **`__new__`**：遍历 MRO 收集所有 `AttributeDescriptor`，为有默认值的字段设置 `_mutobj_attr_*`（`__new__` 在 `__init__` 之前执行，不受子类是否调用 `super().__init__()` 影响）
- **`__init__`**：保留位置参数映射 + kwargs 赋值逻辑，`setattr` 覆盖 `__new__` 已设的默认值

对有参数的字段，`__new__` 设默认值后 `__init__` 再覆盖，有一次冗余赋值，但语义正确且开销可忽略。

## 实施步骤清单

- [x] 在 `test_defaults.py` 中添加测试用例复现 bug（自定义 `__init__` 不调 `super()` 时默认值丢失）
- [x] 在 `Declaration` 类添加 `__new__` 方法，将默认值初始化逻辑从 `__init__` 移入
- [x] 精简 `Declaration.__init__`，移除默认值初始化，只保留参数赋值
- [x] 运行全量测试，确保无回归
