# 类级别声明严格化 设计规范

**状态**：🔄 实施中
**日期**：2026-06-12
**类型**：重构

## 需求

1. **类级别"声明即承诺"对齐实例**：当前 Declaration / Extension / Implementation 的实例已严格（`__slots__` + `AttributeDescriptor` + `__mutobj_storage__`），但**类本身**仍允许：
   - 类体内无 annotation 直接赋值（`display_name = ""`）
   - 类创建后任意 `setattr` / `MyDecl.oops = 42`

2. **统一通过 `ClassVar[...]` 显式声明类级数据**。无注解 / 非 callable / 非 descriptor 的赋值一律拒绝。

3. **不破坏类声明常规写法**：annotation 字段、方法、`@property`、`classmethod` / `staticmethod`、`ClassVar` 必须能正常写。

## 范围边界

本 spec 仅处理**写入侧**严格化（"哪些值可以写到类上"）。类级**读取侧**的访问分发（`A.field` 应返回什么）留给独立的 `design-metaclass-getattribute.md` 设计文档，与该文档对齐但不耦合——即本 spec 的严格化保证 `cls.__dict__` 干净，为未来 `__getattribute__` 提供干净前提，但不引入 `__getattribute__` 本身。

## 关键参考

- `docs/specifications/feature-linear-field-storage.md` — 混合字段存储设计（📝 设计中）
- `docs/specifications/design-metaclass-getattribute.md` — metaclass `__getattribute__` 框架设计（📝 设计中）
- `docs/archive/2026-06-09-refactor-slots-field-storage.md` — Declaration 实例 `__slots__` 化（已完成）
- `docs/archive/2026-06-10-refactor-extension-implementation-strict.md` — Extension/Implementation 实例严格化（已完成）
- `src/mutobj/core/_declaration.py` `DeclarationMeta.__setattr__` — 当前仅校验 descriptor 写入；`desc is None` 时无防护放行
- `src/mutobj/core/_declaration.py` `DeclarationMeta.__new__` namespace 循环 `parent_desc is None: continue` — 类体无 annotation 数据属性的漏点
- `src/mutobj/core/_extensions.py` `ExtensionMeta` — 无 `__setattr__` 覆盖
- `src/mutobj/core/_implementation.py` `ImplementationMeta` — 无 `__setattr__` 覆盖
- `src/mutobj/core/_classmeta.py` — `DeclarationClassMeta` / `ExtensionClassMeta` / `ImplementationClassMeta` + 模块级 cache
- `src/mutobj/core/_reload.py` `update_class_inplace` — 走 `type.__setattr__` 绕过 metaclass，`hot-reload` 路径

## 设计方案

### Metaclass 类创建路径与攻击面

```
1. exec(class body) → namespace dict
2. metaclass.__new__(mcs, name, bases, namespace) → cls
   ├─ namespace["__slots__"] = () 注入（已有）
   ├─ super().__new__(mcs, name, bases, namespace)
   │   ↑ C 层：namespace 整体 → cls.__dict__（不经过 __setattr__）  ← 渠道 A
   ├─ process_field_annotations → setattr(cls, name, descriptor)    ← 渠道 B
   └─ namespace 二次循环：父类字段覆盖、方法挂载                     ← 渠道 B
3. metaclass.__init__(cls, ...)（默认空）
```

属性进入 `cls.__dict__` 仅有两个渠道：
- **渠道 A**：`super().__new__` 时 C 层从 namespace 整体拷贝
- **渠道 B**：metaclass 内或类创建后的 `setattr` / `type.__setattr__`

当前两个渠道的漏点：
- 渠道 A：namespace 二次循环里 `parent_desc is None: continue` 静默放过类体无 annotation 数据
- 渠道 B：`DeclarationMeta.__setattr__` 在 `desc is None` 分支 `super().__setattr__` 无防护放行

### 严格化锁两处

#### 渠道 A：metaclass `__new__` 拦截

`DeclarationMeta.__new__` 的 namespace 二次循环里 `parent_desc is None` 改为 `raise TypeError`，并指引用户加 `ClassVar[...]` 注解。

`ExtensionMeta` / `ImplementationMeta` 没有等价循环（只调 `process_field_annotations`），需在 `super().__new__()` 之后扫描 `cls.__dict__` 做同等校验。抽到 `_fields.py` 共享函数 `validate_class_namespace(cls, annotations, classvars, skip)`。

#### 渠道 B：metaclass `__setattr__` 白名单

三个 metaclass 共享白名单逻辑（按命中顺序）：

1. `isinstance(value, AttributeDescriptor)` → 现有 descriptor 分支
2. 已存在的 `AttributeDescriptor` 覆盖（`desc is not None`）→ 现有覆盖逻辑
3. callable / `classmethod` / `staticmethod` / `property` → 放行（`@impl`、delegate、monkey-patch 方法）
4. 已存在于 `cls.__dict__` 的属性覆盖 → 放行（覆盖现有 ClassVar / 方法）
5. 已声明 ClassVar（在 `mutobj_meta_cache[cls].classvars` 中，沿 MRO 查）→ 放行
6. 基础设施 dunder（`__module__`、`__doc__` 等白名单）→ 放行
7. 否则 → `AttributeError`

