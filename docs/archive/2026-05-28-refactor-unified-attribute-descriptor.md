# AttributeDescriptor 与 Property 统一设计规范

**状态**：✅ 已完成
**日期**：2026-05-28
**类型**：重构

## 需求

1. `Declaration` 上的存储字段和 `@property` 字段统一为同一种 descriptor 运行时类型。
2. `Implementation` 注册时，不再静默跳过与 Declaration 同名但类型不匹配的成员。
3. 只读语义由 unified `AttributeDescriptor` 直接承载，为后续 `ReadOnly` 设计铺路。

## 关键参考

- `src/mutobj/core/_fields.py` — unified `AttributeDescriptor`、getter/setter token、默认访问器恢复逻辑
- `src/mutobj/core/_declaration.py` — Declaration 上存储字段 / 计算字段的注册路径
- `src/mutobj/core/_impls.py` — accessor 覆盖、`impl_call_super()` 来源解析、卸载恢复
- `src/mutobj/core/_implementation.py` — Implementation 类成员注册与类型不匹配报错
- `src/mutobj/core/_reload.py` — 热重载时 unified descriptor 的 owner 迁移
- `tests/test_property.py` — property 兼容性行为
- `tests/test_implementation.py` — bridge 行为与类型不匹配报错

## 设计方案

### Unified `AttributeDescriptor`

`Declaration` 上所有公开字段 token 现在都是 `AttributeDescriptor`，但分为两种运行模式：

| 模式 | `has_storage` | 默认 getter | 默认 setter | `readonly` |
|------|---------------|-------------|-------------|------------|
| 注解字段（`name: str`） | True | 读 `storage_name` | 写 `storage_name` | False |
| 计算字段（`@property`）无 setter | False | 类体 `fget` | None | True |
| 计算字段（`@property` + setter） | False | 类体 `fget` | 类体 `fset` | False |

统一后的 `AttributeDescriptor` 提供：

- `getter` / `setter` token，继续支持 `@mutobj.impl(Decl.prop.getter)` 和 `@mutobj.impl(Decl.prop.setter)`
- `owner_cls`，用于 accessor token 解析
- `restore_default_getter()` / `restore_default_setter()`，在卸载 impl 时回到类体默认行为

### 注册表语义

统一的是 **descriptor 类型**，不是所有 descriptor 都并入现有“存储字段注册表”语义。

- `_attribute_registry` **继续只记录存储字段**
- `Declaration.__new__` 只给 `has_storage=True` 的字段落默认值
- `_get_init_fields()` 只返回 `has_storage=True and init=True` 的字段
- `mutobj.fields()` 继续只暴露存储字段
- 计算字段通过类字典中的 `AttributeDescriptor` 与 `_get_attribute_descriptor()` 参与运行时解析

这样保持了现有存储字段反射 / 构造行为不变，同时让 property 运行时也统一成 `AttributeDescriptor`。

### 默认实现与覆盖链语义

property 类体中的 getter/setter 仍然是覆盖链的默认实现，而不是只有 `@impl` 才算实现。

- `@property def x(self): ...` 的类体 `fget` 会作为 `x.getter` 的默认链底
- `@x.setter` 的类体 `fset` 会作为 `x.setter` 的默认链底
- `impl_call_super(Decl.x.getter, self)` / `impl_call_super(Decl.x.setter, self, value)` 继续沿用现有覆盖链语义
- 卸载模块级 impl 后，getter/setter 会恢复到类体默认访问器，而不是退化成未实现状态

### Implementation 注册规则

Implementation 类中的同名成员现在会执行显式类型校验：

| Declaration 上的声明 | Implementation 里写了 | 结果 |
|----------------------|-----------------------|------|
| 存储字段 | `@property` | 报错 |
| 存储字段 | 普通方法 | 报错 |
| 计算字段 | 普通方法 | 报错 |
| 方法 / classmethod / staticmethod | `@property` | 报错 |
| 方法 / classmethod / staticmethod | 同名 callable | 正常注册 |
| Declaration 上不存在 | 任意成员 | 继续视为 impl 内部辅助成员，静默忽略 |

## 兼容性结论

现有主流消费端用法不需要修改：

- `@mutobj.impl(Decl.prop.getter)` / `@mutobj.impl(Decl.prop.setter)` 不变
- `mutobj.impl_call_super(Decl.prop.getter, self)` 不变
- `isinstance(Decl.prop, mutobj.AttributeDescriptor)` 现在对注解字段和 property 都成立
- `mutobj.fields()`、构造参数、默认值行为保持存储字段语义，不会把计算字段错误混入

## 实施步骤清单

- [x] 扩展 `AttributeDescriptor`，统一承载存储字段与计算字段
- [x] 移除运行时 `Property` 路径，改为直接在 Declaration 上挂 unified descriptor
- [x] 保留 property 类体默认访问器与 `impl_call_super()` 语义
- [x] 为 Implementation 注册补齐类型不匹配报错
- [x] 更新测试覆盖 unified descriptor 与报错行为
- [x] 重写规范文档，反映最终设计

## 测试验证

- `pytest`
- `pyright`
- `mutobj-lint`
