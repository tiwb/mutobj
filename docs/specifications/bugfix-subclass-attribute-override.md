# Declaration 子类属性覆盖失效 设计规范

**状态**：✅ 已完成
**日期**：2026-03-12
**类型**：Bug修复

## 背景

当 Declaration 子类用无注解的 `attr = value` 覆盖父类声明属性时，实例属性获取到的是父类默认值而非子类覆盖值。这是一个严重的语义正确性问题，在 mutbot 移除 FastAPI 重构中首次暴露——所有 View 路由注册全部静默失败。

### 复现

```python
import mutobj

class View(mutobj.Declaration):
    path: str = ""

class HealthView(View):
    path = "/api/health"     # 直觉：覆盖父类默认值

print(HealthView.path)       # "/api/health" ✅ 类属性正确
print(HealthView().path)     # "" ❌ 实例属性被父类默认值覆盖
```

### 影响范围

所有 Declaration 子类通过无注解赋值覆盖父类声明属性的场景均受影响。目前 mutbot 的 View/WebSocketView 体系因此完全不工作（路由表为空）。

## 原因分析

### Python 数据描述符优先级

`View` 声明 `path: str = ""` 时，`DeclarationMeta` 在 `View.__dict__` 创建 `AttributeDescriptor`（实现了 `__get__` + `__set__`，是数据描述符）。

`HealthView` 用 `path = "/api/health"` 覆盖时，在 `HealthView.__dict__` 放了一个普通字符串。

Python 实例属性查找规则：**数据描述符优先于一切**，不管在 MRO 哪一层。

```
实例属性查找优先级：
  1. MRO 中的数据描述符（有 __get__ + __set__）  ← View.path 的 AttributeDescriptor
  2. 实例 __dict__
  3. MRO 中的非数据描述符和普通类属性            ← HealthView.path 的字符串在这里

类属性查找优先级：
  1. MRO 中第一个匹配的类属性                    ← HealthView.__dict__["path"] 先匹配
```

所以 `HealthView.path` 正确（类级别查找，HealthView 的字符串先匹配），但 `HealthView().path` 错误（实例级别查找，View 的数据描述符优先）。

### `Declaration.__init__` 的默认值应用

```python
# core.py:674-694
def __init__(self, **kwargs):
    applied = set()
    for klass in type(self).__mro__:           # 遍历 MRO
        if klass in _attribute_registry:
            for attr_name in _attribute_registry[klass]:
                if attr_name in applied:
                    continue
                desc = klass.__dict__.get(attr_name)
                if isinstance(desc, AttributeDescriptor) and desc.has_default:
                    setattr(self, attr_name, desc.default)  # ← 用父类默认值 ""
                    applied.add(attr_name)
```

`HealthView` 没有注解所以不在 `_attribute_registry` 中。遍历到 `View` 时找到 `path` 的 `AttributeDescriptor`，用默认值 `""` 设置了 `self._mutobj_attr_path = ""`。之后所有实例访问都走数据描述符，返回 `""`。

## 设计方案

### 核心设计

在 `DeclarationMeta.__new__` 中增加一步：**子类用无注解赋值覆盖父类声明属性时，自动为子类创建新的 `AttributeDescriptor`**。

处理位置：在现有注解属性处理逻辑之后，扫描 `namespace` 中不在本类 `annotations` 里但在父类 `_attribute_registry` 中的属性。

```python
# 伪代码：处理完注解属性后
for attr_name, value in namespace.items():
    if attr_name in own_annotations:
        continue                          # 已经处理过了
    if attr_name.startswith("_"):
        continue                          # 私有属性不管
    # 检查父类是否有同名声明属性
    parent_desc = _find_parent_descriptor(cls, attr_name)
    if parent_desc is not None:
        # 子类意图覆盖 → 创建新 AttributeDescriptor
        new_desc = AttributeDescriptor(attr_name, parent_desc.annotation, default=value)
        setattr(cls, attr_name, new_desc)
        attr_registry[attr_name] = parent_desc.annotation
```

这样子类的 `AttributeDescriptor` 在 MRO 中先于父类的被找到，实例属性访问返回正确的覆盖值。

### 需要处理的边界情况

