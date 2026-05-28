# Implementation API 精化 —— @property 支持、类型安全与错误语义

**状态**：✅ 已完成  
**日期**：2026-05-28  
**类型**：功能设计

## 需求

基于上一次 Implementation 桥接机制（`feature-implementation-class.md`）的落地情况，对模块级 API 的接口签名和功能覆盖做精化：

1. **`@property` 支持** — Implementation 子类中定义的 `@property` 自动桥接到 Declaration 的 property 覆盖链（getter/setter），与 `impl()` 装饰器对 `Decl.prop.getter` / `Decl.prop.setter` 的处理方式一致。

2. **`implementation_class` 签名收窄** — 只接受 `type[Declaration]`（类），不接受 Declaration 实例。调用方需要自己传 `type(decl)`。

3. **`implementation_of` 必须传 `impl_cls`** — 去掉 `impl_cls=None` 默认值，改为必传参数，利用泛型 `TypeVar("IT")` 让 pyright 推导返回类型为 Impl 实例类型。

4. **`implementation_owner` 泛型类型** — 参数类型收窄为 `Implementation[T]`，返回类型推导为 `T`（Declaration 子类）。

5. **公开 API 不返回 `None`** — `implementation_class`、`implementation_of`、`implementation_owner` 三个公开函数在找不到结果时抛出 `LookupError`，而非返回 `None`。消除调用方的判空负担，让 pyright 不需要处理 union 类型。

6. **pyright 类型验证 fixture** — 新增 `tests/type_check/fixtures/04_implementation.py`，用 `typing.assert_type` 验证上述三个 API 的静态类型推导正确、且无需判空。

### 核心约束

- **向后兼容**：`implementation_class` 去掉接受实例的重载、`implementation_of` 去掉 `impl_cls` 可选默认值是**破坏性变更**。需确认下游（mutagent 等）是否已有使用，决定迁移策略。

- **Impl 不受影响**：`Implementation` 基类和 `__init_subclass__` 钩子逻辑不变。本次只精化模块级查询 API 与自动注册扫描逻辑。

- **property 桥接与 `_implementation_bridge` 兼容**：getter bridge 签名 `(impl,) -> value`，setter bridge 签名 `(impl, value) -> None`，当前 `_implementation_bridge` 统一走 `impl_method(impl, *args, **kwargs)` 可复用，不需要改动 bridge 调用模型。

## 关键参考

### 源码

- `mutobj/src/mutobj/core/_implementation.py` — `Implementation` 基类、三个公开 API、`_implementation_bridge`、`_register_implementation_methods`、`_prepare_implementation_instance`
- `mutobj/src/mutobj/core/_impls.py:71-92` — `_apply_impl()`：将链顶实现应用到类方法/property（含 getter/setter 分支）
- `mutobj/src/mutobj/core/_impls.py:115-149` — `_register_to_chain()`：注册实现到覆盖链
- `mutobj/src/mutobj/core/_impls.py:345-412` — `impl()` 装饰器：`_PropertyGetterPlaceholder` / `_PropertySetterPlaceholder` 处理
- `mutobj/src/mutobj/core/_properties.py` — `Property` 描述符、`_PropertyGetterPlaceholder`、`_PropertySetterPlaceholder`
- `mutobj/src/mutobj/core/_constants.py` — `_DECLARED_PROPERTIES`、`_DECLARATION_CHAIN_HOOKS` 等标记常量
- `mutobj/src/mutobj/core/_declaration.py:148-190` — DeclarationMeta 中 property 声明处理（`property` → `Property` 转换、覆盖链初始化）
- `mutobj/src/mutobj/core/_declaration.py:318-323` — `DeclarationMeta.__call__`：`_prepare_implementation_instance` 调用点
- `mutobj/src/mutobj/core/_state.py` — `_implementation_class_registry`、`_implementation_instance_registry`、`_implementation_owner_registry`
- `mutobj/src/mutobj/__init__.py` — 公开导出清单

### 测试