### ClassVar 存储策略

ClassVar 值直接存入 `cls.__dict__`（通过 `type.__setattr__`），不引入额外 descriptor 代理。理由：

- `cls.__dict__` 是 Python 类级数据的天然存储位置，MRO 继承机制免费送出
- 实例访问 `a.classvar` 通过 `object.__getattribute__` 自然上溯到 `cls.__dict__`，无需 metaclass 参与
- 严格化之后 `cls.__dict__` 内只有已声明数据——字段走 descriptor，ClassVar 走裸值，两者都是"已声明"，不存在歧义
- 不需要额外存储层（`__mutobj_classvars__` dict）或 copy-on-write 机制

### 改动范围

- `_declaration.py`：`__setattr__` 增白名单分支；`__new__` namespace 循环 `raise`
- `_extensions.py` / `_implementation.py`：新增 `__setattr__`；`__new__` 末尾调 `validate_class_namespace`
- `_fields.py`：新增 `validate_class_namespace` 共享函数 + `validate_class_setattr` 白名单校验
- `_constants.py`：新增 `MUTOBJ_CLASS_DUNDER_WHITELIST`
- `_reload.py`：`update_class_inplace` 中 `setattr` 统一改为 `type.__setattr__`，豁免严格化
- 测试：类级严格化行为
- 下游：3 处已加 `ClassVar` 注解（`mutbot/session.py` ×2 + `mutgui/modules.py` ×1，验证通过）
- 下游：2 处 monkey-patch 已消除（`mutgui/_viewport_impl.py`，改为 lazy import，验证通过）

**LOC 估算**：~150（含测试，下游改动已完成不计入）

### 已定案决策

#### Q1: hot-reload 豁免
`update_class_inplace` 中所有 `setattr(existing, ...)` 改为 `type.__setattr__(existing, ...)`，显式绕过 metaclass 校验。新类已通过完整严格校验，reload 是可信内部元操作。

#### Q2: Extension / Implementation 同步严格化
三套 metaclass 对称处理——`ExtensionMeta` / `ImplementationMeta` 新增 `__setattr__`，`__new__` 末尾调 `validate_class_namespace`。

### 效率

- `__setattr__` 仅在类级赋值时触发（极低频，类创建期 + 偶发 monkey-patch）
- `__new__` 末尾扫描 `cls.__dict__` 是类创建期一次性成本，量级 ~100 字段时亚毫秒
- **运行时零开销**——类创建后无额外拦截路径



## 实施步骤清单

- [x] `_constants.py` — 新增 `MUTOBJ_CLASS_DUNDER_WHITELIST`（基础设施 dunder 白名单）
- [x] `_fields.py` — 新增 `validate_class_setattr` 共享白名单校验函数
- [x] `_fields.py` — 新增 `validate_class_namespace` 共享函数，扫描 `cls.__dict__` 做渠道 A 校验
- [x] `_declaration.py` — `__setattr__` 增白名单分支（desc is None 时不再放行）
- [x] `_declaration.py` — `__new__` namespace 循环：`parent_desc is None` 时 `raise TypeError`（指引 ClassVar）
- [x] `_extensions.py` — 新增 `__setattr__`（共享白名单逻辑）
- [x] `_extensions.py` — `__new__` 末尾调 `validate_class_namespace`
- [x] `_implementation.py` — 新增 `__setattr__`（共享白名单逻辑）
- [x] `_implementation.py` — `__new__` 末尾调 `validate_class_namespace`
- [x] `_reload.py` — `update_class_inplace` 中 `setattr` 统一改为 `type.__setattr__`，豁免严格化
- [x] 测试 — 新增 `test_class_namespace_strict.py`：类体内无 annotation 赋值报错、`__setattr__` 拒绝未声明值、ClassVar 声明放行、白名单放行项
- [x] 全量回归测试通过（554 passed：530 原有 + 24 新增）

## 消费者场景

| 消费者 | 场景 | 依赖的输出 | 验收标准 |
|--------|------|-----------|---------|
| mutobj 自身测试 | 类级严格化行为 | `__setattr__` 拒绝未声明；`__new__` 拒绝无 annotation 类体赋值 | 新增测试通过 |
| mutbot / mutgui hot-reload | `_reload.py` 路径不被新 `__setattr__` 拦截 | 类同步成功 | reload 集成测试通过 |
| `design-metaclass-getattribute`（未来） | 严格化保证 `cls.__dict__` 干净 | `__getattribute__` 实现路径只需在 meta cache 与 cls.__dict__ 之间分发 | getattribute spec 实施时验证 |
