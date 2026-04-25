# Extension `__setattr__` 属性代理设计审查 设计规范

**状态**：✅ 已完成
**日期**：2026-04-21
**类型**：重构

## 需求

1. 审查 `Extension.__setattr__` 的属性代理设计是否合理、是否符合使用直觉
2. 实际使用中遇到了反直觉行为，需要评估是否需要调整

## 问题现象

在 mutgui 的 DockPanel per-viewport 功能实现中（`feature-dock-viewport.md`），需要在 `ViewWireTransform` Extension 实例上设置自定义回调：

```python
xf = ViewWireTransform.get_or_create(self)  # self 是 DockPanel（View 子类）
xf.transform = self._transform_wire_tree    # 意图：覆盖 extension 的 transform 方法
```

**预期**：`xf.transform` 被覆盖为自定义方法
**实际**：赋值被静默代理到了 DockPanel 实例上（`setattr(dock_panel, "transform", ...)`），`xf.transform` 仍然是默认空实现

原因是 `Extension.__setattr__`（`core.py:933`）的规则：
- `_` 前缀 → 设在 extension 自身
- 非 `_` 前缀 → 代理到 `self._instance`（目标 Declaration 实例）

最终绕过方案：改用 `_fn` 私有属性存储回调。

## 核心问题

### 当前行为（修改前）

```python
# Extension.__getattr__
def __getattr__(self, name):
    if name.startswith("_"):
        raise AttributeError(...)    # _ 前缀：不代理
    return getattr(self._instance, name)  # 非 _ 前缀：代理到 Declaration

# Extension.__setattr__
def __setattr__(self, name, value):
    if name.startswith("_"):
        super().__setattr__(name, value)  # _ 前缀：设在 extension 自身
    elif self._instance is not None:
        setattr(self._instance, name, value)  # 非 _ 前缀：代理到 Declaration
```

### 问题分析

1. **`__getattr__` 和 `__setattr__` 不对称**：`__getattr__` 是 fallback（只在正常查找失败时触发），但 `__setattr__` 总是被调用。导致"能读不能写"的不一致
2. **静默失败**：赋值不报错也不警告，开发者很难发现回调没生效
3. **零消费者**：扫描 mutbot、mutagent、mutgui 全部 Extension 子类，所有属性均为 `_` 前缀，读代理和写代理均无实际使用者

## 设计方案

### 决策：去掉所有代理，`_instance` 改为公开的 `target`

- 删除 `__getattr__` 读代理
- 删除 `__setattr__` 写代理（原先已简化为直通 `super().__setattr__`，最终完全移除）
- `_instance` → `target` 公开属性，与类级属性 `_target_class` 形成对称
- 访问 Declaration 属性使用 `ext.target.name` 显式写法

**理由**：
- 代理行为零消费者，读写均无实际使用
- 显式访问 `ext.target.xxx` 比隐式代理更清晰
- 消除读写不对称导致的反直觉行为

## 关键参考

- `src/mutobj/core.py:838` — `Extension` 类定义
- `src/mutobj/core.py:854` — `target: Declaration | None` 属性声明
- `mutgui/src/mutgui/_view_impl.py:55-68` — `ViewWireTransform` Extension（触发此问题的场景）

## 实施步骤清单

- [x] 去掉 `__setattr__` 写代理
- [x] 去掉 `__getattr__` 读代理
- [x] `_instance` → `target` 公开属性
- [x] 更新测试（`test_extension.py`、`test_defaults.py`）
- [x] 全量测试通过