- `mutobj/tests/test_implementation.py` — 现有 Implementation 功能测试
- `mutobj/tests/type_check/test_pyright.py` — pyright 类型验证测试框架（参数化 fixtures、`assert_type` 模式）
- `mutobj/tests/type_check/fixtures/02_extension.py` — 参考 fixture：`Extension` API 类型验证模式（`assert_type(ext, SessionExt)`）
- `mutobj/tests/type_check/fixtures/01_repro.py` — 参考 fixture：`Declaration.__new__` 返回 `Self` 类型验证

### 规范文档

- `mutobj/docs/specifications/feature-implementation-class.md` — 上一次 Implementation 桥接机制的设计规范（✅ 已完成），包含核心模型、构造流水线、方法自动注册规则

## 设计方案

### 1. 模块级 API 最终形态

本轮把 Implementation 查询 API 调整为“调用成功即有值，失败抛异常”的模型。

```python
from typing import Any, TypeVar

D = TypeVar("D", bound=mutobj.Declaration)
IT = TypeVar("IT", bound=mutobj.Implementation[Any])


def implementation_class(decl_cls: type[D]) -> type[mutobj.Implementation[D]]:
    """返回 decl_cls 沿 MRO 注册到的 Implementation 类；找不到抛 LookupError。"""


def implementation_of(decl: mutobj.Declaration, impl_cls: type[IT]) -> IT:
    """返回 decl 关联的 impl_cls 实例；找不到或类型不匹配抛 LookupError。"""


def implementation_owner(impl: mutobj.Implementation[D]) -> D:
    """返回 impl 关联的 Declaration 实例；找不到抛 LookupError。"""
```

#### 1.1 `implementation_class(decl_cls)`

- 只接受 Declaration 类：`type[D]`。
- 不再接受 Declaration 实例。
- 沿 `decl_cls.__mro__` 查询 `_implementation_class_registry`，保持“子类 Declaration 未注册自己的 Impl 时，复用父类 Impl”的现有语义。
- 找不到注册类时抛 `LookupError`。
- 非 Declaration 类或 Declaration 实例传入时抛 `TypeError`。

示例：

```python
impl_cls = mutobj.implementation_class(ConfigLoader)
# pyright: type[mutobj.Implementation[ConfigLoader]]
```

迁移旧写法：

```python
# 旧：允许传实例
impl_cls = mutobj.implementation_class(loader)

# 新：显式传类
impl_cls = mutobj.implementation_class(type(loader))
```

#### 1.2 `implementation_of(decl, impl_cls)`

- `impl_cls` 改为必传。
- `impl_cls` 类型为 `type[IT]`，返回类型为 `IT`，让调用方拿到具体 Impl 类型。
- `decl` 必须是 Declaration 实例。
- `impl_cls` 必须是 `Implementation` 子类。
- 找不到关联实例时抛 `LookupError`。
- 关联实例存在但不是 `impl_cls` 实例时抛 `LookupError`（语义是“没有这个类型的实现实例”）。
- 参数类型不合法时抛 `TypeError`。

示例：

```python
loader = ConfigLoader(path="/x")
impl = mutobj.implementation_of(loader, ConfigLoaderImpl)
# pyright: ConfigLoaderImpl
impl._load()
```

迁移旧写法：

```python
# 旧：省略 impl_cls，返回 Any | None
impl = mutobj.implementation_of(loader)

# 新：需要具体类型，且失败走异常
impl = mutobj.implementation_of(loader, ConfigLoaderImpl)
```

若调用方确实只有动态 Declaration 类型而不知道具体 Impl 类，可分两步：

```python
impl_cls = mutobj.implementation_class(type(loader))
impl = mutobj.implementation_of(loader, impl_cls)
# 静态类型只能是 Implementation[type(loader)] 层面的基类；需要具体成员时仍应传具体 Impl 类。
```

#### 1.3 `implementation_owner(impl)`

- 参数类型收窄为 `Implementation[D]`。
- 返回类型为 `D`。
- 找不到 owner 时抛 `LookupError`。
- 参数不是 `Implementation` 实例时抛 `TypeError`。

示例：

```python
class ConfigLoaderImpl(mutobj.Implementation[ConfigLoader]):
    def refresh(self) -> None:
        owner = mutobj.implementation_owner(self)
        # pyright: ConfigLoader
        owner.path
```

