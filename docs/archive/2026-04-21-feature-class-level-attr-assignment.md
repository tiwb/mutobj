# DeclarationMeta.__setattr__ — 运行时类级属性赋值 设计规范

**状态**：✅ 已完成
**日期**：2026-04-21
**类型**：功能设计

## 需求

1. `MyDecl.attr = value` 应更新 AttributeDescriptor 的 default，而非替换描述符
2. 当前行为：类级赋值摧毁描述符，新实例通过 Python 普通类属性继承拿到值（机制意外可用但描述符已丢失）
3. 子类覆盖（`class Sub(Base): attr = value`）已在 `DeclarationMeta.__new__` 中正确处理（505-542行），但运行时赋值未覆盖

## 关键参考

- `src/mutobj/core.py:240` — `AttributeDescriptor` 类，`__get__`/`__set__` 只处理实例级访问
- `src/mutobj/core.py:437` — `DeclarationMeta.__new__`，类创建时的属性处理
- `src/mutobj/core.py:505-542` — 子类无注解属性覆盖逻辑（已正确创建新 AttributeDescriptor）
- `src/mutobj/core.py:745-762` — `Declaration.__new__`，遍历 MRO 为有默认值的 AttributeDescriptor 设置实例初始值

## 设计方案

### 问题分析

Python 描述符协议中，`type.__setattr__` 直接替换类 `__dict__` 中的值，不经过描述符的 `__set__`。因此 `MyDecl.attr = "new_value"` 会用字符串覆盖 `AttributeDescriptor` 对象。

子类场景在 `DeclarationMeta.__new__` 中处理了（类创建时扫描 namespace），但运行时赋值发生在类创建之后，无拦截点。

### 方案：DeclarationMeta.__setattr__

在 `DeclarationMeta` 上定义 `__setattr__`，拦截类级赋值：

```python
def __setattr__(cls, name: str, value: Any) -> None:
    # 已经是描述符赋值（DeclarationMeta.__new__ 内部调用），放行
    if isinstance(value, AttributeDescriptor):
        super().__setattr__(name, value)
        return

    # 当前类或 MRO 中有该属性的 AttributeDescriptor
    desc = cls.__dict__.get(name)
    if desc is None:
        for base in cls.__mro__[1:]:
            base_desc = base.__dict__.get(name)
            if isinstance(base_desc, AttributeDescriptor):
                desc = base_desc
                break

    if isinstance(desc, AttributeDescriptor):
        if isinstance(value, _MUTABLE_TYPES):
            type_name = type(value).__name__
            raise TypeError(
                f"Declaration '{cls.__name__}' attribute '{name}' uses mutable default "
                f"value {type_name}. "
                f"Use field(default_factory={type_name}) instead."
            )
        if isinstance(value, Field):
            new_desc = AttributeDescriptor(
                name, desc.annotation,
                default=value.default,
                default_factory=value.default_factory,
            )
        else:
            new_desc = AttributeDescriptor(name, desc.annotation, default=value)
        super().__setattr__(name, new_desc)
        return

    super().__setattr__(name, value)
```

### 设计要点

- **就地创建新 AttributeDescriptor**（非修改原描述符的 `.default`），保持不可变语义，避免影响父类描述符
- **MRO 查找**：当赋值发生在子类上、描述符在父类时，在子类上创建新描述符（与 `__new__` 中的子类覆盖逻辑一致）
- **复用现有校验**：可变类型检查、Field 支持，与 `__new__` 中逻辑对齐
- **`_attribute_registry` 同步**：当子类首次覆盖父类属性（描述符来自 MRO 而非 `cls.__dict__`）时，需将 `name -> annotation` 加入 `_attribute_registry[cls]`；若子类已有同名条目（之前覆盖过），则无需更新（annotation 不变）。同时清除 `_ordered_fields_cache` 中 `cls` 的缓存（新字段改变了有序字段列表）
- **已有实例不受影响**：运行时赋值只替换类上的描述符默认值。已创建的实例在 `__new__` 时已将默认值写入实例 `__dict__`，描述符 `__get__` 优先返回实例值，因此不受影响。只有赋值之后新建的实例才使用新默认值
- **annotation 继承**：从父类描述符继承 `desc.annotation` 创建新描述符。运行时赋值不支持修改类型注解（改注解应通过子类声明体完成，由 `__new__` 处理）
- **非声明属性放行**：不匹配 AttributeDescriptor 的赋值直接 `super().__setattr__`，不影响 `_DECLARED_METHODS` 等内部属性

## 测试用例

- [x] **基类运行时赋值** — `Base.attr = new_value` 后，新实例 `Base()` 拿到新默认值
- [x] **子类运行时赋值** — `Sub.attr = new_value`（描述符在父类），子类创建新描述符，父类不受影响
- [x] **已有实例不受影响** — 赋值前创建的实例保持原值
- [x] **Field 对象赋值** — `Base.attr = field(default_factory=list)` 正确创建带 factory 的描述符
- [x] **可变类型报错** — `Base.attr = []` 抛出 `TypeError`，提示使用 `field(default_factory=list)`
- [x] **非声明属性放行** — `MyDecl._internal = 1` 或 `MyDecl.some_new = "x"` 正常赋值，不创建描述符
- [x] **_attribute_registry 同步** — 子类首次覆盖后，`_attribute_registry[Sub]` 包含该属性
- [x] **描述符赋值放行** — 内部 `setattr(cls, name, AttributeDescriptor(...))` 不被拦截

## 实施步骤清单

- [x] 在 `DeclarationMeta` 中实现 `__setattr__` 方法
- [x] 编写测试用例
- [x] 运行测试 + 类型检查，确保无回归
