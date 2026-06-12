# `@impl` 附加元数据机制

**状态**：✅ 已完成
**日期**：2026-05-18
**类型**：功能设计

**相关文档**：
- [`feature-impl-has-semantics.md`](feature-impl-has-semantics.md) — `impl_*` 系列结构原语重设计（本文的前置上下文）

## 需求

### 起源

`feature-impl-has-semantics.md` 的最终设计明确：mutobj 框架在硬约束下（禁 AST、禁 opcode）能 100% 回答的全部是结构事实。涉及「这个 impl 在语义上是什么角色」的判断（典型如「这是个占位 stub 还是真实现」），结构上无法表达——基类的桩声明 `def execute: ...` 和子类的类体实现 `def execute: do_save()` 在 chain 视角下完全同形。

承认这是物理边界后，正确做法是让 consumer **显式标注**这种语义信息，而不是让框架去猜。最自然的标注位置是 `@impl` 装饰器——因为：

1. `@impl` 是 mutobj 唯一显式的实现注册点
2. 已经有装饰器入口，附加 kwarg 改动最小
3. consumer 已经习惯在 `@impl` 附近表达"这是给谁注册的实现"

### 具体待解决问题

1. **mutgui Action.execute 区分 stub vs 实现**
   - `Action.execute` 是基类桩，没有合理的默认行为，variant 推断需要知道「这是 stub」
   - `SaveAction` 等子类的类体 `def execute: do_save()` 是真实现
   - 当前用 `raise NotImplementedError` workaround + 字节码扫描 hack 实现，违反硬约束需要拆掉

2. **生态里其他可能用例**（暂未实证，调研中）
   - `deprecated` 标注：某个 impl 已废弃
   - `since` / `version` 信息
   - feature flag 标记
   - consumer 自定义反射元数据

### 用户偏好

用户明确表示**不喜欢之前在 `feature-impl-has-semantics.md` 讨论中草拟的 API 形态**（`meta={"key": value}` dict 参数）。需要重新设计更合适的形态。

之前讨论过但被否决的雏形（仅作历史记录）：

```python
# 形态 1（用户不喜欢）：dict kwarg
@impl(Action.execute, meta={"mutgui.is_stub": True})

# 形态 2（用户不喜欢）：扁平 kwarg
@impl(Action.execute, is_stub=True, since="0.7")

# 形态 3（用户不喜欢）：独立装饰器
@impl(Action.execute)
@impl_meta(is_stub=True)
```

否决原因待用户进一步说明，本文设计阶段需要重新探索。

## 关键参考

- [`feature-impl-has-semantics.md`](feature-impl-has-semantics.md) — 前置 spec，定义了为什么需要 meta 机制
- `src/mutobj/core.py` `impl` 装饰器定义（具体行号待查）
- `mutgui/src/mutgui/action.py:113` — Action.execute 当前 workaround
- `mutgui/src/mutgui/_action_registry.py:224` — variant 推断 consumer 点
- `mutgui/src/mutgui/_action_impl.py` — @impl 注册集中地，meta 标注最可能落在这里

## 设计方案

本节为 YAGNI 第一版设计——只覆盖当前唯一真实需求（mutgui `Action.execute` 区分 stub vs 实现），其余可能性（声明侧 meta、chain 累积、按 chain_index 查询、native 化序列化等）一律留到第二个 consumer 出现再扩展。

### 核心决策

