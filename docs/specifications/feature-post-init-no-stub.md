# `__post_init__` 无桩 @impl 支持 + 元类强制触发 + 防污染

**状态**：✅ 已完成
**日期**：2026-04-25
**类型**：功能设计 + 重构

## 需求

mutio 的 Response 子类（JSONResponse / HTMLResponse / PlainTextResponse / RedirectResponse / FileResponse）当前用 `@impl(Cls.__init__)` 模式注入构造逻辑，5 个子类几乎只有一个不同签名的 `__init__` 桩，`@impl(__init__)` 全是把 body/headers 算出来再回头调 `Response.__init__(...)`。讨论后决定改用方案 B（字段 + `__post_init__`）。

落地方案 B 触发了三个 mutobj 框架问题：

1. **可以让 `__post_init__` 不必声明桩就能 @impl 覆盖吗？** 当前必须在子类类体里写 `def __post_init__(self) -> None: ...`，纯实现细节场景下样板感强。
2. **如果可以，机制能不能不引入"特例"？** 第一版补丁里塞了 19 行 `# 特例: Declaration 基类的 __post_init__ ...` 分支，跟 mutobj 其他统一处理风格不符。
3. **`__init__` 也能享受同等待遇吗？** 如果不能,框架要至少防止用户把 `@impl(Cls.__init__)` 误注册到 Declaration 基类(目前是静默污染所有子类)。

## 关键参考

### 源码定位

- `mutobj/src/mutobj/core.py:60-77` — `_MUTOBJ_RESERVED_DUNDERS` + 新增 `_DECLARATION_USER_HOOKS` 白名单常量
- `mutobj/src/mutobj/core.py:493-506` — Declaration 元类 early-return 分支，按白名单注册"用户钩子"
- `mutobj/src/mutobj/core.py:684-688` — MRO 委托循环（去掉 `or base.__name__ == "Declaration"` 跳过）
- `mutobj/src/mutobj/core.py:752-762` — DeclarationMeta `__call__`：`__new__ → __init__ → __post_init__`
- `mutobj/src/mutobj/core.py:1107-1119` — `impl()` 防污染检查（拒绝注册到 Declaration 基类）

### 测试

- `mutobj/tests/test_post_init.py` — 新增 3 个测试覆盖无桩 / 兄弟隔离 / super 缺失场景
- `mutobj/tests/test_impl.py` — 新增 1 个测试覆盖防污染

## 设计方案

### 核心抽象：`_DECLARATION_USER_HOOKS` 白名单

Declaration 基类上"允许被 @impl 自动委托"的方法白名单。这些钩子默认 no-op、签名固定、可被追加式覆盖；Declaration 自身的 `__init__`/`__new__` 等框架基础设施不进白名单。

```python
_DECLARATION_USER_HOOKS = frozenset({
    "__post_init__",
})
```

未来加新钩子（`__validate__`、`__pre_render__` 等）只需追加白名单一行。

### Declaration 基类增加默认 `__post_init__`

```python
class Declaration(metaclass=DeclarationMeta):
    def __post_init__(self) -> None:
        """构造完成后自动调用，子类可覆盖做派生计算。

        子类既可在类体内重新声明 ``def __post_init__(self) -> None: ...``
        把它作为自身覆盖链入口，也可以省略声明、直接
        ``@mutobj.impl(MyClass.__post_init__)`` 注入实现 —— 元类会为每个
        子类生成独立的委托，覆盖不会污染兄弟类或基类。
        """
        ...
```

### 元类 `__call__` 强制触发流水线

```python
def __call__(cls: type[T], *args: Any, **kwargs: Any) -> T:
    obj = cls.__new__(cls, *args, **kwargs)
    if isinstance(obj, cls):
        cls.__init__(obj, *args, **kwargs)
        obj.__post_init__()
    return obj
```

收益：用户 `@impl(Cls.__init__)` 自定义构造**不调 `super().__init__()`** 时，`__post_init__` 仍能触发。两个钩子互不依赖，心智模型简化。

代价：用户故意"不想触发 post_init"的场景绕不过去——但这种用法不合理，本身就该被纠正。

### 防污染：拒绝 @impl 注册到 Declaration 基类

`impl()` 在解析到 `target_cls is Declaration` 且 `method_name` 不在白名单时，立即 `raise ValueError`，并提示用户怎么修：

