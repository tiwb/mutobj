# @impl super 调用机制 设计规范

**状态**：✅ 已完成
**日期**：2026-03-04（更新 2026-04-25）
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

## 现状分析

### _impl_chain 结构

```python
_impl_chain: dict[tuple[type, str], list[tuple[Callable, str, int]]]
#                  (类, 方法名)           [(实现函数, 来源模块, 注册序号), ...]
```

- 按 `seq`（注册序号）排序，尾部 = 当前活跃实现
- 同模块重复注册时复用原序号（保持链中位置）
- **隐式约束：一个模块对同一 `(cls, key)` 至多一条记录**——`_register_to_chain` 用 `existing_idx` 检查，同模块第二次注册会**静默替换**前一条，不会在链中并存

### 方法分发

注册时（`_register_to_chain` 返回 `became_top=True`），`impl()` 装饰器调用 `_apply_impl(cls, impl_key, func)` 直接把链顶函数装到类上（普通方法用 `setattr`、property 用 `prop._fget/_fset`）。卸载活跃实现时（`unregister_module_impls`）反向操作：链顶变化则 `_apply_impl` 装新顶，链空则 `_restore_stub` 恢复原桩。

调用时不再有运行时 dispatcher——类上挂的就是当前链顶函数本身，调用开销与普通方法一致。这意味着"调用上一级"必须由 super 调用 API 在被调函数内部主动查 `_impl_chain` 找前一个条目，而不能依赖一个统一的 dispatcher 入口。

## 设计方案

### 期望的 API

类似 Python `super()`，但显式传递 method 句柄：

```python
@mutagent.impl(JinaSearchImpl.search)
async def _jina_search(self, query, max_results=5):
    try:
        return await mutobj.call_super_impl(
            JinaSearchImpl.search, self, query, max_results
        )
    except RuntimeError as e:
        raise _enrich_error(e) from e
```

- 函数名 `call_super_impl`：`call`（直接调用）+ `super`（向链上一级）+ `impl`（限定为 @impl 链，避免与 Python 继承的 `super()` 混淆）
- 与 `@impl` 在同一术语体系内，对老用户友好
- 用户**不需要**额外传 `__name__` 或自身函数引用

### Q1: 调用者定位机制

**问题**：`call_super_impl` 如何知道"当前是哪个实现在调用"？

**方案**：`sys._getframe(1).f_globals["__name__"]` 自动取得调用方模块名，到 `_impl_chain` 里匹配。

**为什么用 frame 而不是让用户传 `__name__`**：

- chain 里存的 `source_module` 来自 `func.__module__`，而 `func.__module__` 在函数定义时由所在模块的 `__name__` 赋值
- 函数体内读到的 `__name__` 与 chain 里存的 `source_module` **完全同源**，所有边缘场景（`__main__`、`exec(code, globals)`、Jupyter REPL 等）下两者都一致
- 让框架抄一次，比让每个 impl 都手抄 `__name__` 更省事且不易出错
- `sys._getframe` 是 CPython 官方 API，PyPy 也支持，标准库 `logging` / `dataclasses` / `warnings` 等广泛使用
- 性能：单次调用约 100ns，且**只在 `call_super_impl` 被调时才付出**——正常方法分发完全不受影响

**为什么不用 ContextVar / wrapper 方案**：需要给 chain 里每个条目包一层 wrapper 维护"当前 super 是谁"的状态，每次方法调用都增加 wrapper + dict copy + ContextVar set/reset 开销，且 mutobj 现有的"链顶函数直接挂在类上"模型要重写。复杂度和运行时开销都远高于 frame 方案，无明显收益。

### Q2: 函数同名问题

**问题**：如果链中不同模块的 impl 函数恰好同名（如都叫 `_jina_search`），会不会混乱？

**答**：完全无影响。定位逻辑只比对 `source_module` 字符串，不涉及函数名（`func.__name__` / `__qualname__`）。chain 中两条记录的 module 字符串必然不同（同模块同 key 会被静默替换为单条），故定位无歧义。

**报错信息约定**：错误消息中应使用 module 名而非函数名定位，因为函数名同名时无信息量。

### Q3: 链空或 caller 不在链中的行为

- **caller 是链底**（idx == 0，没有上级）→ `NotImplementedError`，消息中带上 caller 模块名，方便排查链结构
- **caller 不在链中**（如从测试或非 @impl 上下文里调用）→ `RuntimeError`，提示该 API 必须在 @impl 函数内调用

### Q4: 是否提供 escape hatch

第一版**不提供**显式传 caller module 的参数。如果未来真有从测试或 helper 函数调用 super 的需求，再以可选关键字参数形式叠加（向后兼容），不破坏当前 API：

```python
# 假想的未来扩展（YAGNI，第一版不做）
def call_super_impl(method, *args, _caller_module=None, **kwargs): ...
```

### Q5: property / classmethod / staticmethod 支持

`call_super_impl(JinaSearchImpl.search, ...)` 对普通方法直接可用。对其他形式：

- **property getter/setter**：复用 `@impl` 装饰器内已有的 method → `(cls, impl_key)` 解析逻辑（impl_key 形如 `"prop_name.getter"` / `"prop_name.setter"`），抽取为内部函数 `_resolve_impl_key(method)`，`@impl` 和 `call_super_impl` 共用
- **classmethod**：`Cls.cm` 拿到的是 bound method，`_resolve_impl_key` 需处理 `__func__`
- **staticmethod**：通过 `_DECLARED_STATICMETHODS` 标记识别

