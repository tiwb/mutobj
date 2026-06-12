# mutobj 测试方法论

## 测试的三层模型

> 一个测试要么描述用户能观察到的行为，要么固定一条不该回滚的内部契约，要么把当前实现抄了一遍。前两类有价值，第三类是负债。

借鉴 Bertrand Meyer《Object-Oriented Software Construction》的 Design by Contract、Gerard Meszaros《xUnit Test Patterns》的测试分类、以及 Hyrum's Law，把所有测试明确分成三层：

| 层级 | 验证对象 | 典型例子 | 态度 |
|------|---------|---------|------|
| **L1 行为** | 用户通过公开 API 能观察到的输入–输出 | `Child().x == 10`、`mutobj.fields(cls)` 返回值 | 测试主体，必须有 |
| **L2 契约** | 内部状态机 / 失效时机 / 回退路径，公开 API 无法直接观察，但承诺不回滚 | "unregister 后调用方法回退到默认实现"、"setattr 后缓存被清空" | 允许触及内部，但**集中、显式、少量** |
| **L3 实现** | 当前数据结构、命名、临时缓存形态 | `decl_meta_cache[cls].fields` 是 `dict`、descriptor ID、字段在容器中的顺序 | 不写；已写的迁移或删除 |

### 判定流程

对每条断言走一次三选一：

1. 能用公开 API 复述？ → **L1**，用公开 API 写。
2. 不能用公开 API 复述，但这条性质回滚会让 mutobj 另一个模块（lint / reload / unregister 等）行为变错？ → **L2**，允许触及内部，但必须用 `@pytest.mark.l2("<契约名>")` 标记测试函数，并在同一测试中补一条端到端行为断言形成"契约 + 行为"双重验证。
3. 不能用公开 API 复述，回滚也不破坏任何承诺？ → **L3**，删除。

> L2 是少数派。当一个项目的"L2 测试"开始膨胀（>10% 的内部断言），通常说明公开 API 设计有缺口，应回头补 API。

### 公开 API 清单（L1 工具箱）

所有 L1 测试仅使用 `mutobj/__init__.py` 导出的公开 API。完整清单以该文件 `__all__` 为准，不在此重复维护。

### L2 标记机制

L2 测试使用 `@pytest.mark.l2` 标记，契约名作为参数：

```python
@pytest.mark.l2("unregister 后 resolve_class 回退到原始注册")
def test_unregister_then_resolve_falls_back(self):
    ...
```

---

## 测试不应驱动公开 API 扩散

参考 Joshua Bloch《Effective Java》Item 15（最小化可访问性）与 DHH《Test-Induced Design Damage》：

> 当一条断言找不到对应的公开 API，**先确认它真属于 L1**，再决定是否扩张 API。

优先级：

1. **优先**：用现有公开 API 组合验证。
2. **其次**：判断这个 API 终端用户也用得上 → 加入 `mutobj.*` 公开 API。
3. **兜底**：只有测试 / lint / reload 等内省工具用得上 → 放 `mutobj._testing` 或 `mutobj.introspect` 子命名空间，文档明确声明**非 SemVer 保护**。

**反模式**：为单个测试新增一个公开 API，但终端用户文档里没有任何使用场景。

---

## 覆盖率：信号不是证明

参考 Brian Marick《How to Misuse Code Coverage》（1999）与 Martin Fowler《TestCoverage》：

- 高行 / 分支覆盖率是**必要条件**，不是**充分条件**。
- 一个穿透 200 行的行为断言会让这 200 行"被执行"，但不代表里面的每个分支都被验证过。
- 因此"用行为测试替代实现细节测试"和"提高覆盖率"是两件独立的事，不能互相代替。**行为测试 + 高覆盖率仍然可能漏掉 L2 契约**——这正是 L2 必须独立存在的原因。

mutobj 推荐目标：**Line ≥ 90%，Branch ≥ 80%**。

> 本方法论改造的目标是"L3 减少 / L1 替代 / L2 显式化"。覆盖率数字可能略降但测试信号更强，是预期结果，不应作为否决依据。

---

## 覆盖率工具与基线

`pyproject.toml` 已内置配置：

```toml
[tool.coverage.run]
source = ["src/mutobj"]
branch = true
```

常用命令：

```bash
pytest --cov --cov-report=json tests/        # 生成 JSON
pytest --collect-only -m l2 -q               # 统计 L2 数量
```

### 基线必须团队共享

参考 Fowler《Continuous Integration》：CI 基准是团队共享状态，不能是本地副本。当前文档把 `coverage_baseline.json` 仅留在本地违反这一原则，需修正。两选一：

- **方案 A（轻量）**：把**精简版** `coverage_baseline.json`（只保留 `totals` 字段）入库，PR CI 跑 `pytest --cov` 后与之 diff。完整 `coverage.json` 仍 `.gitignore`。
- **方案 B（标准）**：接 Codecov / Coveralls，CI 自动推送，PR comment 展示 diff。

### PR 收尾验证

1. `pytest` 全绿
2. 与基线 diff：Line 不降、Branch 不降超过 1pp（轻微下降允许，要在 PR 描述写明原因）
3. 新增的内部断言只能出现在带有 `@pytest.mark.l2(...)` 标记的测试里

---

## 编写新测试的清单

- [ ] 默认按 L1 写：只用 `mutobj.*` 公开 API，不 import `mutobj.core._*`
- [ ] 要触及内部前先回答："这条性质回滚是否会让 mutobj 其他模块行为变错？"
  - 是 → L2，加 `@pytest.mark.l2("<契约名>")` + 同处补一条端到端行为断言
  - 否 → 不要写
- [ ] 异常断言只检查类型 + 关键 token，不锁死完整 message
- [ ] 不依赖字典 / 集合迭代顺序（除非顺序本身是公开承诺）
- [ ] 公开 API 不够用时，依次考虑：现有 API 组合 → 加入 `mutobj.*` 公开 API（仅当终端用户也用得上） → 放 `mutobj._testing`

