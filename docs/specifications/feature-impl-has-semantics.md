# `impl_*` API 重新设计 — 四个原子结构原语

**状态**：✅ 已完成
**日期**：2026-05-18
**类型**：功能设计

**相关文档**：
- [`feature-impl-meta.md`](feature-impl-meta.md) — `@impl` 附加元数据机制（用于本文不能解决的语义层问题，如「这个 impl 是占位 stub 还是真实现」）

## 硬约束（不可违反）

本设计反复被绕回老路，先把红线钉死：

- **禁止 AST 扫描**：不允许在框架任何位置通过 `ast.parse` / `ast.NodeVisitor` 等手段读用户函数的源码 AST 来推断函数体。
- **禁止 opcode / 字节码判断**：不允许通过 `dis.get_instructions`、`func.__code__.co_code` 等读用户函数的字节码来推断函数体形态（无论是判断 `...`、`pass`、`raise NotImplementedError` 还是别的模式）。

这两条覆盖所有阶段（metaclass `__new__`、`@impl` 注册、运行时查询）和所有目的（判 stub、判默认实现、判 NotImplementedError 等）。任何方案如果隐含"扫一下函数体就能知道"，都已经出局，不要再回头。

替代手段限定为：**显式标记**（`__mutobj_is_stub__` 等属性）、**结构事实**（`__dict__`、`_impl_chain` 内容）、**显式哨兵 / 装饰器**（用户主动声明）。

## 需求

1. 当前 `impl_has(method)` 试图通过 `_looks_like_notimplemented_stub()` 字节码扫描来判断函数体是不是 `raise NotImplementedError`——违反上面的硬约束，必须删除。
2. 实际影响：mutgui `Action.execute` 被迫用 `raise NotImplementedError` workaround 来控制 `impl_has` 返回值，lint 报 R001，风格不统一。
3. 在不扫函数体的前提下，框架无法区分 `def f(): ...` 和 `def f(): return 42`——它们在 metaclass 眼里完全相同。这是物理边界，不是缺陷。
4. 因此需要重新设计语义：要么把语义压缩到结构能回答的范围内（spec 当前方向），要么引入显式标记让用户自己表达 stub 意图。

## 关键参考

- `src/mutobj/core.py:1325` — `impl_has()` 当前实现（待删）
- `src/mutobj/core.py:1337` — `impl_has_override()` 当前实现（保留）
- `src/mutobj/core.py:1286` — `_looks_like_notimplemented_stub()` 字节码扫描（待删）
- `src/mutobj/core.py:1296` — `_default_impl_has_behavior()` 多层判断（待删）
- `src/mutobj/core.py:786` — metaclass 普通方法处理：用户类体 `def` → chain[0]，`source_module="__default__"`
- `src/mutobj/core.py:800-820` — metaclass 继承委派创建：framework delegate → chain[0]，带 `__mutobj_is_delegate__`
- `src/mutobj/core.py:145` — `_make_stub_method` 仅用于 `_restore_stub` setattr，**不进 `_impl_chain`**
- `mutgui/src/mutgui/action.py:113` — `Action.execute` 的 `raise NotImplementedError` workaround（待移除）
- `mutgui/src/mutgui/_action_registry.py:224` — variant 推断依赖 `impl_has`（待迁移到 meta 方案）
- `mutgui/demo/examples/action.py:241-289` — 实证：子类类体直接 `def execute` 是主流写法
- `mutgui/src/mutgui/_action_impl.py` — 实证：框架级默认行为用 `@impl`

## 设计方案

### 核心洞察：框架只能回答结构问题，不能猜函数体；且不该替 consumer 拍板

硬约束下，关于一个 method，框架能 **100% 准确回答**的结构事实只有这 7 条：

| # | 问题 | 数据源 |
|---|---|---|
| 1 | 这个 method 在 mutobj registry 里有没有 chain | `(cls, key) in _impl_chain` |
| 2 | chain 长什么样 | `_impl_chain[(cls, key)]` |
| 3 | 链上有没有任何 `@impl` 注册项 | `any(mod != "__default__" ...)` |
| 4 | chain[0] 是用户类体 def 还是框架 delegate | `__mutobj_is_delegate__` 标记 |
| 5 | 链顶（活跃实现）是哪一项 | `chain[-1]` |
| 6 | method 归属哪个 mutobj 类 | `func.__mutobj_class__` |
| 7 | MRO 上哪些父类声明过同名 method | 遍历 `_DECLARED_METHODS` |