实现时优先保证普通方法路径，property/classmethod/staticmethod 在第一版同步支持但需补充测试。

## 最终 API

```python
def call_super_impl(method, *args, **kwargs):
    """调用 @impl 链中当前实现的上一级实现

    必须从 @impl 函数体内调用。框架自动通过调用栈定位当前实现，
    返回链中前一条记录的执行结果。

    Raises:
        NotImplementedError: 当前实现已是链底，无上级可调
        RuntimeError: 调用者不在该 method 的 @impl 链中
    """
    cls, key = _resolve_impl_key(method)
    caller_module = sys._getframe(1).f_globals["__name__"]
    chain = _impl_chain.get((cls, key), [])
    for i, (fn, mod, _) in enumerate(chain):
        if mod == caller_module:
            if i == 0:
                raise NotImplementedError(
                    f"No super implementation for {cls.__name__}.{key} "
                    f"below module {mod!r}"
                )
            return chain[i - 1][0](*args, **kwargs)
    raise RuntimeError(
        f"call_super_impl({cls.__name__}.{key}) must be called from within "
        f"an @impl function for that method (caller module: {caller_module!r})"
    )
```

导出位置：`mutobj.__init__` 的 `__all__`，与 `impl` 并列。

## 测试要点

1. **基础链式调用**：A 注册 → B 覆盖 A 并 `call_super_impl` → 调用返回 A 的结果
2. **三层链**：A → B → C，C 调 super 得到 B，B 调 super 得到 A
3. **链底报错**：直接在最底层 impl 里调 `call_super_impl` → `NotImplementedError`
4. **非 impl 上下文报错**：从普通函数 / 测试代码调 `call_super_impl` → `RuntimeError`
5. **同名函数**：A 和 B 两个 impl 函数同名，验证定位正确
6. **卸载后行为**：`unregister_module_impls` 卸掉 B 之后，从 C 调 super 跳过 B 直达 A（取决于卸载语义，需先确认）
7. **property / classmethod / staticmethod**：各自补一组用例
8. **async 函数**：上述场景 async 版本（实际首要场景就是 async）

## 关键参考

### 源码
- `mutobj/src/mutobj/core.py:22` — `_impl_chain` 定义
- `mutobj/src/mutobj/core.py:169` — `_apply_impl()` 把链顶函数装到类上
- `mutobj/src/mutobj/core.py:192` — `_restore_stub()` 链空时恢复原桩
- `mutobj/src/mutobj/core.py:215` — `_register_to_chain()` 注册逻辑（含同模块替换约束）
- `mutobj/src/mutobj/core.py:976` — `impl()` 装饰器（含 method → (cls, impl_key) 解析逻辑，需抽取为 `_resolve_impl_key`）
- `mutobj/src/mutobj/core.py:1032` — `source_module = func.__module__`，与 frame 方案的 `__name__` 同源
- `mutobj/src/mutobj/core.py:1101` — `unregister_module_impls()`
- `mutbot/src/mutbot/builtins/web_jina_ext.py:14,39` — 当前 workaround（直接 `import _jina_search as _base_search`），上线后改用 `call_super_impl`
- `mutobj/tests/test_impl_chain.py` / `test_unregister.py` — 现有覆盖链相关测试，新测试文件 `test_impl_super.py` 与之并列

## 实施步骤清单

- [x] **抽取 `_resolve_impl_key(method)` 工具函数**
  - 从 `core.py:impl()` 装饰器中提取 method → `(cls, impl_key)` 的解析逻辑
  - 覆盖三种形式：property getter/setter（`_PropertyGetterPlaceholder` / `_PropertySetterPlaceholder`）、普通方法/classmethod/staticmethod
  - `impl()` 装饰器改为复用此函数，确保行为不变（跑现有测试通过）
- [x] **实现 `call_super_impl(method, *args, **kwargs)`**
  - 按设计方案中的最终 API 实现，10 行内
  - frame 取 caller module，链中按 module 字符串匹配，找到当前条目 → 调用 `chain[i-1][0]`
  - 链底报 `NotImplementedError`，caller 不在链中报 `RuntimeError`
  - 实施发现：链底的 `__default__` 桩条目需跳过（`i == 0 or chain[i-1][1] == "__default__"` 都视为无上级）
- [x] **导出 API**
  - `mutobj/__init__.py` 的 `__all__` 与 from-import 中加入 `call_super_impl`
- [x] **新增测试文件 `tests/test_impl_super.py`**（12 个用例全部通过）
  - 基础链式调用（A → B 覆盖 + super 调 A）
  - 三层链式（A → B → C，逐级 super）
  - 链底调 super → `NotImplementedError`
  - 非 @impl 上下文调 super → `RuntimeError`
  - 同名 impl 函数不影响定位
  - async 方法版本
  - property getter / setter
  - classmethod / staticmethod
  - 卸载中间层后链式行为（跳过被卸载的中间层直达下一个有效实现）
- [x] **消费者迁移：mutbot web_jina_ext**
  - `mutbot/src/mutbot/builtins/web_jina_ext.py` 移除 `from mutagent.builtins.web_jina import _jina_search as _base_search` workaround
  - 改用 `mutobj.call_super_impl(JinaSearchImpl.search, self, query, max_results)`
  - mutbot 集成测试 594/594 通过
- [x] **运行完整测试 + 类型检查**
  - mutobj `pytest`: 254/254 通过（原 242 + 新增 12）
  - mutobj `mypy src/mutobj`: 19 错（均为预存在，基线 20，本次重构后减少 1）
