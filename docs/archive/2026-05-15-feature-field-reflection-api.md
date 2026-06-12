# Declaration 字段反射 API(field_default / field_info / fields)

**状态**：✅ 已完成
**日期**:2026-05-15
**类型**:功能设计

## 需求

1. pyright 无法看到 Declaration 类字段上的 `make_default()` / `get_default()` 等 descriptor 方法,导致消费方出现 ~6 个 `reportAttributeAccessIssue` 类型错误,只能用 `# pyright: ignore` 镇压
2. 这本质上是 mutobj 运行时 descriptor 替换行为超出 Python 类型系统表达能力的问题--希望探索在类型层面让类型检查器理解 descriptor 协议的可能性

## 关键参考

- `src/mutobj/core.py` - `AttributeDescriptor` (L344), `make_default()` (L376), `get_default()` (L369)
- `src/mutobj/core.py` - `DeclarationMeta.__new__` 字段处理逻辑
- mutgui `src/mutgui/action.py` - 消费方受影响位置:`action_cls.categories.make_default()` (L296, L299), `item.order.make_default()` (L428, L440)

### 问题现象

```python
# mutobj: 用户声明
class Action(Declaration):
    categories: tuple[str, ...] = ()
    order: int | None = None

# 运行时: DeclarationMeta.__new__ 把值替换成 AttributeDescriptor
# Action.categories → AttributeDescriptor(name="categories", default=())
# Action.order → AttributeDescriptor(name="order", default=None)

# 消费方: 需要通过 descriptor 读取默认值
for action_cls in ActionRegistry._action_classes():
    if category in action_cls.categories.make_default():  # pyright ✗
        ...

# pyright 视角:
#   action_cls.categories → tuple[str, ...]  (来自 __annotations__)
#   tuple[str, ...] 没有 make_default()        → reportAttributeAccessIssue
```

### 根本矛盾

- `__annotations__` 记录用户声明的字段类型(`tuple[str, ...]`),用于实例属性的类型检查
- `DeclarationMeta.__new__` 把类属性值替换成 `AttributeDescriptor` 实例,用于类级反射(`make_default()` 等)
- pyright 从 `__annotations__` 推断 `action_cls.categories` 的类型,不知道运行时实际是 descriptor
- `__get__` 的返回类型只有一个,无法同时表达"类级访问返回 descriptor、实例级访问返回声明类型"

## 设计方案

### 总体思路:把 descriptor 暴露降级为内部实现细节,提供显式反射 API

`Action.categories.make_default()` 是 leaky abstraction -- 利用了 "类级访问返回 descriptor" 的运行时副产物来做反射。Python 类型系统不存在表达这种二义性的手段,硬要让 pyright 理解就得让用户改写声明方式(如去掉 annotation 直接 `categories = mutobj.field(...)`),DX 大退步。

正确方向是让 descriptor 类级暴露成为**内部实现细节**,提供与 `dataclasses.fields()` / `mutobj.impl_has(Cls.method)` 同构的显式反射 API。运行时旧行为保留以维持向后兼容。

### API 设计:复用 mutobj 现有反射范式

mutobj 已有 `impl_has(Cls.method)` / `impl_chain(Cls.method)` 这类"类点成员当 token 传"的反射范式,新 API 沿用同一形态。函数命名采用 `field_*` 前缀,与 `field()` 工厂区开、语义自诈:

```python
# 主路径:拿默认值(消费场景 90%)
mutobj.field_default(Action.categories)        # → ()  类型 tuple[str, ...]

# 拿元信息(少数高级场景)
mutobj.field_info(Action.categories)            # → AttributeDescriptor

# 遍历所有字段(dataclasses.fields 等价物,用于动态字段名场景)
mutobj.fields(Action)                            # → Mapping[str, AttributeDescriptor]
```

不提供 `mutobj.field_default(Action, "categories")` 这种字符串双签名形式:`Cls.field` 路径覆盖静态已知字段名场景,动态字段名场景走 `fields(cls)[name]`,路径分明。

**类型 stub 关键技巧** -- 用泛型让类型透传:

```python
from typing import TypeVar, overload
_T = TypeVar("_T")

def field_default(field: _T, /) -> _T: ...
def field_info(field: object, /) -> AttributeDescriptor: ...
def fields(cls: type, /) -> Mapping[str, AttributeDescriptor]: ...
```

pyright 视角:
- `action_cls.categories: tuple[str, ...]`(来自 annotation)
- `mutobj.field_default(action_cls.categories)` 推断为 `tuple[str, ...]`
- `category in tuple[str, ...]` ✓ -- 全链路无 `# type: ignore`