框架**永远回答不了**的：函数体内容、用户的语义意图（「我这个 def 是 stub 还是实现」）。

所有需要语义判断的问题（典型如 mutgui 的「这个 execute 算不算实现」），都**不属于本设计的解决范围**，由 [`feature-impl-meta.md`](feature-impl-meta.md) 通过显式 meta 标记机制承接。

### chain[0] 的形态穷举

确认 metaclass 行为后，普通方法的 chain[0] 只有两种形态：

| chain[0] 函数对象 | source_module | 标记 | 含义 |
|---|---|---|---|
| 用户在类体写的 `def f` | `"__default__"` | `__mutobj_class__` | 类自己声明 |
| 框架生成的 delegate | `"__default__"` | `__mutobj_is_delegate__ = True` | 从父类继承 |

`@impl` 注册会 append 到链顶（chain[-1]），不改变 chain[0]。`_make_stub_method` 只用于 `_restore_stub` setattr，**不进 chain**。

### 最终 API 设计：4 个原子原语

每个 API 回答一个原子结构问题，**不做任何语义复合**，互相正交。

```python
# === 基础设施（已有，保留）===
impl(target)                      # 注册装饰器
impl_call_super(method, *args)    # 链式 super 调用
impl_chain(method)                # 返回完整 chain 拷贝（结构事实 #2）

# === 显式注册查询（已有，保留）===
def impl_has_override(method) -> bool:
    """链上有任何 @impl 注册项（结构事实 #3）"""
    cls, key = _resolve_impl_key(method)
    chain = _impl_chain.get((cls, key), [])
    return any(mod != "__default__" for _, mod, _ in chain)

# === 新增两个结构原语 ===
def impl_is_own(method) -> bool:
    """chain[0] 是该类在自己类体里写的 def（结构事实 #4 的正面）

    True 意味着：这个 method 在当前 cls 的 chain 底层，是用户函数。
    False 意味着：chain[0] 是 framework delegate，或根本没有 chain。
    """
    cls, key = _resolve_impl_key(method)
    chain = _impl_chain.get((cls, key), [])
    if not chain:
        return False
    return not getattr(chain[0][0], "__mutobj_is_delegate__", False)

def impl_is_inherited(method) -> bool:
    """chain[0] 是 framework 生成的继承委派（结构事实 #4 的反面）

    True 意味着：当前 cls 自己没在类体写这个 method，框架自动
    生成 delegate 转发到父类的实现。
    """
    cls, key = _resolve_impl_key(method)
    chain = _impl_chain.get((cls, key), [])
    if not chain:
        return False
    return bool(getattr(chain[0][0], "__mutobj_is_delegate__", False))
```

`impl_is_own` 和 `impl_is_inherited` 互斥（chain 存在时），命名采用 `own / inherited` 对仗，借鉴 JS `Object.hasOwn` 的「自家的」直觉。

### 各场景下 4 个 API 的返回值

| 场景 | `impl_chain` | `impl_has_override` | `impl_is_own` | `impl_is_inherited` |
|---|---|:---:|:---:|:---:|
| `Action` 基类，类体 `def execute: ...` | 1 项（用户 def） | False | True | False |
| `SaveAction(Action)` 类体 `def execute: do_save()` | 1 项（用户 def） | False | True | False |
| `MenuOnly(Action): pass`（不写 execute） | 1 项（delegate） | False | False | True |
| `Foo(Action)` + `@impl(Foo.execute)` | 2 项（delegate + impl） | True | False | True |
| `Action.check_visible`（类体 `...` + 框架 `@impl`） | 2 项（用户 def + impl） | True | True | False |

**关键观察**：`Action`（基类桩）和 `SaveAction`（子类实现）在 4 个 API 下输出**完全一样**——这是结构上不可分辨。要区分这两者必须靠语义层信号（meta 标记），不属于本文范围。