### 2. 内部 nullable helper 与公开 API 分离

公开 API 不返回 `None` 后，内部构造流程仍需要“查不到就跳过”的 nullable 语义。例如普通 `Declaration` 子类没有注册 Implementation 时，构造必须继续成功，而不是因为 `_prepare_implementation_instance()` 调用了公开 `implementation_class()` 而抛 `LookupError`。

因此实现上引入内部 helper，把“可选查询”和“公开查询”分开：

```python
def _lookup_implementation_class(
    decl_cls: type[Declaration],
) -> type[Implementation[Any]] | None:
    ...


def _lookup_implementation_instance(
    decl: Declaration,
    impl_cls: type[IT],
) -> IT | None:
    ...


def _lookup_implementation_owner(
    impl: object,
) -> Declaration | None:
    ...
```

调用关系：

```text
_prepare_implementation_instance
  -> _lookup_implementation_class(...)     # None 表示无 Impl，正常跳过

implementation_class
  -> 参数校验
  -> _lookup_implementation_class(...)
  -> None => LookupError

implementation_of
  -> 参数校验
  -> _lookup_implementation_instance(...)
  -> None => LookupError

implementation_owner
  -> 参数校验
  -> _lookup_implementation_owner(...)
  -> None => LookupError
```

这样既满足公开 API 的非 Optional 类型，又不破坏 Declaration 构造管线。

### 3. 错误语义

本轮统一为：

| 场景 | 异常类型 | 说明 |
|------|----------|------|
| 参数类型不合法 | `TypeError` | 例如 `implementation_class(decl_instance)`、`implementation_of(obj, Impl)`、`implementation_owner(object())` |
| 参数类型合法但没有查询结果 | `LookupError` | 例如没有注册 Impl、没有关联实例、owner 已失效、实际 Impl 类型不匹配 |
| 框架内部不变量破坏 | `RuntimeError` | 例如桥接函数执行时按注册关系应有实例却没有；是否保留现有 `RuntimeError` 由实现选择，但不影响公开 API 语义 |

推荐错误消息：

```text
LookupError: No Implementation class is registered for ConfigLoader
LookupError: No ConfigLoaderImpl instance is associated with ConfigLoader instance
LookupError: Implementation instance for ConfigLoader is BaseLoaderImpl, expected ConfigLoaderImpl
LookupError: No Declaration owner is associated with ConfigLoaderImpl instance
TypeError: implementation_class() expects a mutobj.Declaration class, got ConfigLoader instance
TypeError: implementation_of() expects impl_cls to be an Implementation subclass
```

### 4. `@property` 自动桥接

#### 4.1 目标语义

Declaration 中声明 property：

```python
class Product(mutobj.Declaration):
    price: float

    @property
    def display_price(self) -> str:
        ...

    @display_price.setter
    def display_price(self, value: str) -> None:
        ...
```

Implementation 中用普通 Python property 实现：

```python
class ProductImpl(mutobj.Implementation[Product]):
    @property
    def display_price(self) -> str:
        owner = mutobj.implementation_owner(self)
        return f"${owner.price:.2f}"

    @display_price.setter
    def display_price(self, value: str) -> None:
        owner = mutobj.implementation_owner(self)
        owner.price = float(value.removeprefix("$"))
```

调用方仍只接触 Declaration：

```python
p = Product(price=12.5)
assert p.display_price == "$12.50"
p.display_price = "$9.00"
assert p.price == 9.0
```

#### 4.2 注册规则

在 `_register_implementation_methods()` 扫描 `impl_cls.__dict__` 时增加 property 分支：

| Impl 类成员 | Declaration 条件 | 注册行为 |
|-------------|------------------|----------|
| `@property` 且 `name` 在 Decl 的 `_DECLARED_PROPERTIES` 中，`fget is not None` | Decl 声明了同名 property | 注册到 `f"{name}.getter"` 覆盖链 |
| 同上，`fset is not None` | Decl 声明了同名 property | 注册到 `f"{name}.setter"` 覆盖链 |
| `@property` 但 Decl 没有同名 property | 无 | 不注册，保留为 Impl 内部 property |
| 普通 callable | 沿用现有方法注册规则 | 注册到同名 Declaration 方法 / hook |

