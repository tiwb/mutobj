# mutobj impl introspection 与 descriptor 元信息 API 设计规范

**状态**：🔄 实施中
**日期**：2026-04-30
**类型**：功能设计

## 需求

1. `Declaration` 子类的方法与字段在类级访问时不再完全遵循普通 Python class attribute 语义；上层项目需要稳定、可读、无字符串的 introspection API。
2. `mutgui` 当前通过 `type(action).execute is not Action.execute` 判断 action 是否可执行，这在 mutobj 的 delegate stub 机制下会误判。
3. `mutobj` 已有 `call_super_impl()`，但公开 API 前缀不统一；本次希望新增更明确的同义入口 `impl_call_super()`，并逐步收敛到 `impl_*` 家族。
4. 字段默认值查询不应要求调用方传字符串字段名；期望能直接从 descriptor 对象读取默认值元信息。

## 关键参考

- `src/mutobj/core.py` — `_impl_chain`、`AttributeDescriptor`、`_resolve_impl_key()`、`call_super_impl()` 的现有实现
- `src/mutobj/__init__.py` — 当前公开 API 导出列表
- `tests/test_impl_super.py` — `call_super_impl()` 现有行为测试
- `tests/test_defaults.py` / `tests/test_class_setattr.py` — `AttributeDescriptor` 与字段覆盖行为测试
- `mutgui/src/mutgui/action.py` — 当前 `can_execute` 误判路径
- `mutgui/tests/test_action.py` — action variant / menu 渲染回归测试
- `docs/specifications/feature-impl-super.md` — 现有 super 调用机制设计文档

## 设计方案

### impl 相关公开 API

本次新增 `impl_*` introspection API，统一表达“针对 @impl 链的查询”：

- `mutobj.impl_has(method) -> bool`
  - 问题语义：该声明方法当前是否有**真实可执行实现**
  - 返回 `False` 的典型场景：当前只剩显式 `NotImplementedError` 默认桩，或 delegate 最终仍回落到未实现基类

- `mutobj.impl_has_override(method) -> bool`
  - 问题语义：该声明方法当前是否有**超出默认链底的覆盖实现**
  - 典型用途：调试链结构、判断是否发生了模块级覆盖

- `mutobj.impl_chain(method) -> list[tuple[Callable[..., Any], str, int]]`
  - 返回该 method 对应的 `_impl_chain` 浅拷贝，供调试与高级框架逻辑使用

- `mutobj.impl_call_super(method, *args, **kwargs) -> Any`
  - 作为 `call_super_impl()` 的更统一别名
  - `call_super_impl()` 继续保留兼容，但进入 deprecate 轨道

### impl_has 与 impl_has_override 的区别

两者不是互斥同义词，而是不同层级：

| 场景 | `impl_has()` | `impl_has_override()` |
|------|--------------|-----------------------|
| 只有未实现默认桩 / delegate | `False` | `False` |
| 类体内直接写了默认实现 | `True` | `False` |
| 有 `@impl` 或 reload 后的新链顶覆盖 | `True` | `True` |

这组语义直接对应“能不能用”与“有没有覆盖”两个常见判断，比 `is_declared_only` 更易理解。

### descriptor 相关公开 API

不新增字符串风格 top-level 函数，而是直接在 `AttributeDescriptor` 上暴露元信息接口：

- `AttributeDescriptor.has_default`（已存在）
- `AttributeDescriptor.get_default() -> Any`
  - 返回声明上的默认值本身
  - 若字段来自 `default_factory`，返回 factory callable，而不是执行结果

- `AttributeDescriptor.make_default() -> Any`
  - 返回实例化时会应用的默认值
  - `default_factory` 存在时执行 factory
  - 普通 default 时直接返回该值

调用方可直接写：

```python
Action.order.has_default
Action.order.get_default()
Action.order.make_default()
```

不需要 `mutobj.get_default(Action, "order")` 这类字符串 API。

### 兼容策略

#### impl_call_super / call_super_impl

- 新代码与文档使用 `impl_call_super()`
- `call_super_impl()` 内部转调 `impl_call_super()`
- `call_super_impl()` 发 `DeprecationWarning`
- 本轮不移除旧名字，避免打断现有项目

#### 现有导出 API

- 旧 API 不重命名删除
- 新增 `impl_*` 家族作为推荐入口
- 后续若要做更统一的元信息入口，可在此基础上增加 `mutobj.meta(...)`，本轮不做

## 消费者场景

| 消费者 | 场景 | 依赖的输出 | 验收标准 |
|--------|------|-----------|---------|
| mutgui | 判断 `Action.execute` 是否真实实现 | `mutobj.impl_has(Action.execute)` | dropdown-only action 不再被误判为 split |
| mutobj 用户 | 在字段 descriptor 上读取默认值元信息 | `Action.order.get_default()` / `make_default()` | 不需要字符串字段名 |
| mutobj 用户 | 在 `@impl` 中调用上一级实现 | `mutobj.impl_call_super()` | 与 `call_super_impl()` 行为一致 |

## 实施步骤清单

- [x] 新增 `impl_has()` / `impl_has_override()` / `impl_chain()` 并导出到 `mutobj.__init__`
- [x] 新增 `impl_call_super()`，让 `call_super_impl()` 转调并发出弃用提示
- [x] 为 `AttributeDescriptor` 增加 `get_default()` / `make_default()`
- [x] 为 mutobj 补充 impl introspection、descriptor 元信息、别名兼容相关测试
- [x] 将 `mutgui` 的 execute 判断切换到 `mutobj.impl_has()` 并补充回归测试

## 设计备注

- `impl_has()` 的内部判断应基于 `_impl_chain` 的结构语义，而不是基于方法对象 identity；否则仍会被 delegate stub 误导。
- `impl_has_override()` 不等于“当前链长 > 1”，因为链中可能同时出现默认桩与类体内默认实现；实现时应明确区分 `__default__` 与其他来源模块。
- `AttributeDescriptor.get_default()` 与 `make_default()` 故意同时存在，避免把“声明的默认值元信息”和“实例默认值生产”混成一个 API。
- `impl_has()` 本轮不把 `...` / `pass` 形式的类体默认实现视为“未实现”；只有显式 `NotImplementedError` 与最终回落到未实现基类的 delegate 才返回 `False`。