### 旧 API 归并

| API | 处理 | 理由 |
|---|---|---|
| `impl_has(method)` | **删除** | 名字隐含「有没有真实实现」是语义判断，硬约束下框架无法准确回答。不同 consumer 对「真实实现」心智不同（仅认 @impl / 认类体 def / 认任何 chain），保留 `impl_has` 必然替某一种 consumer 拍错板 |
| `impl_has_override` | 保留 | 语义清晰、结构准确 |
| `impl_chain` | 保留 | 基础设施 |
| `impl` / `impl_call_super` / `call_super_impl` | 保留 | 不在本设计范围 |

**删除的私有函数**（违反硬约束的字节码 hack）：

- `_default_impl_has_behavior`
- `_looks_like_notimplemented_stub`
- `_meaningful_instructions`

### Consumer 如何用这套 API

```python
# 反射场景：「这个 method 实际会跑哪段代码？」
active = impl_chain(Foo.bar)[-1][0]  # 链顶函数

# 「子类有没有重写父类的 method？」
# 当前 cls 是子类时：
impl_is_own(Sub.bar)  # True 意味着 Sub 自己写了 def 或被 @impl 替换

# 「有没有人为这个 method 注册过 @impl」
impl_has_override(Foo.bar)

# 「这个 method 是不是基类桩，没人提供实现」
# 答：本文 API 回答不了；这是语义问题，用 meta 方案
```

### mutgui Action.execute 的处理

mutgui 想区分「`Action.execute` 是基类桩」vs「`SaveAction.execute` 是子类实现」，但两者在 4 个 API 下输出完全相同。**本文设计明确不解决这个场景**，迁移到 [`feature-impl-meta.md`](feature-impl-meta.md)：

- `Action` 类体改回 `def execute(self, context): ...`（不再 `raise NotImplementedError`）
- 在 `_action_impl.py` 用 `@impl(Action.execute, meta={...})` 注册一个带 stub 标记的占位实现
- `_action_registry.py` 用 `mutobj.impl_meta(...)` 读 meta 判定

具体 meta API 形态在 [`feature-impl-meta.md`](feature-impl-meta.md) 里设计。meta spec 已落地，mutgui 完成迁移：

- `_action_impl.py` 注册 ``@impl(Action.execute, Stub())`` 占位
- `action.py` 类体改回 ``def execute: ...``，移除 ``raise NotImplementedError`` workaround
- `_action_registry.py` 改用 ``mutobj.impl_meta_of(type(action).execute, Stub) is None`` 判定

## 已否决方案（死路记录，防止反复绕回）

### 死路 1：opcode / AST 扫描识别 `...` / `raise NotImplementedError`

**否决原因**：违反本文顶部「硬约束」。当前 `_looks_like_notimplemented_stub` 就是这条路，中途必需删除。不论是扫 `LOAD_CONST Ellipsis` 还是扫 `RAISE_VARARGS NotImplementedError`，一律禁止。

### 死路 2：强制所有实现走 `@impl`（`impl_has ≡ impl_has_override`）

**诱人之处**：看上去贴合 mutobj「Declaration-Implementation 分离」哲学，删代码最多，`impl_has` 退化为 `impl_has_override` 别名，mutgui consumer 零改动。

**实证证据**：`mutgui/demo/examples/action.py:241-289` 里 `SaveAction` / `RunAction` / `CheckAction` / `PublishAction` 全都是子类类体直接 `def execute(self, context)`，不走 `@impl`。对比 `mutgui/src/mutgui/_action_impl.py`：框架级默认行为（check_visible / resolved_label 等）才用 `@impl`。这说明 mutobj 生态里「类体直接实现」与「@impl 实现」是**两种同等公民的主流写法**，不是边角用法。

**否决原因**：

- 强制走 `@impl` 后，每个用户 Action 子类被迫拆成两段写法，类与实现被人为划散，与「一个 Action 一个类」的直觉冲突。
- demo 里起码 4–5 个 Action 要重写，生态里所有 mutgui Action 用户代码都要跟进。
- 这不是「贴近哲学」，是**改写哲学去迁就现状代码**。mutobj 哲学原本就并不排斥子类类体直接实现；它排斥的是「下层不能依赖上层」，而不是「不能在类体写函数」。

