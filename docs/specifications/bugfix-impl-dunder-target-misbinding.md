# `@impl` 在 dunder 方法上目标类错配

**状态**：✅ 已完成
**日期**：2026-04-24
**类型**：Bug修复

## 需求

Declaration 子类中**用户显式声明的 dunder 方法**（典型 `__init__`）作为 `@impl` 目标时，目标类定位机制不正确：

1. `DeclarationMeta` 在收集声明方法时，按 `if name.startswith("_"): continue` 一刀切跳过所有下划线方法 → 不给它们设置 `__mutobj_class__`、不入 `_impl_chain`、不加入 `_DECLARED_METHODS`
2. `@impl(SomeClass.__init__)` 装饰时，`getattr(method, "__mutobj_class__", None)` 取不到值 → 走 fallback：按 qualname 在 `_class_registry.values()` 里找首个 `__name__ == class_name` 的类
3. 当工作区里**有多个同名 Declaration 子类**时，fallback 命中的"第一个"取决于注册顺序，可能不是用户写代码时引用的那个 → 静默把 impl 装到错的类上，**无任何报错**

**触发实例**（mutgui + mutbot 同名 `Channel`）：

- `mutgui/src/mutgui/channel.py` 声明 `class Channel(Declaration)` 带 `def __init__(self) -> None: ...`
- `mutgui/src/mutgui/_channel_impl.py` 写 `@impl(Channel.__init__)` 实现 `channel_init`，给 `self.channel_id` 自增赋值
- `mutbot/src/mutbot/channel.py` 也声明 `class Channel(Declaration)` 但**没有** `__init__` stub（用 `Declaration` 默认 `__init__` 接收 kwargs 设属性），有 `ch: int` / `session_id: str` 字段
- 两个 `Channel` 都被加载到 `_class_registry` 后，`@impl(mutgui.Channel.__init__)` 的 fallback 按字典 values 顺序取了 mutbot.Channel
- 后果一：`mutgui.Channel()` 子类调用 `super().__init__()` 走的是 `Declaration.__init__`（没人覆盖它），`channel_id` **永远没赋值** → 后续访问触发 `AttributeError: 'XxxChannel' object has no attribute '_mutobj_attr_channel_id'`
- 后果二：`mutbot.Channel(ch=42, session_id="s1")` 实际调用的 `__init__` 已被 `channel_init(self) -> None` 替换，**只接收 self**，kwargs 报错 `TypeError: Channel.__init__() got an unexpected keyword argument 'ch'`

实际报错日志：

```
ERROR    mutbot.asyncio: Task exception was never retrieved: 'MutbotMutguiChannel' object has no attribute 'channel_id'
Traceback (most recent call last):
  File "D:\ai\mutobj\src\mutobj\core.py", line 265, in __get__
    return getattr(obj, self.storage_name)
AttributeError: 'MutbotMutguiChannel' object has no attribute '_mutobj_attr_channel_id'

ERROR    mutbot.web.rpc: RPC handler error: method=session.connect
Traceback (most recent call last):
  File "D:\ai\mutbot\src\mutbot\web\transport.py", line 585, in open
    channel = Channel(ch=ch_id, session_id=session_id or "")
TypeError: Channel.__init__() got an unexpected keyword argument 'ch'
```

### 影响范围

不只 `__init__`。任何用户在 Declaration 子类里**显式声明的 dunder**作为 stub 都受影响：`__call__`、`__enter__`/`__exit__`、`__hash__`、`__eq__`、`__len__`、`__iter__`、`__contains__`、`__getitem__`/`__setitem__` 等等——只要写成 `def __xxx__(...): ...` 期望 `@impl` 覆盖，目前都靠"qualname 全局唯一"才能正确工作。

mutgui 是当前最容易触发的下游：`View`、`Channel`、`ViewPort` 等基类都有 `__init__` stub，下游项目（mutbot 已踩到，未来 LLM 配置面板/Terminal 等只会更多）很可能定义同名 Declaration 类。

### 当前 workaround