```python
if target_cls is Declaration and method_name not in _DECLARATION_USER_HOOKS:
    raise ValueError(
        f"@impl({method_name!r}): refusing to register on Declaration base "
        f"class. The method was resolved to Declaration because the "
        f"subclass does not declare its own {method_name!r}. Add a stub "
        f"on the subclass first, e.g.\n"
        f"    class MySubclass(mutobj.Declaration):\n"
        f"        def {method_name}(self, ...) -> ...: ...\n"
        f"then re-run @impl(MySubclass.{method_name})."
    )
```

典型救场场景：用户写 `@impl(Box.__init__)` 但 `Box` 没有自己的 `__init__` 桩，反推会到 Declaration——之前会静默替换 `Declaration.__init__` 污染所有子类，现在立即报错并示范桩怎么写。

### 为什么 `__init__` 不能进白名单

`__init__` 与 `__post_init__` 的设计意图根本不同：

| | `__post_init__` | `__init__` |
|--|----------------|------------|
| 默认行为 | no-op | 字段绑定 + 参数解析（框架核心） |
| 签名 | 固定 `(self) -> None` | **每个子类不同** |
| 覆盖语义 | 在默认之后**追加**钩子 | **完全替换**构造逻辑 |
| 桩的信息量 | 0（"我有钩子"） | **就是新签名 API 本身** |

`__init__` 的桩对 IDE / pyright / 读者就是 API 文档。强行让它走"无桩 @impl"会破坏关键字参数处理和签名提示。已经有 `__post_init__` 这个无桩钩子覆盖大多数场景。

### Extension 不需要 `__post_init__`

Extension 的 `__init__` 自身就是零参 hook（`core.py:996-997`），在字段绑定后被 `get_or_create` 自动调用——行为上等价于 dataclass 的 `__post_init__`，不需要新增 API。

## 实施步骤清单

- [x] 在 `core.py` 顶部新增 `_DECLARATION_USER_HOOKS = frozenset({"__post_init__"})` 常量及说明注释
- [x] 改造元类 Declaration early-return 分支：遍历白名单注册到 `_DECLARED_METHODS` 和 `_impl_chain`
- [x] 删除元类中 19 行 `# 特例: Declaration 基类的 __post_init__ ...` 分支
- [x] 元类 MRO 委托循环去掉 `or base.__name__ == "Declaration"` 跳过条件
- [x] Declaration 加默认空 `def __post_init__(self) -> None: ...`（带 docstring 说明用法）
- [x] Declaration `__init__` 末尾移除 `self.__post_init__()` 调用
- [x] 元类增加 `__call__`：强制 `__new__ → __init__ → __post_init__` 流水线
- [x] `impl()` 增加防污染检查：拒绝注册到 Declaration 基类（白名单除外）
- [x] `tests/test_post_init.py` 新增 `test_impl_without_stub_declaration` / `test_impl_does_not_leak_to_siblings` / `test_post_init_fires_when_custom_init_skips_super`
- [x] `tests/test_impl.py` 新增 `test_impl_refuses_to_pollute_declaration_base`
- [x] 全套测试通过（242 passed）

## 测试验证

| 测试 | 验证点 |
|------|--------|
| `test_impl_without_stub_declaration` | 子类不声明桩，直接 `@impl(Cls.__post_init__)` 即可工作 |
| `test_impl_does_not_leak_to_siblings` | 给 ChildA 注入 post_init 不影响 ChildB 和 Declaration 基类 |
| `test_post_init_fires_when_custom_init_skips_super` | `@impl(__init__)` 不调 super 时 post_init 仍由元类触发 |
| `test_impl_refuses_to_pollute_declaration_base` | `@impl(Box.__init__)` 不写桩会清晰报错而非污染 Declaration |

最终：**242 passed**（含新增 4 个测试）。

## 后续工作

mutio Response 子类按方案 B 重构（这是触发本次框架改动的原始需求，在另一个 spec 文档中跟进）。

mutobj 指南 `docs/guide.md` 可酌情更新两点：
- "三种构造方式"章节加入"无桩 @impl(__post_init__)"作为方式 4
- "Extension"章节加一句"`__init__` 即扮演 post_init 角色，可重写做派生计算"
