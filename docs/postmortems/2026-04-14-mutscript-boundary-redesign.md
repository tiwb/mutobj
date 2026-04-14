# MutScript 设计边界重新划分 — 设计迭代复盘

**日期**：2026-04-14
**类型**：设计迭代复盘
**关联规范**：`docs/specifications/feature-safe-subset.md`

## 起源

`feature-safe-subset.md` 设计了 MutScript —— 一个严谨的 Python 语言子集，包含三个组件：

- **Script** — AST 编译器，将 Python 代码编译为安全的字节码（属性访问 → guard 变换）
- **ScriptEnv** — 执行环境，提供 guard 函数实现 + 冻结关键 key + 安全 builtins
- **TypeSpec** — 类型安全声明，通过 `discover_subclasses()` 自动发现每个类型的安全方法白名单

三者全部放在 mutobj 中。设计完整，论证严谨，但 **ScriptEnv 的实现一直卡着** —— 因为没有真实的消费者场景来验证执行环境的设计决策。

## 转折：python-sandbox 的实践路径

一条独立的实践路径提供了关键信息：

1. **编辑器内 python-sandbox**：MCP 工具太多占用 context → 聚合为单一 Python 执行工具
2. **独立 python-sandbox**：从编辑器扩展到给 Claude Code 用，验证更广泛的场景
3. **mutagent.sandbox**：确定 sandbox 是 mutagent 的核心能力（PySandbox 之于 MutAgent ≈ Bash 之于 Claude Code）

关键发现：**简单的 AST 检查（禁 import/class + 限制 builtins）就够用**。Agent 不会尝试绕过能力边界，不需要属性级的 guard 变换来保证安全。严格的沙箱是长期架构目标，但不是当前必需。

## 决策：边界重新划分

### 核心原则

**mutobj 提供原语，不提供组装。** 判断标准：一个组件的变更单元跟着谁走？

### TypeSpec → 留在 mutobj

TypeSpec 是**类型的自描述能力**。它声明"这个类型在 MutScript 中暴露哪些操作"。变更单元是类型本身 —— 当你定义或修改一个类型时，同时更新它的 TypeSpec。

TypeSpec 作为 Declaration 子类，通过 `discover_subclasses()` 自动发现，完全契合 mutobj 的类型系统。

三个潜在消费者：
- **mutagent.sandbox** — 读取 TypeSpec 做运行时属性访问检查
- **mutobj 框架** — Declaration 子类的代码遵循子集约束
- **native 化** — 子集足够受限，可编译为原生代码（反复设计但未开始）

### Script → 移交 mutagent.sandbox

Script 的 AST 变换（`.attr` → `.getattr()` guard 调用）是**沙箱专用的编译策略**。编译产物硬编码了运行时 contract（`.getattr`/`.setattr` 函数必须存在于执行环境中），与 ScriptEnv 是同一设计决策的两面。

native 化需要的编译器会做完全不同的变换（生成原生调用而非 guard 调用）。将 Script 定性为"通用原语"是不准确的 —— 它是特定消费者的特定编译策略。

### ScriptEnv → 移交 mutagent.sandbox

ScriptEnv 是**应用层组装**：把 Script 的编译能力 + TypeSpec 的类型白名单 + 注入的外部函数组合成可执行环境。注入什么函数、什么级别的隔离、怎么管理状态 —— 这些都是消费者的决策。

mutagent.sandbox 的 app 层（SandboxApp）就是 ScriptEnv 的真实形态。

### 对 feature-safe-subset.md 的影响

规范需要收窄范围至 TypeSpec + 语言子集定义。Script/ScriptEnv 部分标注为已迁出至 mutagent.sandbox 的规范中。（规范修改作为后续任务，不在本次执行。）

## 核心洞察

### "为假想消费者设计"是卡住的根因

ScriptEnv 卡住不是因为设计难度，而是因为缺少真实消费者来验证设计决策。执行环境的设计需要知道"注入什么、隔离到什么程度、状态怎么管" —— 这些问题只有消费者能回答。python-sandbox 的实践路径恰好提供了这个消费者。

### 编译器的归属由目标运行时决定

Script 和 ScriptEnv 的耦合不是实现层面的偶然耦合，而是设计层面的必然耦合 —— 编译器的输出格式由运行时的需求决定。当存在多个不同的运行时（sandbox、native），它们各自需要各自的编译器。因此编译器跟着运行时走，不放在原语层。

### 原语 vs 组装的判断标准

一个组件是原语还是组装，可以通过"变更单元"来判断：
- **TypeSpec** 的变更跟着类型走 → 类型原语，属于 mutobj
- **Script/ScriptEnv** 的变更跟着执行场景走 → 场景组件，属于消费者

### 实践验证优先于理论完备

python-sandbox 用简单的 AST 检查证明了 agent 场景下不需要严格沙箱。这个实践信号让我们可以渐进增强：先用简单方案上线（mutagent.sandbox），需要时再引入 mutobj 的 Script + TypeSpec。避免了在缺少消费者反馈时追求理论上的完备性。

## 后续影响

- **mutobj**：解除 ScriptEnv 阻塞，专注 TypeSpec 和语言子集定义
- **mutagent**：新增 `mutagent.sandbox` 子模块，从 python-sandbox 迁入，作为 agent 的核心执行能力
- **feature-safe-subset.md**：后续收窄范围，Script/ScriptEnv 部分迁至 mutagent 规范