mutgui 侧 hack（`mutgui/src/mutgui/_channel_impl.py` 顶部）：

```python
# 显式绑定 __mutobj_class__：mutobj metaclass 跳过下划线方法（含 __init__），
# 不会自动给 __init__ 设置 __mutobj_class__。
Channel.__init__.__mutobj_class__ = Channel

@impl(Channel.__init__)
def channel_init(self: Channel) -> None: ...
```

这是用户态 workaround，根因在 mutobj。本 spec 修复后该 hack 应移除。

## 关键参考

- `src/mutobj/core.py:600-609` — `DeclarationMeta.__new__` 处理普通方法声明的循环；首行 `if method_name.startswith("_"): continue` 是问题源头
- `src/mutobj/core.py:586-598` — 同样的下划线 skip 出现在 staticmethod 处理（一致性问题）
- `src/mutobj/core.py:548-583` — property 处理也有 `if prop_name.startswith("_"): continue`
- `src/mutobj/core.py:572-584` — classmethod 处理同样有下划线 skip
- `src/mutobj/core.py:973-1002` — `@impl` 装饰器 fallback 路径：`__mutobj_class__` 缺失 → 按 qualname 搜 `_class_registry.values()` 取首个匹配，多匹配时静默选第一个
- `src/mutobj/core.py:807-828` — `Declaration.__init__` 默认实现（接收 kwargs 设属性），mutbot.Channel 依赖此默认行为
- `src/mutobj/core.py:788-805` — `Declaration.__new__` 应用属性默认值（与 `__init__` 解耦，所以即使 `__init__` 被错配，无默认值的属性如 `channel_id` 仍未初始化）
- `mutgui/src/mutgui/channel.py` — 触发实例上游
- `mutgui/src/mutgui/_channel_impl.py` — 触发实例 + 当前 workaround
- `mutbot/src/mutbot/channel.py` — 同名 Declaration 触发碰撞
- `mutagent/src/mutagent/tools.py:144` — `Toolkit._customize_schema` 单下划线 stub（已有 `@impl` 用法，本 spec 顺带修复其潜在隐藏 bug）
- `mutagent/src/mutagent/builtins/web_toolkit_impl.py:107` — `@impl(WebToolkit._customize_schema)` 用例
- `mutbot/src/mutbot/ui/toolkit.py:155` — 另一处 `_customize_schema` 实现
- `mutobj/docs/specifications/bugfix-init-default-values.md` — 相邻问题（自定义 `__init__` 不调 super 导致默认值丢失），同样发生在 `__init__` 区域

## 复现方案

最小复现脚本（不依赖 mutgui/mutbot）：

```python
# repro.py
import mutobj

# 模拟 mutgui.Channel
class Channel(mutobj.Declaration):
    channel_id: int

    def __init__(self) -> None: ...

    async def send(self, message: dict) -> None: ...


# 模拟 mutbot.Channel —— 同名 Declaration，无 __init__ stub
import sys
import types
_other_module = types.ModuleType("other_pkg")
sys.modules["other_pkg"] = _other_module
exec(
    "import mutobj\n"
    "class Channel(mutobj.Declaration):\n"
    "    ch: int\n"
    "    session_id: str = ''\n",
    _other_module.__dict__,
)
OtherChannel = _other_module.Channel  # noqa


# 给"自己的" Channel.__init__ 写 impl —— 期望它装在第一个 Channel 上
@mutobj.impl(Channel.__init__)
def channel_init(self) -> None:
    print("[impl] channel_init called on", type(self).__name__)
    self.channel_id = 99


# 复现后果一：MyChannel() 不调用 channel_init
class MyChannel(Channel):
    pass

c = MyChannel()
print("MyChannel.channel_id =", getattr(c, "channel_id", "<MISSING>"))
# 期望: 99；实际: <MISSING>，且没看到 [impl] 输出

# 复现后果二：OtherChannel(ch=1) kwargs 报错（impl 被装到了 OtherChannel 上）
try:
    o = OtherChannel(ch=1, session_id="s")
    print("OtherChannel created:", o.ch, o.session_id)
except TypeError as e:
    print("OtherChannel TypeError:", e)
```