伪代码：

```python
declared_properties: set[str] = getattr(target_cls, _DECLARED_PROPERTIES, set())

for member_name, member_value in impl_cls.__dict__.items():
    if isinstance(member_value, property):
        if member_name not in declared_properties:
            continue
        if member_value.fget is not None:
            _register_impl_property_accessor(
                target_cls,
                impl_cls,
                member_name,
                "getter",
                member_value.fget,
                source_key,
            )
        if member_value.fset is not None:
            _register_impl_property_accessor(
                target_cls,
                impl_cls,
                member_name,
                "setter",
                member_value.fset,
                source_key,
            )
        continue

    # existing callable method path
```

`_register_impl_property_accessor()` 等价于对 `@impl(Decl.prop.getter)` / `@impl(Decl.prop.setter)` 做自动 bridge：

```python
impl_key = f"{prop_name}.{accessor_kind}"  # "display_price.getter" / "display_price.setter"
accessor_func.__mutobj_source_key__ = source_key
bridge = _implementation_bridge(target_cls, impl_cls, impl_key, accessor_func, source_key)
became_top = _register_to_chain(target_cls, impl_key, bridge, source_key)
if became_top:
    _apply_impl(target_cls, impl_key, bridge)
```

#### 4.3 与覆盖链、显式 `@impl` 的关系

Implementation 自动桥接的 property accessor 与显式 `@impl(Decl.prop.getter)` / `@impl(Decl.prop.setter)` 进入同一条覆盖链：

```text
Product.display_price.getter 覆盖链：
  chain[0] = Declaration property getter 默认实现
  chain[1] = ProductImpl.display_price.fget 自动桥接
  chain[2] = @impl(Product.display_price.getter) 显式覆盖
```

沿用上一版 Implementation 的 source key 设计：

```text
显式 @impl source key:             module
Implementation 自动 bridge key:   module::implementation::QualName
```

因此即使显式 `@impl` 与 `ProductImpl` 定义在同一模块，也不会发生同模块替换，二者可以在同一覆盖链中共存，并通过 `impl_call_super()` 串联。

#### 4.4 `impl_call_super()` 一致性

如果希望 Impl property getter/setter 内部也能调用 `impl_call_super()`，需要让 `_resolve_frame_source_key()` 能从 property accessor frame 反推 source key。现有逻辑只会解包 `classmethod` / `staticmethod` / 普通 callable；property 对象不是 callable。

建议同步扩展 `_resolve_frame_source_key()`：

```python
candidate = klass.__dict__.get(method_name)
if isinstance(candidate, property):
    for accessor in (candidate.fget, candidate.fset, candidate.fdel):
        if accessor is not None and getattr(accessor, "__code__", None) is frame.f_code:
            return _resolve_source_key(accessor)
```

并在注册 property accessor 时给 `fget` / `fset` 写入 `__mutobj_source_key__ = source_key`。这样以下写法可用：

```python
class ProductImpl(mutobj.Implementation[Product]):
    @property
    def display_price(self) -> str:
        owner = mutobj.implementation_owner(self)
        base = mutobj.impl_call_super(Product.display_price.getter, owner)
        return base.upper()
```

若实施时希望严格收窄本轮范围，可以把 property accessor 中调用 `impl_call_super()` 标为暂不支持；但为了与普通方法自动桥接保持一致，本 spec 推荐同步支持。

### 5. 类型设计与 pyright 验证

新增 fixture：`tests/type_check/fixtures/04_implementation.py`。

目标：验证三个公开 API 都不产生 Optional，且具体 Impl 类型可推导。

