# `@impl` 及相关 API 的非 Declaration 类守卫

**状态**：✅ 已完成
**日期**：2026-05-15
**类型**：重构

## 需求

`@impl` 在 `_resolve_impl_key` 中有一层 fallback `method.__globals__.get(class_name)`，使 `@impl` 可以"碰巧"作用于非 `mutobj.Declaration` 子类的普通 Python 类。这不是刻意设计——mutobj 架构文档和 guide 中所有示例都在 Declaration 子类上使用 `@impl`。

当前 mutgui 利用了这个未定义行为：`EventHandler`（纯普通类）的子类 `MenuTrigger` 使用了 `@impl(MenuTrigger.handle)`。这引发连锁问题：

1. 开发者看到后会误以为这是合法模式，在其他地方模仿
2. `@impl` 对普通类退化为 `setattr` 替换方法，不走 stub→delegate→chain 机制
3. 相关 API（`impl_has`、`impl_chain`、`impl_call_super`、`unregister_module_impls`）对普通类的行为未经测试

需要排查所有依赖 `_resolve_impl_key` 的公开 API，对非 Declaration 目标类增加类型检查报错。

## 关键参考

- `src/mutobj/core.py:1176-1235` — `_resolve_impl_key`：三层解析，第三层 `__globals__` fallback 是根因
- `src/mutobj/core.py:235-273` — `_register_to_chain`：`_impl_chain` key 为 `(type, str)`，不检查 Declaration
- `src/mutobj/core.py:189-230` — `_apply_impl` / `_restore_stub`：对非 Declaration 的 classmethod/staticmethod 会 fall through 到 `setattr`
- `src/mutobj/core.py:1435-1530` — `impl()` 装饰器
- `src/mutobj/core.py:1285-1307` — `impl_has` / `impl_has_override` / `impl_chain`
- `src/mutobj/core.py:1373-1425` — `impl_call_super`
- `src/mutobj/core.py:1535-1568` — `unregister_module_impls`

### mutgui 违规现场

- `src/mutgui/events.py:185` — `class EventHandler:`（非 Declaration）
- `src/mutgui/events.py:275` — `class Callback(EventHandler)`
- `src/mutgui/events.py:325` — `class Bind(EventHandler)`
- `src/mutgui/menu.py:55` — `class MenuTrigger(EventHandler)`
- `src/mutgui/_menu_impl.py:65` — `@impl(MenuTrigger.handle)`

## 设计方案

### 受影响 API 排查

所有通过 `_resolve_impl_key` 获取目标类的公开 API：

| API | 非 Declaration 时行为 | 需要守卫 |
|-----|---------------------|---------|
| `impl()` | `setattr` 替换方法，不走 stub/delegate 链 | ✅ 是 |
| `impl_has()` | 查 `_impl_chain`，能返回结果但语义错误 | ✅ 是 |
| `impl_has_override()` | 同上 | ✅ 是 |
| `impl_chain()` | 同上 | ✅ 是 |
| `impl_call_super()` | 通过 caller 模块在链中定位，非 Declaration 无 stub entry | ✅ 是 |
| `call_super_impl()` | 委托给 `impl_call_super` | ✅ 是 |
| `unregister_module_impls()` | `_restore_stub` 对非 Declaration 的 property/classmethod/staticmethod fall through | ✅ 是 |
| `get_declaration_doc()` | 查 `_impl_chain` 中 `__default__` entry，无实际副作用 | ❌ 不需要 |

以下 API 已通过其他机制安全（不依赖 `_resolve_impl_key` 的 `__globals__` fallback）：

| API | 安全保障 |
|-----|---------|
| `discover_subclasses()` | 只查 `_class_registry`（仅 Declaration 注册） |
| `resolve_class()` | 只查 `_class_registry` + `DeclarationMeta.__new__` 自动注册 |
| `fields()` | 依赖 `_attribute_registry`（仅 DeclarationMeta 填充） |
| `field_default()` | `isinstance(field, AttributeDescriptor)` 守卫 |
| `field_info()` | 同上 |
| `extension_types()` | 类型签名 `type[Declaration]`，pyright 已覆盖 |
| `extensions()` | 类型签名 `Declaration`，pyright 已覆盖 |

### 决策：守卫点选 `_resolve_impl_key`，`__globals__` fallback 仅对 Declaration 放行