预期输出（bug 现状）：

```
MyChannel.channel_id = <MISSING>
OtherChannel TypeError: Channel.__init__() got an unexpected keyword argument 'ch'
```

修复后预期：

```
[impl] channel_init called on MyChannel
MyChannel.channel_id = 99
OtherChannel created: 1 s
```

注意：单 Declaration `Channel` 的场景下 fallback 也能"凑巧"找对，bug 不暴露。**必须有同名 Declaration 才会暴露**。这也是为什么之前 mutgui 自己的测试套全绿——只有一个 `Channel`，fallback 永远命中正确目标。

## 设计方案

### 双层修复

**Layer A — metaclass 让所有 namespace 显式声明的方法走注册（根治）**

`DeclarationMeta.__new__` 中处理 property / classmethod / staticmethod / 普通方法的四个循环里，当前都有 `if name.startswith("_"): continue`，这一刀切把 dunder（`__init__`、`__call__`）和单下划线私有方法（`_helper`）一起排除在声明-实现机制外。

**修复策略**：去掉单下划线跳过，只跳过会破坏 Python 类机制的少数保留 dunder。所有用户在类体里显式定义的方法（无论 `_` 开头与否）都正常走注册流程：打 `__mutobj_class__`、入 `_impl_chain`、加入 `_DECLARED_METHODS` 等。

```python
# 跳过 mutobj 保留的 dunder（这些是 Python 类协议钩子，注册它们会破坏类机制）
_MUTOBJ_RESERVED_DUNDERS = frozenset({
    "__new__",                  # 实例化协议，Declaration 自己用
    "__init_subclass__",        # 子类创建钩子
    "__class_getitem__",        # 泛型语法 cls[T]
    "__set_name__",             # 描述符协议
    "__subclasshook__",         # ABC 子类判断
    "__instancecheck__",        # isinstance 钩子
    "__subclasscheck__",        # issubclass 钩子
})

# 四个循环（property / classmethod / staticmethod / 普通方法）的过滤都改为：
if name in _MUTOBJ_RESERVED_DUNDERS:
    continue
# 其他所有 namespace 内的方法（包括 __init__ / __call__ / _helper）正常注册
```

**为什么单下划线方法也注册**（决策，原 Q1）：

- 实际依赖调研：五个仓库（mutobj/mutagent/mutbot/mutgui/mutio）的 Declaration 子类里只有 4 个 `_xxx` 方法，全部是"想被 `@impl` 覆盖"的语义：3 个 `__init__`（mutgui.Channel/ViewPort、mutbot.Session）+ 1 个 `Toolkit._customize_schema`（已有 `@impl(WebToolkit._customize_schema)`、`UIToolkit._customize_schema` 等用法）
- 没有任何"刻意依赖单下划线被跳过"的合法用法
- 语义上"能否被 `@impl` 覆盖"应取决于"是否在 Declaration 类体里显式定义"，而不是名字前缀——名字前缀和声明-实现分离机制正交
- 顺带修了 `Toolkit._customize_schema` 的潜在隐藏 bug：当前它被 metaclass 跳过 → `@impl(WebToolkit._customize_schema)` 走 fallback → 但因为类上没 stub 替换，`instance._customize_schema(...)` 实际可能拿到默认实现而非 `@impl` 注册的版本（实施时验证）

**同步清理 workaround**（决策，原 Q2）：

本 spec 实施完成、验证 mutgui 测试套全绿后，立即清理 mutgui `_channel_impl.py` 顶部的手动 `Channel.__init__.__mutobj_class__ = Channel` 赋值，避免误导后来者以为 dunder 必须手动绑定。

**Layer B — `@impl` fallback 多匹配时报错（防御性兜底）**

即使 Layer A 修好主路径，仍有边缘情况会走 fallback：

