# mutobj pyright 类型错误修复

**状态**：✅ 已完成
**日期**：2026-03-09
**类型**：Bug修复

## 背景

mutobj 使用 pyright strict 模式，当前有 75 个错误。主要集中在 `core.py` 一个文件中，错误可分为以下几类。

## 现状分析

### 错误分类与统计（实际 75 个）

| 规则 | 数量 | 根因 |
|------|------|------|
| `reportFunctionMemberAccess` | 16 | `__mutobj_class__` 等自定义函数属性 |
| `reportPrivateUsage` | 10 | `_prop`/`_fget`/`_fset` 跨类访问 |
| `reportMissingTypeArgument` | 4 | `Extension` 未指定类型参数 |
| `reportUnknown*Type` 连锁 | ~42 | Extension[Unknown] 传播 + metaclass 迭代 |
| `reportUnnecessaryComparison`/`IsInstance` | 3 | metaclass 上下文误判 |

## 设计方案

### 核心决策

1. **函数属性赋值**（Q1）— pyright 配置关闭 `reportFunctionMemberAccess = false`（16 处错误，逐行抑制噪音太大；mutobj 只有 core.py 一个文件，无误漏风险）

2. **Extension 泛型**（Q2）— 注册表和函数签名中 `Extension` 改为 `Extension[Any]`（消除 ~50 个连锁 Unknown 错误）

3. **protected 访问**（Q3）— 逐行 `# pyright: ignore[reportPrivateUsage]` 抑制（10 处；保留全局 protected 检查的价值）

4. **strict 模式规则取舍**（Q4）— 在 `pyproject.toml` 中只关闭 `reportFunctionMemberAccess = false`；`reportUnnecessaryComparison` 和 `reportUnnecessaryIsInstance` 仅 3 处，逐行 `# pyright: ignore` 抑制

### metaclass 迭代的 Unknown 类型

`DeclarationMeta.__init_subclass__` 中遍历 `__dict__` 产生的 Unknown 类型错误，通过显式类型注解和 `set[str]()` 类型参数消除。`classmethod.__func__` / `staticmethod.__func__` 的 Unknown 传播通过逐行 `# pyright: ignore` 抑制。

## 关键参考

### 源码
- `mutobj/src/mutobj/core.py` — 所有错误集中于此文件
- `mutobj/pyproject.toml:63-66` — pyright 配置（strict + reportFunctionMemberAccess=false）

### 相关规范
- `mutagent/docs/specifications/bugfix-pyright-type-errors.md` — 已完成
- `mutbot/docs/specifications/bugfix-pyright-type-errors.md` — 已完成

## 实施步骤清单

### Phase 1: pyright 配置调整 [✅ 已完成]

- [x] **Task 1.1**: 在 `pyproject.toml` 的 `[tool.pyright]` 中添加 `reportFunctionMemberAccess = false`
  - 状态：✅ 已完成

### Phase 2: Extension[Any] 泛型修复 [✅ 已完成]

- [x] **Task 2.1**: 修复 `_extension_registry` 及相关函数签名，`Extension` → `Extension[Any]`
  - 状态：✅ 已完成

### Phase 3: protected 访问抑制 [✅ 已完成]

- [x] **Task 3.1**: 在 10 处 `_prop`/`_fget`/`_fset` 访问行添加 `# pyright: ignore[reportPrivateUsage]`
  - 包含 `_apply_impl` 和 `_restore_stub` 中遗漏的 4 处
  - 状态：✅ 已完成

### Phase 4: 逐行抑制 + metaclass Unknown 类型修复 [✅ 已完成]

- [x] **Task 4.1**: 在 3 处 `reportUnnecessaryComparison`/`reportUnnecessaryIsInstance` 添加逐行 `# pyright: ignore`
  - 状态：✅ 已完成
- [x] **Task 4.2**: 修复 `DeclarationMeta.__init_subclass__` 中的 Unknown 类型错误
  - `classmethod`/`staticmethod` 返回类型添加泛型参数
  - `getattr(base, _DECLARED_*, set())` 改为 `set[str]()`
  - `classmethod.__func__`/`staticmethod.__func__` 添加类型注解 + `# pyright: ignore`
  - `_MUTABLE_TYPES` isinstance 后提取 `type_name` 变量避免 Unknown 传播
  - `_apply_impl`/`_restore_stub` 中 `declared_cm`/`declared_sm` 添加 `set[str]` 类型注解
  - 状态：✅ 已完成

### Phase 5: 残余错误处理 [✅ 已完成]

- [x] **Task 5.1**: 修复 Phase 1-4 后剩余的 5 个 pyright 错误
  - `val.__func__` Unknown 传播 — 逐行 `# pyright: ignore`
  - `type(value).__name__` Unknown 传播 — 逐行 `# pyright: ignore`
  - 状态：✅ 已完成

### Phase 6: 验证 [✅ 已完成]

- [x] **Task 6.1**: 运行 `npx pyright src/mutobj/` 验证 0 errors ✅
- [x] **Task 6.2**: 运行 `pytest` 确保无功能回归 — 170 passed ✅
  - 状态：✅ 已完成

## 修复统计

| 修复方式 | 消除错误数 |
|----------|-----------|
| pyright 配置关闭 `reportFunctionMemberAccess` | 16 |
| `Extension[Any]` 泛型参数 | ~42 |
| 逐行 `# pyright: ignore` | 13 |
| 显式类型注解 / `set[str]()` | 4 |
| **合计** | **75** |