**后续方案不要倒退到「只认 `@impl` 为实现」这个起点。**任何可行设计必须同时能表达：子类类体直接 `def execute: do_save()` 也是「有实现」。

### 死路 3（预防性记录）：要求用户把函数体改成特定写法来供框架识别

例如要求「必须写 `raise NotImplementedError`」「必须写 `...`」「必须写 `pass`」。**均否决**——框架不看函数体，就不要要求用户以特定写法挑逗框架。区分意图必须靠**函数体以外的信号**（哨兵、装饰器、类属性结构、MRO 位置等）。

## 设计方案演进（历史，已废弃）

本设计早期使用三原语 `impl_is_declared` / `impl_has_override` / `impl_is_inherited`，`impl_is_declared` 基于 `key in cls.__dict__` 判断。后续发现两个问题：

1. **数据源不一致**：`impl_is_declared` 查 `__dict__`，其他原语查 `_impl_chain`。`@impl` 用 `setattr` 替换 `cls.__dict__[key]`，导致 `impl_is_declared` 在 @impl 后返回 False 这种反直觉行为（被列为 Q2 待定问题）。
2. **mutgui 组合公式有 bug**：文档当时建议 `impl_is_declared(t) or impl_has_override(t)` 来判断 execute 是否被实现，但基类 `Action.execute` 自己也满足 `impl_is_declared`，导致 `Action()` 直接实例化被误判为「有实现」。

**修订**：把判断基准统一到 `_impl_chain` 的 chain[0]，`impl_is_declared` 改名为 `impl_is_own`。同时承认「basis 类桩 vs 子类实现」在结构上不可分辨，从本文范围中剥离，交给 meta 方案。

## 待定问题

（暂无）

## 实施步骤清单

- [x] 扫描生态中所有 `impl_has(` 调用点，形成迁移表（mutobj/mutagent/mutbot/mutgui/tests）
  - mutobj/src/mutobj/__init__.py、core.py（自身定义 / 导出）
  - mutobj/tests/test_introspection_api.py（翻转预期）
  - mutobj/tests/test_impl_declaration_guard.py（仅验证 TypeError，保留）
  - mutgui/src/mutgui/_action_registry.py:224（按 spec 暂留，等 meta 落地）
  - mutagent / mutbot：无调用
- [x] 新增 `impl_is_own(method)` 与 `impl_is_inherited(method)`
- [x] 标记 `impl_has` 为 `DeprecationWarning`，一个版本后删除
- [x] 删除 `_looks_like_notimplemented_stub` / `_meaningful_instructions` / `_default_impl_has_behavior`
- [x] 检查 `impl_call_super` 是否依赖被删的字节码扫描，必要时调整
  - 已移除 `_default_impl_has_behavior` 调用；super 到链底默认项时直接调用，用户函数自身决定是否抛 NotImplementedError
- [x] 更新 `test_introspection_api.py`：
  - 已翻转 `test_ellipsis_body_*`、`test_pass_body_*`、`test_real_default_body_*`、`test_inherited_delegate_from_real_base_*` 的期望
  - 已新增 `TestImplIsOwnAndInherited` 类覆盖主要 own/inherited 场景
  - 额外修复：`test_impl_super.py::test_super_at_chain_bottom_raises` 取消 "No super implementation" match（不再由框架报，由用户函数本身抛）
- [x] 更新 mutobj 公开 API 文档（`__all__`、docs/api/reference.md）
- [x] mutgui：`_action_registry.py` 的 `impl_has` 调用已迁移到 `mutobj.impl_meta_of(type(action).execute, Stub) is None`（meta spec 落地后完成）
- [x] 全量测试 + lint
  - mutobj pytest: 381 passed
  - mutobj pyright src/mutobj/core.py + __init__.py: 0 errors
  - mutgui / mutagent / mutbot import OK
  - 已消除：mutgui `Action.execute` 的 workaround 已通过 `@impl(Action.execute, Stub())` + `impl_meta_of` 机制解决，`SaveAction` 等子类类体实现不再被误判
