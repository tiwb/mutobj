# @impl super 调用机制 设计规范

**状态**：📝 设计中
**日期**：2026-03-04
**类型**：功能设计

## 背景

当前 `@impl` 覆盖机制支持后注册覆盖先注册——上层项目（mutbot）可以覆盖下层（mutagent）的实现。但覆盖后无法调用被覆盖的实现（"上级实现"）。

实际场景：mutbot 覆盖 mutagent 的 `JinaSearchImpl.search`，在原始实现的基础上附加错误处理。当前做法是直接 import 原始函数：

```python
from mutagent.builtins.web_jina import _jina_search as _base_search

@mutagent.impl(JinaSearchImpl.search)
async def _jina_search(self, query, max_results=5):
    try:
        return await _base_search(self, query, max_results)
    except RuntimeError as e:
        raise _enrich_error(e) from e
```

问题：
1. **依赖内部名称** — 需要知道原始函数的模块路径和函数名（`_jina_search`），这是实现细节
2. **脆弱** — 原始函数重命名或移动后，上层代码静默失败
3. **无法链式覆盖** — 如果有三层覆盖（A → B → C），B 调用 A 需要 import A 的函数，C 调用 B 需要 import B 的函数，无法自然地"调用上一级"

期望的 API（类似 Python `super()`）：

```python
@mutagent.impl(JinaSearchImpl.search)
async def _jina_search(self, query, max_results=5):
    try:
        return await mutagent.super_impl(JinaSearchImpl.search)(self, query, max_results)
    except RuntimeError as e:
        raise _enrich_error(e) from e
```

## 现状分析

### _impl_chain 结构

```python
_impl_chain: dict[tuple[type, str], list[tuple[Callable, str, int]]]
#                  (类, 方法名)           [(实现函数, 来源模块, 注册序号), ...]
```

- 按 `seq`（注册序号）排序，尾部 = 当前活跃实现
- 同模块重复注册时复用原序号（保持链中位置）
- `_register_to_chain()` 管理注册逻辑

### 方法分发

Declaration 子类的桩方法通过 `__init_subclass__` 被替换为 dispatcher：

```python
def dispatcher(self, *args, **kwargs):
    chain = _impl_chain.get((cls, method_name), [])
    if chain:
        return chain[-1][0](self, *args, **kwargs)  # 调用链顶
    raise NotImplementedError(...)
```

### 关键约束

- `_impl_chain` 是模块级全局变量
- 链条在运行时可变（`unregister_module_impls` + reimport）
- 需要线程安全考虑（虽然当前无并发写入）

## 设计方案

### QUEST Q1: API 形式
**问题**：super 调用的 API 怎么设计？
**建议**：`mutobj.super_impl(method)` 返回上级实现函数，调用者自行传参。理由：
- 与 `@mutobj.impl(method)` 对称
- 不依赖栈帧魔法（`super()` 的 `__class__` cell 机制不可复用）
- 显式优于隐式

```python
# 用法
result = await mutobj.super_impl(JinaSearchImpl.search)(self, query, max_results)
```

实现思路：根据调用者的模块名在 `_impl_chain` 中定位当前位置，返回前一个条目的函数。

### QUEST Q2: 调用者定位机制
**问题**：`super_impl` 如何知道"当前是哪个实现在调用"？需要这个信息才能找到"上一级"。
**建议**：两种方式：
1. **栈帧检查** — `inspect.stack()` 或 `sys._getframe()` 获取调用者的 `__module__`，在链中查找
2. **显式传入** — `mutobj.super_impl(method, caller=_jina_search)` 或 `mutobj.super_impl(method, module=__name__)`

建议用 `sys._getframe(1).f_globals['__name__']`（零成本，不需要调用者额外传参），fallback 到显式传入。

### QUEST Q3: 链为空或无上级时的行为
**问题**：如果当前实现就是链底（没有上级），`super_impl` 应该怎么处理？
**建议**：raise `NotImplementedError("No super implementation for ...")`。与桩方法未实现时的行为一致。

## 关键参考

### 源码
- `mutobj/src/mutobj/core.py:21` — `_impl_chain` 定义
- `mutobj/src/mutobj/core.py:196` — `_register_to_chain()` 注册逻辑
- `mutobj/src/mutobj/core.py:700` — `impl()` 装饰器
- `mutobj/src/mutobj/core.py:538` — dispatcher 生成（`__init_subclass__`）
- `mutbot/src/mutbot/builtins/web_jina_ext.py` — 当前 workaround（直接 import 原始函数）