- 用户从其他模块 `from xxx import some_method` 后再 `@impl(some_method)`，原始 method 已被替换/装饰过，`__mutobj_class__` 可能丢失
- 用户传入的 `method` 本身是 `_impl_chain` 替换后的实现版本而非 stub
- 跨进程 / pickle 场景

`core.py:991-1002` 的当前 fallback 静默选首个匹配：

```python
# 当前
for cls in _class_registry.values():
    if cls.__name__ == class_name:
        target_cls = cls
        break
```

改为多匹配报错：

```python
candidates = [cls for cls in _class_registry.values() if cls.__name__ == class_name]
if len(candidates) > 1:
    raise ValueError(
        f"@impl({method_name!r}): ambiguous target — multiple Declaration "
        f"classes named {class_name!r} are registered: "
        f"{[f'{c.__module__}.{c.__qualname__}' for c in candidates]}. "
        f"This usually means the method does not have __mutobj_class__ set; "
        f"if it's a dunder method declared by the user, ensure it's defined "
        f"in the class body (mutobj should auto-tag it)."
    )
elif len(candidates) == 1:
    target_cls = candidates[0]
# else: target_cls 仍为 None → 沿用原有 __globals__ fallback
```

**Layer B 不影响合法用法**（决策，原 Q3）：调研 mutbot/mutagent/mutgui/mutio 四仓的所有 `@impl(...)` 用法，无任何"两个同名 Declaration 共存且都依赖 fallback 凑巧装对"的情况。Layer A 修好后，fallback 多匹配几乎一定是 bug，报错比静默错配安全得多。错误信息要包含候选类全路径，方便定位冲突。

### 实施前 baseline 验证结果（2026-04-24）

**bug 复现**（修正 repro 脚本顺序——让无 `__init__` stub 的同名 Channel 先注册，再注册带 stub 的）：

```
MyChannel.channel_id = <MISSING>
OtherChannel TypeError: Channel.__init__() got an unexpected keyword argument 'ch'
```

复现条件比想象中更严格：fallback 按 `_class_registry` 字典 values 顺序遍历，如果带 stub 的类先注册，fallback 凑巧能找对。**bug 触发依赖类加载顺序**——这也解释了为什么 mutgui 单独跑测试不暴露（只有一个 `Channel`），mutbot 起 server 才炸（导入顺序导致无 stub 的 mutbot.Channel 先于带 stub 的 mutgui.Channel 注册）。

**metaclass 跳过验证**（`_diag.py`）：

```
A.__init__       has __mutobj_class__: False  ← 跳过
A._helper        has __mutobj_class__: False  ← 跳过
A.public_method  has __mutobj_class__: True   ← 注册
_DECLARED_METHODS on A: None                  ← 注意：没有非 _ 方法时连 set 都不创建
_impl_chain keys for A: 只有 (A, 'public_method')
```

完全符合根因分析。

**`Toolkit._customize_schema` 当前行为**：实际跑 repro 显示 `@impl` 实际**生效了**（result = `'IMPL[foo]'`），且 `Toolkit._customize_schema.__mutobj_class__` 也被设置。这与上面 metaclass 跳过 `_xxx` 的事实矛盾——可能是因为 `@impl(WebToolkit._customize_schema)` 的 fallback 找到了 `Toolkit`/`WebToolkit`（同 qualname 下唯一），然后 `core.py:1021` 把 `__mutobj_class__` 反向写到了 method 上，加上 `setattr(target_cls, method_name, func)` 直接替换了类属性。所以"被跳过"≠"@impl 不生效"，只是绕了路、依赖 fallback 唯一性。

结论：`_customize_schema` 当前**碰巧能用**，没有隐藏 bug 需要修。但只要将来出现同名 Declaration（如别处也定义 `Toolkit`），同样会触发与 Channel 一样的错配。Layer A 修好后这条路径不再依赖 fallback，更稳。


## 消费者场景