候选方案：

- **方案 A**：在每个公开 API 入口增加 `issubclass(target_cls, Declaration)` 检查
- **方案 B**：在 `_resolve_impl_key` 中集中检查，保留 `__globals__` fallback 原样转发
- **方案 C**：在 `_resolve_impl_key` 中集中检查，**`__globals__` fallback 仅对 Declaration（含 Declaration 本身）放行**，对非 Declaration 类直接报 TypeError；同时对局部类场景（`__globals__` 拿不到具体类）从 qualname 解析出 simple name 生成针对性错误信息

**选定方案 C**。理由：

- `_resolve_impl_key` 是唯一瓶颈，一处改动让所有依赖它的 API（含 `impl_call_super` / `call_super_impl`）传递性获得保护，避免逐个 API 加检查的遗漏风险。
- fallback 不能一刀切：子类未桊、反推到 Declaration 基类是合法路径（详见下方限定），仍需 fallback 拿到 Declaration、交由 `impl()` 装饰器的 `_DECLARATION_USER_HOOKS` 检查抦截。
- 错误信息质量：全局类从 `__globals__` 拿到实体，局部类从 qualname 解析出 simple name，两种场景都能在错误信息里点名。

**fallback 放行范围限定**：仅在 `__globals__` 拿到的 candidate 是 Declaration 子类或 Declaration 本身时才赋值给 `target_cls`。其他场景一律报 TypeError。

### 修改内容

#### `_resolve_impl_key` 改动

原第 3 层 fallback 是 `target_cls = method.__globals__.get(class_name)`，无条件赋值。改为：仅当 `__globals__` 拿到的是 Declaration 子类或 Declaration 本身时才赋值；拿到的是普通类报 TypeError；`__globals__` 拿不到（局部类）时从 qualname 解析出 simple name 然后报 TypeError。最后保留原 `ValueError` 作为兜底。

```python
# 取代原 fallback 分支（位于外层 `if target_cls is None:` 块内，与
# class_name 同作用域）
if target_cls is None:
    candidate = (
        method.__globals__.get(class_name)
        if hasattr(method, "__globals__") else None
    )
    if isinstance(candidate, type):
        if issubclass(candidate, Declaration) or candidate is Declaration:
            target_cls = candidate  # 合法路径：反推到 Declaration 基类
        else:
            raise TypeError(
                f"@impl({candidate.__name__}.{method_name}): "
                f"{candidate.__name__} is not a mutobj.Declaration subclass. ..."
            )
    else:
        # 局部类场景：__globals__ 拿不到，从 qualname 去除 <locals> 后取末段
        parts = [p for p in class_name.split(".") if p and p != "<locals>"]
        cls_display = parts[-1] if parts else "<unknown>"
        raise TypeError(f"@impl({cls_display}.{method_name}): ...")

# 最外层兜底：qualname 不含 "." 的 callable 仍会被更上游报 ValueError
if target_cls is None:
    raise ValueError(f"Cannot find class for method {method_name}")
```

实际实现中错误信息是完整多行提示（含修复指引），此处省略，详见下方"错误信息样例"。

**作用域要点**：`class_name` 只在上游 `if "." in qualname:` 分支被绑定，诊断分支必须与上游同位于同一个 `if target_cls is None:` 块内，pyright 才会认为其已绑定。

第 1 层 `__mutobj_class__` 由 `DeclarationMeta._meta_register` 自动设置，外部 API 不暴露，**基于约定不再额外校验**。

#### 错误信息样例

```
TypeError: @impl(MenuTrigger.handle): MenuTrigger is not a mutobj.Declaration subclass.
@impl only supports Declaration subclasses.
To fix:
  - Make MenuTrigger inherit from mutobj.Declaration, or
  - Write the implementation directly in the class body (no @impl)
```

#### `_restore_stub` 不再加防御断言

入口（`_resolve_impl_key`）已经卡死后，`_impl_chain` 不可能出现非 Declaration 的 key。在 `_restore_stub` 加冗余断言反而让人怀疑"是不是入口不可靠"。**保持简洁，不加。**

#### 受影响 API 的保护是传递性的

`impl()` / `impl_has` / `impl_has_override` / `impl_chain` / `impl_call_super` / `call_super_impl` / `unregister_module_impls` 都通过 `_resolve_impl_key` 获取目标类，无需单独修改即可获得保护。

