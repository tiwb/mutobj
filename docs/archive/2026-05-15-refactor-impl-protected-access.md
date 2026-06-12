# `@impl` 实现函数访问受保护成员 — pyright 类型检查兼容性

**状态**：✅ 已完成
**日期**：2026-05-15

## 需求

mutobj 的 `@impl` 装饰器将实现函数放在物理上独立的模块（`_*_impl.py`）中，语义上这些函数就是类方法。当 `@impl` 实现需要调用基类的 `_` 前缀方法时，pyright strict 模式的 `reportPrivateUsage` 会报错。

触发场景（mutgui）：

```python
# events.py — EventHandler 基类
class EventHandler(mutobj.Declaration):
    def _resolve_call(self, view, event) -> tuple[list, dict]:
        """protected helper，供子类 handle() 实现中调用"""
        ...

# _menu_impl.py — @impl 实现模块
@impl(MenuTrigger.handle)
async def menu_trigger_handle(self: MenuTrigger, view: View, event: Event) -> bool:
    positional, kwargs = self._resolve_call(view, event)  # ← pyright: reportPrivateUsage
```

`menu_trigger_handle` 是模块级函数，不在 `EventHandler` 类体内。pyright 按物理位置判定位，不认 `@impl` 建立的语义关系。

**这是一个 mutobj 框架层的通病**——任何下游项目只要在 `@impl` 实现里调用基类的 protected helper，都会触发。当前 mutgui 有 1 处（`_menu_impl.py`），随着项目增长会持续出现。

## 关键参考

### 问题现场

- `mutobj/src/mutobj/core.py:1390-1525` — `impl()` 装饰器：将模块级函数注册为类方法实现
- `mutgui/src/mutgui/events.py:208` — `EventHandler._resolve_call`，protected helper
- `mutgui/src/mutgui/_menu_impl.py:63-67` — `@impl(MenuTrigger.handle)` 调用 `self._resolve_call`
- `mutgui/docs/specifications/refactor-impl-cross-module-access.md` — 下游消费者场景，决策一以此问题为前提

### mutobj 项目结构约定

- `@impl` 实现位于 `_*_impl.py` 命名模式的文件中
- 声明文件底部通过 `from . import _xxx_impl` 触发注册
- `_impl.py` 文件按约定只包含 `@impl` 函数及其局部 helper

## 设计方案

### 根因

pyright 的 `reportPrivateUsage` 按**词法位置**判定 protected 成员访问：`_x` 仅在定义类的类体内、其子类的类体内、或同一模块内合法。`@impl` 函数物理上是 module-level、且常位于独立的 `_*_impl.py`，不满足任意一条，因此 pyright 报错是规则的正确执行而非误报。

mutobj 的 `@impl` 模型隐含一种 Python 命名约定中**不存在的可见性**——「对实现者公开，对业务代码私有」。在不修改 pyright 的前提下，框架层无法消解这一不匹配。

### 决策

**mutobj 不在框架层解决此问题**——明确承认这是 pyright 词法规则与 `@impl` 模型的固有错位。提供单一标准绕行：**文件级 pragma `# pyright: reportPrivateUsage=false`**。

选择 pragma 作为推荐方案的理由：

- `_*_impl.py` 按约定就是 Declaration 类的实现延伸，访问基类 protected helper 在语义上属「类内访问」，关掉该检查不会漏过真正的违规
- 一行注释跟随源码走，零调用点污染
- 不需要项目级 pyrightconfig 配置，下游零成本接入

严谨场景（不接受任何漏检）由使用者自行处理——例如把 helper 重新组织为模块级公开函数、独立辅助类等。**mutobj 不为此提供框架层方案，也不在文档中给出具体配方**，避免暗示存在「mutobj 推荐的严谨写法」。

### 落点

- `docs/guide.md` 在「实现文件命名」之后追加新小节「`@impl` 与基类 protected 成员」，说明问题与 pragma 写法
- `core.py::impl()` 装饰器 docstring 追加简短注意（2 行），引导到 guide.md
- 不建独立 `pyright-compatibility.md`、不改 `architecture.md`、不动 `README.md`

## 实施步骤清单

- [x] `docs/guide.md` 追加「`@impl` 与基类 protected 成员」小节（位于「实现文件命名」之后、「覆盖链与卸载」之前）
- [x] `core.py::impl()` docstring 追加 2 行「注意」，引导到 guide.md
- [x] 验证 mutobj 自身 pyright strict 仍通过（`pyright src` 输出 `0 errors, 0 warnings, 0 informations`）