1. **meta = 任意 Python 对象**——mutobj 不强制基类，consumer 用 `class Stub: pass` / dataclass / 未来用 Declaration 都行（YAGNI；现在只有 `Stub` 一个真实需求，强制基类是过度设计；未来若进入 native 化管道，可统一升级到 Declaration 子类，本版设计不挡这条路）。
2. **meta 通过 `@impl` 的位置参数传入**——避开了 `meta={...}` dict kwarg / 扁平 kwarg / 双装饰器三种被否决形态。
3. **两个查询函数封顶**——`impl_meta()` 拿全部，`impl_meta_of()` 按类型取一个，不引入更多函数。
4. **只看链顶语义**——`chain[-1]` 的 meta，不沿 chain 累积、不沿 MRO 累积。
5. **delegate 透明转发**——当 `chain[-1]` 是 framework 生成的继承委派时，递归到被委派类的 chain 链顶取 meta（不做这层透明，consumer 第一次用就踩坑）。
6. **meta 不进 `impl_chain()` 返回值**——保持 `impl_chain` 元组形状不变，避免破坏既有 consumer；meta 走旁路存储。
7. **不做声明侧 meta**——「Action.execute 是 stub」在本版仍走「注册一个 `Stub` 标记的占位 @impl」的形态，Action 类体维持 `def execute(self, context): ...`。第二个用例出现且确实需要声明侧表达时，再扩展为「声明侧 + 实现侧」双层。

### 注册 API

```python
@impl(target)                                  # 无 meta，行为不变
@impl(target, Stub())                          # 单个 meta
@impl(target, Stub(), Deprecated(since="0.8")) # 多个 meta
```

- `@impl` 签名扩为 `impl(target, *metas)`
- meta 对象按传入顺序保存为 tuple，consumer 自行决定顺序语义（一般无关）

### 查询 API

```python
mutobj.impl_meta(method) -> tuple[object, ...]
    """返回该 method 当前链顶 impl 的全部 meta；无 meta 返回 ()。
    若链顶是 framework delegate，透明递归到被委派类的链顶。"""

mutobj.impl_meta_of(method, meta_type) -> meta_type | None
    """返回链顶 impl 上第一个 isinstance(_, meta_type) 的 meta；找不到返回 None。
    delegate 转发规则同上。"""
```

两个函数都基于 `_resolve_impl_key` 走 mutobj 标准的 method → (cls, key) 路径，与 `impl_chain` / `impl_is_own` 等既有 API 行为一致。

### 存储设计

旁路一个独立 dict，键为 chain 条目的稳定 id：

```python
_impl_metas: dict[tuple[type, str, int], tuple[object, ...]] = {}
# 键：(target_cls, impl_key, seq)   ——复用 _impl_chain 已有的 seq 序号
# 值：注册时传入的 meta tuple
```

- `_register_to_chain` 增加 meta 参数，注册时写入 `_impl_metas`
- `unregister_module_impls` 同步清理对应条目
- `_impl_chain` 元组形状 `(func, source_module, seq)` 完全不变

### delegate 透明转发

查询时若 `chain[-1][0]` 带有 `__mutobj_is_delegate__` 标记，则沿被委派类的方向递归（delegate 函数对象上已记录指向的父类，逻辑参考 `core.py:800-820` 周边的 delegate 创建处）。递归只走一层 chain 链顶——不需要遍历完整 MRO，因为 delegate 自身已表达了继承链。

### 不做（明确 YAGNI）

以下项一律推迟到第二个真实 consumer 出现时再讨论，不写进本版：

- `ImplMeta` 基类、`@mutobj.stub` 语法糖、声明侧 `@declare_meta` 装饰器
- chain 上 meta 的累积/继承规则（按类型决定聚合策略）
- 按 `chain_index` 查询某一层的 meta
- meta 类型的 `discover_subclasses` 支持
- meta 进入 native 化 / 序列化管道
- 把 meta 一并塞进 `impl_chain()` 返回值

## 消费者场景