```python
from __future__ import annotations

from typing import assert_type

import mutobj


class Loader(mutobj.Declaration):
    path: str

    def load(self) -> str: ...


class LoaderImpl(mutobj.Implementation[Loader]):
    cache: dict[str, str]

    def load(self) -> str:
        owner = mutobj.implementation_owner(self)
        assert_type(owner, Loader)
        return owner.path


def use(loader: Loader) -> str:
    impl = mutobj.implementation_of(loader, LoaderImpl)
    assert_type(impl, LoaderImpl)

    impl.cache = {}

    owner = mutobj.implementation_owner(impl)
    assert_type(owner, Loader)

    impl_cls = mutobj.implementation_class(Loader)
    assert_type(impl_cls, type[mutobj.Implementation[Loader]])

    return impl.load()
```

不再需要：

```python
impl = mutobj.implementation_of(loader, LoaderImpl)
if impl is None:
    ...
```

也不再允许 fixture 中出现：

```python
mutobj.implementation_of(loader)        # pyright 应报缺少 impl_cls
mutobj.implementation_class(loader)     # pyright 应报参数类型不匹配
```

这类“应报错”用例不放入零诊断 fixture；如需锁定，可在后续引入负向 pyright 测试框架。

## 兼容性与迁移

### 破坏性变更清单

| 旧写法 | 新写法 | 迁移原因 |
|--------|--------|----------|
| `implementation_class(decl)` | `implementation_class(type(decl))` | API 只接受类，避免实例/类双语义 |
| `implementation_of(decl)` | `implementation_of(decl, ConcreteImpl)` | 让 pyright 推导具体 Impl 类型 |
| `impl = implementation_of(...); if impl is None:` | `try: impl = implementation_of(...); except LookupError:` | 公开 API 不返回 Optional |
| `owner = implementation_owner(...); assert owner is not None` | `owner = implementation_owner(...)` | 返回值不再是 Optional |

### 下游扫描建议

实施前应在 mono-repo 中扫描：

```bash
rg "implementation_class\(" mutagent mutbot mutgui mutobj
rg "implementation_of\(" mutagent mutbot mutgui mutobj
rg "implementation_owner\(" mutagent mutbot mutgui mutobj
```

重点关注：

- `implementation_class(x)` 中 `x` 是否可能是实例。
- `implementation_of(x)` 是否省略了第二个参数。
- 是否依赖 `None` 表示“不存在”。
- 是否存在 `assert owner is not None` 这类现在多余但不破坏运行的代码。

### 发版策略

这是 `0.x` 阶段可接受的破坏性 API 调整，但仍建议：

1. 在 changelog / release note 中明确列出迁移表。
2. 同步更新 `docs/api/reference.md`。
3. mutobj 自身测试先迁移到新 API，避免继续传播旧用法。
4. 如 mutagent / mutgui / mutbot 已有旧用法，跟随同一提交或同一批次提交迁移。

## 测试计划

### 1. Runtime：property 自动桥接

新增或扩展 `tests/test_implementation.py`：

1. **getter 自动桥接**
   - Decl 声明 property getter。
   - Impl 定义同名 `@property`。
   - 访问 `decl.prop` 返回 Impl getter 结果。

2. **setter 自动桥接**
   - Decl 声明 property setter 或至少声明同名 property。
   - Impl 定义同名 property setter。
   - 执行 `decl.prop = value` 后，Impl setter 被调用并更新 owner 或 impl 状态。

3. **getter + setter 同时桥接**
   - 同一个 Impl property 的 `fget` / `fset` 分别注册到 `.getter` / `.setter` 覆盖链。

4. **未声明 property 不注册**
   - Impl 内部 property 名不在 Decl `_DECLARED_PROPERTIES` 中。
   - 不应污染 Declaration，也不应抛错。

5. **显式 `@impl` 与 Impl property bridge 共存**
   - Impl property getter 自动注册。
   - 同模块再显式 `@impl(Decl.prop.getter)` 覆盖，并调用 `impl_call_super()`。
   - 断言 super 调到 Impl property bridge。

6. **unregister 行为**
   - 调用 `unregister_module_impls(__name__)` 后，property 覆盖链恢复到默认实现或下一级实现。

### 2. Runtime：公开 API 错误语义