### 对下游的影响

**mutgui 需要同步整改**：`EventHandler` 改为 `mutobj.Declaration` 子类，或去掉 `@impl(MenuTrigger.handle)` 改为类内方法。

这个整改另开 SDD（`mutgui/docs/specifications/refactor-eventhandler-declaration.md`）。本文档不涵盖 mutgui 侧的修改。

### 测试

需补 8 个测试用例，分为三类：

1. **`@impl` 拒绝非 Declaration**：`@impl(PlainClass.foo)` 招 TypeError；错误信息含类名、方法名、修复指引
2. **查询类 API 同样拒绝**：`impl_has` / `impl_has_override` / `impl_chain` 对非 Declaration 类报 TypeError
3. **回归锁**：
   - 查询 API 对非 Declaration 类一定抛 TypeError（而非 ValueError），防诊断分支被退化
   - qualname 不含 `.` 的 callable 仍报 `ValueError("Cannot determine class")`
   - **子类未桊、反推到 Declaration 基类是合法路径**，必须能被解析为 Declaration 以触发 `_DECLARATION_USER_HOOKS` 的 `refusing-to-register` 抦截——防止 fallback 被误删

所有用例集中于 `tests/test_impl_declaration_guard.py`。

## 消费者场景

| 消费者 | 场景 | 依赖的输出 | 验收标准 |
|--------|------|-----------|---------|
| mutgui 开发者 | 使用 `@impl(MenuTrigger.handle)` 后升级 mutobj | 抛 `TypeError` 而非静默错误 | 错误信息指明 MenuTrigger 不是 Declaration |
| mutobj 自身 | CI 运行测试 | 新测试用例通过 | `pytest` 全部通过 |
| mutbot 开发者 | 不会误用 `@impl` 到非 Declaration 类 | pyright 类型检查 + 运行时错误 | 不出现相关 bug |

## 实施步骤清单

- [x] 修改 `src/mutobj/core.py` 的 `_resolve_impl_key`：fallback 仅对 Declaration（含 Declaration 本身）放行，对非 Declaration 类抛出针对性 `TypeError`
- [x] 在 `tests/test_impl_declaration_guard.py` 新增 8 个测试用例（含反推到 Declaration 基类的回归锁）
- [x] 运行 `pytest` 全量回归 — 314 passed
- [x] 运行 `pyright src/mutobj` 类型检查 — 0 errors
- [x] 更新本文档状态为 ✅ 已完成

## 实施记录

> 上方设计方案章节已按变更后定稿，本节仅记录变更来由，供未来读者理解设计演进。

### 设计变更：fallback 从"删除"调整为"仅对 Declaration 放行"

初始方案 C 表述为"删除第 3 层 `__globals__` fallback"。实施中被现有测试 `test_impl_refuses_to_pollute_declaration_base` 揭出漏洞：

- 子类未声明 `__init__` 桊时，`Subcls.__init__` 实际是 `Declaration.__init__`，`__qualname__` 为 `"Declaration.__init__"`
- `Declaration` 本身不在 `_class_registry`（registry 只收子类），第 2 层无法命中
- 需要第 3 层 fallback 才能拿到 Declaration，交由 `impl()` 装饰器的 `_DECLARATION_USER_HOOKS` 检查抦截为 `ValueError("refusing to register on Declaration")`

以上是合法用法，不能一刀切。**精确设计意图**修订为：fallback 仅对 Declaration（含 Declaration 本身）放行，对非 Declaration 类报 TypeError。这同样呈现为“非 Declaration 不能走 fallback”，符合 spec 初衷。

### 局部类场景的诊断

测试文件中定义的本地类取不到 `__globals__` 中的同名入口（`__qualname__` 含 `<locals>`）。需从 qualname 解析出 simple name 作为错误信息展示名，保证诊断信息可读。

### pyright 作用域修正

原实现有两个连续的 `if target_cls is None:` 块，pyright 不推断条件等价性，认为 `class_name` 跨块未绑定。合并进同一块后解决。

## 范围外

- mutgui 侧 `EventHandler` 改为 Declaration 的整改 — 另开 SDD
- lint 工具检测 — 已有独立 SDD `feature-coding-standards-and-lint.md`
- `register_module_impls` — 当前是 no-op，无需守卫
