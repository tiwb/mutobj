# Declaration 私有方法注册 设计规范

**状态**：📝 设计中
**日期**：2026-03-12
**类型**：重构

## 背景

`DeclarationMeta.__new__` 在处理方法、属性、property、classmethod、staticmethod 时，统一跳过 `_` 开头的名称。这导致所有 dunder 方法（`__init__`、`__repr__`、`__eq__` 等）和单 `_` 私有方法都无法进入覆盖链，不能被 `@impl` 覆盖。

### 影响范围

`core.py` 中 6 处 `startswith("_")` 过滤：

| 行 | 上下文 | 过滤的是 |
|---|--------|---------|
| 510 | 属性覆盖检测 | `_` 属性不参与父类属性覆盖 |
| 549 | property 声明 | `_` property 不转为 mutobj.Property |
| 574 | classmethod 声明 | `_` classmethod 不进覆盖链 |
| 588 | staticmethod 声明 | `_` staticmethod 不进覆盖链 |
| 602 | 普通方法声明 | `_` 方法不进覆盖链 |
| 832/840 | Extension | Extension 内部机制，保留 |

### 问题

1. **dunder 方法被误伤**：`__init__`、`__repr__` 等是 Python 公开协议，不是私有方法，应该支持 `@impl`
2. **单 `_` 私有方法是否需要过滤**：在 mutobj 范式下，真正的私有逻辑可以放到模块级函数或 Extension 中。Declaration 类中的 `_method` 同样可能需要声明-实现分离

## 待讨论

### 方向 A：全部放开

去掉所有 `startswith("_")` 过滤（Extension 的除外），所有方法统一进入覆盖链。

- 优点：规则最简单，无特殊化
- 论据：在 mutobj 范式下，真正私有的函数应该放到模块级实现或 Extension，Declaration 类中的方法都是接口的一部分

### 方向 B：放开 dunder，保留单 `_` 过滤

`__xxx__` 方法进入覆盖链，`_xxx` 方法继续跳过。

- 优点：区分 Python 公开协议和实现细节
- 缺点：多一条规则

### 方向 C：其他

待讨论。

## 关键参考

### 源码
- `mutobj/src/mutobj/core.py:510,549,574,588,602` — 6 处 `startswith("_")` 过滤
- `mutobj/src/mutobj/core.py:832,840` — Extension 中的过滤（保留）

### 相关规范
- `mutobj/docs/specifications/feature-positional-init.md` — 位置参数初始化（`__init__` 的 `@impl` 支持依赖本重构）