1. `implementation_class(Decl)` 返回 Impl 类。
2. `implementation_class(DeclWithoutImpl)` 抛 `LookupError`。
3. `implementation_class(decl_instance)` 抛 `TypeError`。
4. `implementation_of(decl, Impl)` 返回 Impl 实例。
5. `implementation_of(decl, WrongImpl)` 抛 `LookupError`。
6. `implementation_of(decl_without_impl, Impl)` 抛 `LookupError`。
7. `implementation_of(decl, object)` / `implementation_of(decl, NotImplementationClass)` 抛 `TypeError`。
8. `implementation_owner(impl)` 返回 owner。
9. `implementation_owner(unbound_impl)` 抛 `LookupError`。
10. `implementation_owner(object())` 抛 `TypeError`。
11. 没有 Impl 的普通 Declaration 构造仍然成功，证明 `_prepare_implementation_instance()` 没有误用公开 `implementation_class()`。
12. 子类 Declaration 未注册自己的 Impl 时，`implementation_class(Child)` 仍返回父类 Impl，`implementation_of(child, ParentImpl)` 正常。

### 3. Type check：pyright fixture

新增 `tests/type_check/fixtures/04_implementation.py`，并通过现有 `tests/type_check/test_pyright.py` 自动纳入。

验收：

```bash
pytest tests/type_check/test_pyright.py
# 04_implementation.py: 0 errors, 0 warnings
```

### 4. 全量回归

```bash
pytest
pyright src/mutobj
```

## 文档更新

`docs/api/reference.md` 增加 Implementation 章节，至少包含：

- `mutobj.Implementation[T]` 的定位：迁移普通类、自动桥接同名方法与 property。
- `implementation_class(decl_cls)`：只传类，返回 Implementation 类，失败 `LookupError`。
- `implementation_of(decl, impl_cls)`：必须传具体 Impl 类，返回具体 Impl 实例，失败 `LookupError`。
- `implementation_owner(impl)`：Impl 内部拿 owner，返回 Declaration 实例，失败 `LookupError`。
- property 自动桥接示例。
- 破坏性变更迁移表。

## 实施步骤清单

- [x] 在 `_implementation.py` 中新增内部 nullable lookup helper，公开 API 改为非 Optional + `LookupError`
- [x] 调整 `implementation_class` 签名：只接受 `type[D]`，删除实例分支
- [x] 调整 `implementation_of` 签名：`impl_cls` 必传，返回 `IT`
- [x] 调整 `implementation_owner` 签名：参数 `Implementation[D]`，返回 `D`
- [x] 修改 `_prepare_implementation_instance()` 使用内部 `_lookup_implementation_class()`，避免无 Impl 时抛错
- [x] 修改 `_implementation_bridge()` 使用新查询语义或内部 lookup，保证桥接错误信息清晰
- [x] 在 `_register_implementation_methods()` 中增加 Impl `@property` getter/setter 自动注册
- [x] 为 property accessor 写入 `__mutobj_source_key__`
- [x] 推荐同步扩展 `_resolve_frame_source_key()` 支持 property accessor frame，以保持 `impl_call_super()` 一致性
- [x] 更新 `tests/test_implementation.py`：迁移旧 API 用法，补 property bridge 与错误语义测试
- [x] 新增 `tests/type_check/fixtures/04_implementation.py`
- [x] 更新 `docs/api/reference.md`
- [x] 扫描并迁移下游 mutagent / mutbot / mutgui 的旧 API 用法
- [x] 运行 `pytest` 与 `pyright src/mutobj`

## 测试验证

- `pytest`
- `pyright src/mutobj`
- `pytest tests/sandbox/test_adapter_mcp.py tests/sandbox/test_pysandbox_sharing.py tests/sandbox/test_namespace_multi_provider.py`（`mutagent`）
- `pyright src/mutagent/sandbox/mcp.py src/mutagent/sandbox/_namespace.py src/mutagent/webui/_settings_mcp.py src/mutagent/app/_app_impl.py`

## 范围外

- 字段桥接（`decl.field` 自动转发到 `impl.field`）仍不纳入本轮。
- 一个 Declaration 支持多个 Implementation 仍不纳入本轮。
- 为 `implementation_of(decl)` 提供动态 get-or-create 或无类型参数重载不纳入本轮。
- 负向 pyright 测试框架不纳入本轮；本轮只新增零诊断 fixture。
