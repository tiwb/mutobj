# mutobj-lint — 路径参数对齐 pyright（默认当前目录 + pyproject.toml 配置）

**状态**：✅ 已完成
**日期**：2026-05-19
**类型**：功能设计

## 需求

1. `mutobj-lint` 当前要求必传 `paths` 参数（`nargs="+"`），每次调用必须显式写路径。`pyright` 无需路径参数，默认扫描当前目录。行为不一致，增加使用摩擦
2. 无路径时默认扫描整个项目（含 `tests/`），和 `pyright` 默认只扫 `src/` 的范围不一致（`pyright` 通过 `[tool.pyright].include` 配置范围）

## 关键参考

- `src/mutobj/lint/__main__.py` — CLI 入口，`_build_parser()` 中 `paths` 参数定义 + `main()` 逻辑
- `src/mutobj/lint/_api.py` — `lint_directory()` 接受 `exclude` 参数
- `pyproject.toml` — `[tool.pyright].include = ["src"]` 已有既定扫描范围
- `docs/specifications/feature-mutobj-lint-iter3.md` — R003 规范（最新 lint 功能）
- `tests/test_lint/test_cli.py` — CLI 测试（需新增无参数默认行为测试）

## 设计方案

### 默认行为：无参数 → 当前目录

`paths` 从 `nargs="+"` 改为 `nargs="*"`，无参数时默认 `["."]`。

```python
parser.add_argument(
    "paths",
    nargs="*",
    default=["."],
    help="要扫描的文件或目录（可多个，默认当前目录）",
)
```

这是和 `pyright` 最直接的对齐方式：`pyright` 无参 ≈ `pyright .`。

### pyproject.toml 配置段 `[tool.mutobj-lint]`

引入专属配置段，控制默认扫描范围：

```toml
[tool.mutobj-lint]
include = ["src"]        # 默认扫描路径（替代 CLI paths 的默认值）
exclude = ["tests"]      # 追加排除目录（与 CLI --exclude 合并）
```

**优先级**：
1. 如果 CLI 传了 `paths` → 直接用，不读 config
2. 如果 CLI 没传 `paths` → 读 `[tool.mutobj-lint].include`，不存在则 fallback 到 `["."]`
3. `--exclude`（CLI）和 config 的 `exclude` **合并**（不是覆盖）：最终排除项 = 内置默认 + config exclude + `--exclude`

**pyproject.toml 搜索**：从当前目录逐级向上查找 `pyproject.toml`，找到第一个直接使用。

### 为何不复用 `[tool.pyright].include`

虽然两个配置语义相近（"我要分析的源码在哪"），但：
- `[tool.pyright]` 负责类型检查，`[tool.mutobj-lint]` 负责风格 lint，职责不同
- 解耦：未来两套工具的扫描范围可能独立变化（如 lint 扫 `src` + `tests`，pyright 只扫 `src`）
- 不影响已有项目：无 `[tool.mutobj-lint]` 时行为等同于无参数默认 cwd，完全向后兼容

### CLI help 更新

```text
usage: mutobj-lint [-h] [--exclude NAME] [--json] [paths ...]

mutobj 代码风格与命名规范静态检查

positional arguments:
  paths          要扫描的文件或目录（可多个。不传时从 pyproject.toml 读取
                  [tool.mutobj-lint].include，或默认当前目录）
```

### 实现概要

改动文件：`src/mutobj/lint/__main__.py`

1. **新增 `_find_pyproject()`**：从 cwd 向上搜索 `pyproject.toml`
2. **新增 `_load_mutobj_lint_config()`**：读 `[tool.mutobj-lint]` 段，返回 `(include: list[str] | None, exclude: list[str])`
3. **修改 `main()`**：
   - 如果 `args.paths` 为空（默认值 `["."]` 无法区分"用户没传"和"用户传了 `.`" → 用 `nargs="*"` + `default=None`，在 `main()` 中判断是否为 `None`）
   - 未传路径时调用 `_load_mutobj_lint_config()`，合并 `include` / fallback
   - `--exclude` 与 config exclude 合并

**注意**：`default=["."]` 无法区分"用户没传"和"用户传了 `"."`"。改用 `default=None` + 在 `main()` 中处理。

## 待定问题

### QUEST Q1: `default=["."]` 还是 `default=None`

**问题**：`default=["."]` 会让 `args.paths` 总是有值，无法区分用户传了 `"."` 还是没传，导致 config 的 `include` 永远不会被读取（因为 `paths` 已经有值了）。

**建议**：使用 `default=None`，在 `main()` 中判断 `if args.paths is None or args.paths == []`，然后去读 config 或 fallback `["."]`。这样用户显式传 `"."` 的行为和 pyright 一致（尊重用户意图），不传时读 config。

### QUEST Q2: 是否需要支持 `[tool.mutobj-lint]` 配置段，还是只做最简默认 cwd

**问题**：方案 A（最简默认 cwd）改动极小但默认范围不精确；方案 B（配置段）使用体验更好但增加复杂度。

**建议**：方案 B。`mutobj-lint` 和 `pyright` 都是项目级工具，通过 `pyproject.toml` 配置是新加入项目的标准操作。引入配置段后，`mutobj-lint` 的调用体验与 `pyright` 完全对齐：进项目目录 → 跑命令 → 自动按配置扫描。且 `mutobj-lint` 现有 `--exclude` 已支持多个，扩大为 config 字段自然。

## 消费者场景

| 消费者 | 场景 | 依赖的输出 | 验收标准 |
|--------|------|-----------|---------|
| 开发者日常使用 | 项目根目录直接敲 `mutobj-lint` | 无参数即可扫描 | 不传参数时自动扫描项目（优先读 config，fallback cwd） |
| CI/CD | 在 CI 中运行 `mutobj-lint` | 扫描 `src/` 目录 | `mutobj-lint` 无参执行，exit code 正确反映违规 |
| mutobj 自身 dogfooding | mutobj 仓库跑 `mutobj-lint` | 扫描 `src/` | 无参数 + 配置 `include = ["src"]`，零违规 |

## 实施步骤清单

- [x] `__main__.py` — `paths` 参数改为 `nargs="*"` + `default=None`
- [x] `__main__.py` — 新增 `_find_pyproject()` 向上搜索 `pyproject.toml`
- [x] `__main__.py` — 新增 `_load_mutobj_lint_config()` 读取 `[tool.mutobj-lint]` 段
- [x] `__main__.py` — `main()` 中合并 CLI paths / config include / fallback cwd 逻辑
- [x] `__main__.py` — config exclude 始终与 `--exclude` 合并；config include 路径相对于 pyproject.toml 所在目录解析
- [x] `tests/test_lint/test_cli.py` — 新增 `TestDefaultPath`（2 个测试）和 `TestPyprojectConfig`（9 个测试）
- [x] `pyproject.toml` — 新增 `[tool.mutobj-lint]` 配置段（`include = ["src"]`）
- [x] pyright 零错误
- [x] 全量 109 个 lint 测试通过
- [x] `mutobj-lint` 无参数运行通过