运行时:`isinstance(arg, AttributeDescriptor)` 校验后调 `.make_default()`,传入非 descriptor 值(如直接传实例属性 `instance.categories`)抛 `TypeError`。

### 与 dataclasses.fields 风格对比

| 写法 | 优点 | 缺点 |
|------|------|------|
| `mutobj.fields(cls)["categories"].make_default()` | 与 dataclasses 完全同构 | 字符串字段名(拼写错误不被 pyright 抓);返回 `Any`,丢失字段值类型 |
| `mutobj.field_default(Cls.categories)` ✅ | 类型透传到字段值类型;无字符串;与 `impl_has(Cls.m)` 同范式 | 与 dataclasses 习惯不同(但 mutobj 本来就有 `impl_has` 先例) |

两种写法**都提供**--`fields(cls)` 用于遍历未知字段集合,`field_default(Cls.x)` 用于读已知字段(绝大多数消费场景)。

### 与 `dataclass_transform` 的关系

本方案与 [`feature-declaration-dataclass-transform.md`](./feature-declaration-dataclass-transform.md) **完全独立**:

- `dataclass_transform` 影响范围(PEP 681):构造器签名、`field()` 工厂识别、`__eq__` 等。**不影响类级属性访问的类型推断**。
- 加了 `dataclass_transform` 之后,pyright 对 `Action.categories` 类级访问类型仍是 `tuple[str, ...]`,看不到 `make_default()` 的问题原封不动。
- mutgui 当前 6 个 `reportAttributeAccessIssue` 错误**只能由 `field_default` 修**,`dataclass_transform` 修不了其中任何一个。
- `field_default` 与 `impl_has` 同性质--都是用"运行时 token + 类型透传"的反射函数,把类型系统无法表达的二义性隐藏在 stub 里,与 `dataclass_transform` 解决的问题域无交集。

两个 spec 可独立实施、独立验收、独立发版。

### 兼容性策略

- 运行时 `Cls.field_name` 仍返回 `AttributeDescriptor`(不动 `AttributeDescriptor.__get__(None, ...)` 行为)
- 旧消费方代码 `Cls.field.make_default()` 继续工作,只是 pyright 报错--不强制迁移
- 文档中标记 "`Cls.field_name` 类级访问返回 descriptor" 为内部实现细节,公开 API 是 `mutobj.field_default()` / `mutobj.fields()`
- mutgui 4 处调用作为首批迁移示例(顺手删 `# pyright: ignore`)

### 实施范围

- mutobj:新增 `field_default()` / `field_info()` / `fields()` 三个公开函数
- mutobj:`__init__.py` 导出新 API
- mutobj:补单测覆盖新 API
- mutobj:更新 README 说明
- mutgui:迁移 4 处调用(`action.py:296,299,428,440`)
- mutbot/mutagent:审视是否有同类消费点(grep `\.make_default\(\)` / `\.get_default\(\)`)

## 消费者场景

| 消费者 | 场景 | 依赖的输出 | 验收标准 |
|--------|------|-----------|---------|
| mutgui `action.py` | 类级读取 `categories` / `order` 默认值用于路由 | `field_default(Cls.f)` 返回字段值类型 | 4 处调用迁移后 `pyright src/mutgui` 关于 `make_default` 的 6 个错误全部消失 |
| mutbot/mutagent | 待 grep 确认是否有同类调用 | 同上 | 若有,同步迁移;若无,备查 |

## 实施步骤清单

- [x] mutobj:实现并在 `__init__.py` 导出 `field_default()` / `field_info()` / `fields()` 三个反射函数(含泛型透传类型注解、`isinstance(AttributeDescriptor)` 运行时校验)
- [x] mutobj:补单测覆盖三个 API 的正确用法、非 descriptor 输入的 `TypeError`、继承场景(MRO 查找)、类型透传的 `reveal_type` 质量门
- [x] mutobj:更新 README 文档,说明新 API 与"`Cls.field_name` 类级访问返回 descriptor 为内部实现细节"的定位
- [x] mutgui:迁移 `action.py:296,299,428,440` 四处调用为 `mutobj.field_default(Cls.field)`,删除附近的 `# pyright: ignore`
- [x] mutgui:运行 `pyright src/mutgui` 验收 6 个 `make_default` 错误全部消失,无新增错误
- [x] mutbot/mutagent:grep `\.make_default\(\)` / `\.get_default\(\)`,识别同类消费点;有则同步迁移,无则记录备查结果