| 消费者 | 场景 | 依赖的输出 | 验收标准 |
|--------|------|-----------|---------|
| mutgui `Channel` | `__init__` stub + `@impl` 注入 `channel_id` | metaclass 自动给 `__init__` 设置 `__mutobj_class__` | mutgui 单元测试 + 移除 `_channel_impl.py` 的手动 `__mutobj_class__` 赋值后行为不变 |
| mutbot `Channel` | 与 mutgui `Channel` 同名共存，靠 `Declaration` 默认 `__init__` 接收 kwargs | mutgui 的 `@impl` 不再误装到 mutbot.Channel 上 | `Channel(ch=42, session_id="s")` 正常构造；`session.connect` RPC 不报 TypeError |
| mutgui `View` / `ViewPort` | `__init__` stub + `@impl` 注入实现 | 同上 | mutgui 现有所有 demo / setup wizard 不受影响 |
| `Toolkit._customize_schema` | 单下划线方法 + `@impl` 覆盖（WebToolkit、UIToolkit 已有用例）| metaclass 注册 `_customize_schema` 后 `@impl` 真正生效 | 实施前先 repro 验证当前行为；实施后 `WebToolkit._customize_schema` 的 `@impl` 实现应被调用，工具描述包含动态注入内容 |
| 任意用户的 dunder stub | `__call__` / `__enter__` 等 | 同上 | 新写测试覆盖 `__init__` + `__call__` + 同名 Declaration 冲突 |

## 实施步骤清单

- [x] **准备：跑一遍最小复现脚本**，确认当前 bug 行为符合预期（`MyChannel.channel_id = <MISSING>`、`OtherChannel TypeError`），作为修复前 baseline
- [x] **Repro：验证 `Toolkit._customize_schema` 当前是否真的没生效**——构造一个测试场景：让 `WebToolkit._customize_schema` 的 `@impl` 实现打印或抛特征值，触发其调用路径，观察是否走到了 `@impl` 实现还是默认实现。结果记录到设计文档（追加在「设计方案」尾部，不删原内容）
- [x] **Layer A 实现**：`mutobj/src/mutobj/core.py`
  - [x] 在文件顶部（其他常量定义附近）加 `_MUTOBJ_RESERVED_DUNDERS` frozenset
  - [x] 修改 4 处下划线过滤（property、classmethod、staticmethod、普通方法循环），把 `if name.startswith("_"): continue` 改为 `if name in _MUTOBJ_RESERVED_DUNDERS: continue`
  - [x] 注意：`Declaration.__init__` 自身不在 `namespace` 里（它是 `Declaration` 类体内定义的，子类继承时不会出现在子类 namespace），不会被新逻辑误注册
- [x] **Layer B 实现**：`mutobj/src/mutobj/core.py:991-1002` `@impl` fallback 多匹配报错
- [x] **mutobj 单元测试**：`mutobj/tests/test_dunder_impl.py`（新文件）
  - [x] 用户显式 `__init__` stub 被 `@impl` 正确替换（基本场景）
  - [x] 同名 Declaration 共存时，`@impl(A.__init__)` 不会误装到 B.__init__
  - [x] 用户显式 `__call__` stub 被 `@impl` 正确替换
  - [x] 单下划线方法（如 `_helper`）也能被 `@impl` 覆盖
  - [x] 保留 dunder（`__new__` / `__init_subclass__` 等）在类体里定义不会破坏 Python 类机制
  - [x] Layer B：制造同名 Declaration + 强制 `__mutobj_class__` 缺失场景，断言 `@impl` 抛 `ValueError` 且错误信息含两个候选类全路径
- [x] **mutobj 测试套全绿**：`cd mutobj && pytest`，包括类型检查 `mypy src/mutobj`
- [x] **mutgui 验证**：`cd mutgui && pytest`，确保现有 `View` / `Channel` / `ViewPort` 行为不变
- [x] **清理 mutgui workaround**：`mutgui/src/mutgui/_channel_impl.py` 顶部移除 `Channel.__init__.__mutobj_class__ = Channel` 及其注释；再跑一次 `cd mutgui && pytest` 验证