| 消费者 | 场景 | 依赖的输出 | 验收标准 |
|--------|------|-----------|---------|
| mutgui `_action_impl.py` | 注册一个标记为 stub 的占位 execute 实现 | `@impl(Action.execute, Stub())` 注册成功，meta 可读 | 占位实现被调用时抛 `NotImplementedError`，`mutobj.impl_meta_of(Action.execute, Stub)` 返回 `Stub()` 实例 |
| mutgui `_action_registry.py` variant 推断 | 区分基类 stub vs 子类真实现 | `mutobj.impl_meta_of(type(action).execute, Stub) is not None` | `Action`/`MenuOnly(Action): pass` 判定为 stub；`SaveAction(Action)` 类体 `def execute: do_save()` 判定为非 stub；dropdown-only action 不再被误判为 split 按钮 |
| mutgui `action.py:113` workaround 移除 | `Action.execute` 不再需要 `raise NotImplementedError` 占位 | 类体维持 `def execute(self, context): ...` | mutobj lint R001 不再报警；语义由 meta 承载 |

mutgui 侧迁移示例：

```python
# mutgui/_action_impl.py
class Stub:
    """标记某个 @impl 注册为占位 stub，子类必须 override。"""

@impl(Action.execute, Stub())
def _execute_stub(self, context):
    raise NotImplementedError(
        f"{type(self).__name__}.execute is not implemented"
    )

# mutgui/_action_registry.py（variant 推断点）
cls_execute = type(action).execute
is_stub = mutobj.impl_meta_of(cls_execute, Stub) is not None
```

- `Stub` 类放在 mutgui 侧（YAGNI；mutobj 不提供基类、不提供具体 marker 类型，避免框架替 consumer 起名字）
- `SaveAction` 等子类类体直接 `def execute` 写法不变，其自身 chain 链顶是用户 def、未挂 `Stub` meta，`impl_meta_of(..., Stub)` 自然返回 `None`
- `MenuOnly(Action): pass` 不写 execute 时，自身链顶是 delegate，透明转发到 `Action.execute` 的链顶（带 `Stub` 标记的占位），正确判定为 stub

## 实施步骤清单

拆为两部分：mutobj 本轮完成，mutgui 作为下游 consumer 由用户后续单独实施。

### mutobj（本轮实施）

- [x] 扩展 `impl()` 装饰器签名接受 `*metas: object`，向下透传到 `_register_to_chain`；无 meta 调用零行为变化
- [x] 新增旁路存储 `_impl_metas: dict[(type, str, int), tuple[object, ...]]`，在 `_register_to_chain` 三个分支（同模块覆盖 / 卸载后重注册 / 全新）正确写入；空 meta 不占条目
- [x] `unregister_module_impls` 同步清理 `_impl_metas` 对应条目
- [x] 实现 `impl_meta(method) -> tuple[object, ...]` 与 `impl_meta_of(method, meta_type) -> meta_type | None`；读 `chain[-1]` 的 seq 索引 `_impl_metas`；链顶为 delegate 时透明递归到 `__mutobj_delegate_base__` 的链顶
- [x] `__init__.py` 导出两个新 API + `__all__` 补充 + `docs/api/reference.md` 增加条目
- [x] 新增 `tests/test_impl_meta.py` 覆盖：零/一/多 meta 注册、tuple 返回、类型过滤、同模块覆盖后 meta 替换、unregister 后 meta 清空、delegate 透明转发的最小复现、非 mutobj method 或无 chain 返回空
- [x] 全量回归：`pytest`（399 用例全过，现有 381 用例不退化）+ `pyright src/mutobj`（0 errors）

### mutgui（下游实施，本轮完成）

- [x] mutgui `_action_impl.py` 新增 `class Stub: pass` 与 `@impl(Action.execute, Stub())` 占位实现（体内抛 `NotImplementedError`，错误信息带类名）
- [x] mutgui `action.py:113` 移除 `raise NotImplementedError` workaround，`Action.execute` 类体改回 `def execute(self, context): ...`，确认 mutobj lint R001 不再报警
- [x] mutgui `_action_registry.py:224` 切换 stub 判定为 `mutobj.impl_meta_of(type(action).execute, Stub) is not None`，删除相关旧导入
- [x] mutgui 回归测试：`pytest`（246 用例全过）
- [x] 回标 `feature-impl-has-semantics.md` 里「mutgui workaround 仍然存在」的遺留备注为已消除