1. **可变类型覆盖**：子类 `items = [1, 2, 3]` 应触发与注解声明相同的可变类型错误（引导用 `field(default_factory=...)`）
2. **callable / property / descriptor 排除**：跟现有注解属性处理一致，跳过方法和描述符
3. **多层继承**：A → B → C，C 覆盖 A 的属性，需要正确找到 A 的描述符并用 C 的值创建新描述符
4. **Field 覆盖**：子类 `items = field(default_factory=list)` 无注解时也应识别

### 实施概要

修改 `DeclarationMeta.__new__` 中属性处理逻辑，在注解属性处理完成后增加无注解覆盖检测。添加对应测试用例覆盖各边界情况。变更局限于 `core.py` 单文件。

### 设计决策

- **静默处理**：无注解覆盖不发 warning（符合 Python 直觉，加 warning 是噪音）
- **`__init__` 无需改动**：MRO 从最派生类开始遍历 + `applied` 去重，子类有描述符后自然正确

## 实施步骤清单

### Phase 1: 核心修复 [✅ 已完成]

- [x] **Task 1.1**: 修改 `DeclarationMeta.__new__` — 在注解属性处理（L505）之前，增加无注解覆盖检测逻辑
  - 遍历 `namespace` 中非注解、非私有、非 callable/property/descriptor 的属性
  - 查找父类 MRO 中的 `AttributeDescriptor`
  - 识别 `Field` 对象，走 Field 处理分支
  - 检测可变类型，抛出与注解声明一致的 TypeError
  - 为不可变默认值创建新 `AttributeDescriptor` 并注册到 `attr_registry`
  - 状态：✅ 已完成

### Phase 2: 测试用例 [✅ 已完成]

- [x] **Task 2.1**: 核心场景测试（`test_defaults.py` 新增 `TestUnannotatedOverride` 类）
  - [x] 基本无注解覆盖 — 实例属性返回覆盖值
  - [x] 多层继承无注解覆盖 — A→B→C 跳级覆盖
  - [x] kwargs 仍能覆盖无注解默认值
  - [x] 父类不受子类无注解覆盖影响
  - [x] 多属性混合 — 同一子类带注解 + 无注解覆盖共存
  - 状态：✅ 已完成

- [x] **Task 2.2**: 边界情况测试
  - [x] 可变类型无注解覆盖报 TypeError
  - [x] `field()` 无注解覆盖正确识别
  - [x] callable/property 不误判为属性覆盖
  - [x] 私有属性 `_xxx` 不触发覆盖逻辑
  - 状态：✅ 已完成

- [x] **Task 2.3**: 注册表与交互验证测试
  - [x] 子类 `__dict__` 中有独立的 `AttributeDescriptor`
  - [x] `_attribute_registry` 中子类包含覆盖属性
  - [x] 无注解覆盖属性在 `@impl` 方法中可正确访问
  - 状态：✅ 已完成

### Phase 3: 验证 [✅ 已完成]

- [x] **Task 3.1**: mutobj 全量测试 — 177 passed，5 failed（预存的中文 regex 问题，非本次引入）
- [x] **Task 3.2**: mutagent 测试 — 687 passed，2 failed（网络相关，非本次引入）
  - 状态：✅ 已完成

## 关键参考

### 源码
- `mutobj/src/mutobj/core.py:437-664` — `DeclarationMeta.__new__`，属性处理逻辑在 470-504 行
- `mutobj/src/mutobj/core.py:240-280` — `AttributeDescriptor`，数据描述符实现
- `mutobj/src/mutobj/core.py:674-694` — `Declaration.__init__`，默认值应用逻辑

### 触发场景
- `mutbot/src/mutbot/web/view.py:236-261` — `View` / `WebSocketView` 基类声明 `path: str = ""`
- `mutbot/src/mutbot/web/routes.py:63-69` — `HealthView(View)` 用 `path = "/api/health"` 覆盖
- `mutbot/src/mutbot/web/view.py:319-341` — `Router.discover()` 实例化后检查 `view.path`，全部为空

### Python 描述符协议
- 数据描述符（有 `__get__` + `__set__`）在实例属性查找中优先于实例 `__dict__` 和非描述符类属性
- 类属性查找不受此影响（MRO 顺序第一个匹配即返回）
