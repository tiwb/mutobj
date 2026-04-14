# MutScript 安全子集设计规范

**状态**：🚫 取消（设计内容已迁移至 mutagent docs/design/sandbox.md，mutobj 不再实现沙箱）
**日期**：2026-04-03
**类型**：功能设计

## 需求

1. 定义一个 Python 语言子集，函数体内的语句范围
2. 子集代码可直接用标准 CPython 执行
3. 严格模式（沙箱）：运行时检查，非子集行为抛异常，保证不可逃逸
4. 编译模式（远期）：同一套规范可指导转译到 C/LLVM IR/WASM
5. 子集规范用 Declaration 模式表达，契合 mutobj 核心理念

### 设计目的

**不是限制，是导轨。** 核心场景是为 agent 提供代码执行环境——agent 基于 LLM 对 Python 的掌握编写代码，通过宿主注入的接口完成工作。子集的约束让 agent 不会浪费 token 尝试不可能的路径（如 import、逃逸），而是专注于用可用接口组合解决问题。

比 bash 更可控（能力边界是技术保证而非提示词约束），比纯 tool 更自由（组合逻辑不需要定义成 tool，循环/条件/数据处理是免费的）。

### 两个核心目标

- **Agent 沙箱**（当前优先）：通过 MCP tool 暴露代码执行能力，agent 代码在沙箱内运行，能力边界由宿主注入的接口决定——不注入就不存在
- **@impl 可编译基础**（远期）：符合子集的 @impl 函数体未来可编译优化。但真正需要编译的函数极少，不是当前重点

### 与 mutobj 的关系

mutobj 定义语言元素的 Declaration 范围（类型白名单、允许的操作）。上层项目选择如何消费这套规范：

- **mutagent**：用运行时检查模式消费，实现沙箱
- **未来的编译器**：用静态分析模式消费，生成目标代码

依赖方向正确：mutagent → mutobj，上层导入下层的子集定义。

## 设计方案

### 公共 API

mutobj 对外暴露三个概念：

| 概念 | 类型 | 职责 |
|------|------|------|
| `TypeSpec` | Declaration 子类 | 声明基础类型的可用属性和方法（白名单） |
| `ScriptEnv` | dict 子类 | 受保护的执行环境（冻结守卫函数和 `__builtins__`） |
| `Script` | 类 | 编译后的代码块，持有转换后的 code object |

内部实现（AST 转换器、守卫函数生成）不暴露为公共 API。

#### Script

构造即编译。接受源码字符串，完成 AST 检查、转换和编译：

```python
class Script:
    """MutScript 编译后的代码块。"""

    def __init__(self, source: str, filename: str = '<mutscript>'): ...

    def exec(self, env: ScriptEnv, locals: dict | None = None) -> None:
        """在受保护环境中执行。

        对齐 Python 内置 exec(code, globals, locals) 语义：
        - env 作为 globals（受保护的 dict）
        - locals 可选，不传则 locals=env（和 Python exec 一致）
        - 共享同一个 locals dict = REPL 会话
        """
        ...
```

#### ScriptEnv

dict 子类，构造方式和 dict 一致。冻结三个安全关键键（`__builtins__`、`.getattr`、`.setattr`），其余行为与普通 dict 完全相同：

```python
class ScriptEnv(dict):
    """Script 执行环境。dict 子类，冻结安全关键键。"""

    def __init__(self, *args, **kwargs):
        """构造方式与 dict 一致。"""
        ...
```

#### 使用示例

```python
from mutobj import Script, ScriptEnv

# 一次性执行
env = ScriptEnv(query=db.query, send=msg.send)
Script("print(1 + 2)").exec(env)

# REPL（共享 locals dict）
env = ScriptEnv(query=db.query)
state = {}
Script("data = query('SELECT ...')").exec(env, state)
Script("print(len(data))").exec(env, state)

# 同一个 env，不同 state（多个独立会话共享同一套能力）
s1, s2 = {}, {}
Script("x = 1").exec(env, s1)
Script("x = 2").exec(env, s2)
# s1['x'] == 1, s2['x'] == 2

# 表达式求值
env = ScriptEnv(width=100, margin=8)
Script("result = width * 2 + margin").exec(env)
# env['result'] == 208（无 locals 时变量存入 env）
```

#### TypeSpec 自动发现

TypeSpec 子类通过 mutobj 的 `discover_subclasses()` 机制自动注册，无需显式传入：

```python
# 定义 TypeSpec 子类（import 即注册）
class StrSpec(TypeSpec):
    def upper(self) -> str: ...
    def split(self, sep: str = ...) -> list: ...

# ScriptEnv 构造时自动发现所有已注册的 TypeSpec，构建守卫函数
env = ScriptEnv()  # 内部：遍历 TypeSpec 子类 → 构建白名单 → 生成守卫
```

### 安全性原理

安全子集的完整安全模型（封闭性定义、威胁分析、形式化证明）见 [`type-spec.md`](../design/type-spec.md#安全子集语言)。以下是关键结论的摘要：

**核心洞察**：属性访问（`.attr`）是唯一能产生不可预测来源对象引用的语法通道。运算符、下标、迭代等操作的返回类型由操作数类型决定，不会产生危险对象。

**封堵策略**：

| 逃逸途径 | 封堵方式 |
|----------|---------|
| `import` | AST 禁止 |
| `class` | AST 禁止 |
| `__builtins__` | 置空 |
| 属性链遍历 | AST 转换为守卫函数调用，白名单检查 |
| 绕过 AST 的危险方法 | 守卫函数透明替换为安全版本 |
| `__builtins__` 回填 | `ScriptEnv` 冻结关键键（见下文） |

**守卫函数不可覆盖**：`.getattr` / `.setattr` 使用非法标识符（以 `.` 开头），AST 转换生成的 `ast.Name(id='.getattr')` 在字节码层合法但源码层不可表达，用户代码无法引用、覆盖或删除。

### 子集语言定义

#### AST 语法限制

以下语法在 AST 层面被禁止（遇到对应节点直接拒绝）：

| 禁止语法 | AST 节点 | 原因 |
|----------|---------|------|
| `import` / `from ... import` | `Import`、`ImportFrom` | 引入新能力，破坏封闭性 |
| `class` | `ClassDef` | 子集面向函数体内的过程式逻辑，不需要类型定义。用户自定义类带来 metaclass、描述符协议、`__init_subclass__` 等隐式行为，增加审计复杂度。未来可按需放开 |

所有其他 Python 语句和表达式均允许：

| 语句 | 说明 |
|------|------|
| 赋值 | `x = expr`、`x += expr`、解包赋值 `a, b = expr`、walrus `:=` |
| 控制流 | `if`/`elif`/`else`、`for`/`while`/`break`/`continue` |
| 函数定义 | `def`（局部函数，含嵌套）、`lambda`、`async def` |
| 返回 | `return`、`yield`、`yield from` |
| 异常 | `raise`/`try`/`except`/`finally` |
| 上下文管理 | `with`/`async with` |
| 模式匹配 | `match`/`case` |
| 作用域 | `global`、`nonlocal` |
| 异步 | `await`、`async for` |
| 其他 | `assert`、`pass`、`del` |

**所有表达式均允许**：字面量、运算符、下标、函数调用、属性访问、推导式、生成器表达式、f-string、星号解包等。

安全性不依赖语法限制（import/class 除外），而依赖属性访问白名单。

#### 危险方法透明替换

以下方法属于白名单类型，但原生实现存在安全风险，由守卫函数**透明替换为安全版本**——用户代码语法不变，拿到的是安全实现：

| 类型 | 方法 | 风险 | 安全版本策略 |
|------|------|------|-------------|
| `str` | `format`、`format_map` | format 迷你语言支持 `{0.__class__.__bases__}` 等属性访问语法，由 C 运行时在字符串解析阶段执行，**完全绕过 AST 层的守卫** | 基于 `string.Formatter` 子类，重写 `get_field()` 拦截属性/下标遍历 |

**实现机制**：守卫函数在返回属性前查找替换表，命中则返回安全版本的绑定方法：

```python
import string

class SafeFormatter(string.Formatter):
    def get_field(self, field_name, args, kwargs):
        # get_field 是 format 迷你语言中属性/下标遍历的唯一入口
        if '.' in field_name or '[' in field_name:
            raise AttributeError(
                f"'{field_name}' is not a valid format field"
            )
        return super().get_field(field_name, args, kwargs)

_safe_fmt = SafeFormatter()

# 类型 → 方法名 → 安全实现
_safe_overrides = {
    (str, 'format'): lambda self, *a, **kw: _safe_fmt.format(self, *a, **kw),
    (str, 'format_map'): lambda self, mapping: _safe_fmt.vformat(self, (), mapping),
}
```

用户代码写法不变：
- `"hello {}".format(name)` — 正常工作
- `"{:.2f}".format(3.14)` — 正常工作
- `"{0.__class__}".format(obj)` — `AttributeError`

f-string 不受影响（属性访问在 AST 层可见，会被正常转换为守卫调用）。

### AST 转换

#### 属性读写对称守卫

属性读取和赋值**均经过白名单检查**：

```python
# 属性读取：obj.attr → .getattr(obj, 'attr')
Attribute(value, attr, Load) → Call(Name('.getattr'), [value, Constant(attr)])

# 属性赋值：obj.attr = val → .setattr(obj, 'attr', val)
Attribute(value, attr, Store) → Call(Name('.setattr'), [value, Constant(attr), val])

# 属性删除：del obj.attr → 不转换，原样执行
```

**设计说明**：

从安全角度，只有属性**读取**构成逃逸通道（详见 [type-spec.md 安全分析](../design/type-spec.md#属性赋值与删除的安全性分析)）。但第一版选择对赋值**同样施加白名单检查**，原因是行为一致性——如果允许 `obj.foo = 42` 但禁止读取 `obj.foo`（因为 `foo` 不在白名单中），这种"写得进去读不出来"的行为会造成困惑，尤其对 agent 来说会浪费 token 调试。

对称守卫使心智模型更简单：**白名单定义了类型上可以碰的属性，读写统一**。

属性删除不守卫——删除是罕见操作，且不产生引用，也不产生不对称困惑。**宿主责任**：属性删除不守卫是安全决策（不构成逃逸），但 `del obj.attr` 会触发 `__delattr__`，可能修改宿主注入对象的状态。如需保护属性删除，宿主应在对象的 `__delattr__` 中自行处理。

#### 守卫函数

两个守卫函数都使用非法标识符，存放在 globals 中，用户代码不可覆盖：

```python
def _make_guards(type_whitelist, safe_overrides):
    def _getattr_guard(obj, name):
        """属性读取守卫"""
        obj_type = type(obj)
        allowed = type_whitelist.get(obj_type)
        if allowed is None or name not in allowed:
            raise AttributeError(
                f"'{obj_type.__name__}' object has no attribute '{name}'"
            )
        # 危险方法 → 透明替换为安全版本
        override = safe_overrides.get((obj_type, name))
        if override is not None:
            return override.__get__(obj, obj_type)
        return getattr(obj, name)

    def _setattr_guard(obj, name, value):
        """属性赋值守卫"""
        obj_type = type(obj)
        allowed = type_whitelist.get(obj_type)
        if allowed is None or name not in allowed:
            raise AttributeError(
                f"'{obj_type.__name__}' object has no attribute '{name}'"
            )
        setattr(obj, name, value)

    return _getattr_guard, _setattr_guard
```

**异常设计原则**：所有守卫抛出的异常均为标准 Python 异常（`AttributeError`、`SyntaxError`、`TypeError`），且错误消息与 CPython 原生消息风格一致。这是有意为之——沙箱的使用者是 agent（LLM），当 agent 看到 `AttributeError: 'tuple' object has no attribute '__class__'`，它会将此理解为"这个属性不存在"，从而转向其他可用接口；如果看到自定义异常如 `SubsetViolation: Attribute '__class__' is not allowed`，agent 会理解为"这个属性存在但被限制了"，可能浪费 token 尝试绕过限制。

### 内部架构

以下为 Script / ScriptEnv 的内部实现，不暴露为公共 API。

#### 两阶段流程

```
Script(source)           ScriptEnv(inject)         Script.exec(env, locals)
      ↓                        ↓                         ↓
[AST 检查+转换]          [构建受保护 dict]           [exec(code, env, locals)]
      ↓                        ↓
禁止 import/class        空 __builtins__（冻结）
.attr 读取 → .getattr()  .getattr/.setattr（冻结）
.attr 赋值 → .setattr()  安全内置函数 + 用户注入
```

#### 阶段 1：AST 检查与转换（Script 构造函数内部）

使用 `ast.NodeTransformer`，在 `Script.__init__` 中完成：

1. 遇到 `Import`/`ImportFrom`/`ClassDef` 节点 → 抛出 `SyntaxError`
2. 遇到 `Attribute(Load)` → 转换为 `.getattr()` 调用
3. 遇到 `Attribute(Store)` → 转换为 `.setattr()` 调用
4. 其他节点原样保留（含属性删除）

转换失败抛出 `SyntaxError` 异常（含行号和原因）。

#### 阶段 2：受控执行（Script.exec 内部）

##### `ScriptEnv`：防止 `__builtins__` 回填逃逸

CPython 的 `exec(code, globals)` 在 globals 字典中**不存在** `__builtins__` 键时会自动注入真实 `builtins` 模块，导致完整逃逸。详细攻击路径分析见 [`type-spec.md`](../design/type-spec.md#条件-2-的实现builtins-回填漏洞与封堵)。

封堵方案：`ScriptEnv` 是自定义 dict 子类，在字典层面冻结安全关键键：

```python
class ScriptEnv(dict):
    """Script 执行环境。dict 子类，冻结安全关键键的删除和覆盖。

    构造方式与 dict 一致。所有全局变量读写最终经过 dict 的
    __getitem__/__setitem__/__delitem__。无论 AST 层面用何种语法
    （del、赋值、for target、except as、walrus 等），最终都会落到
    这两个方法上，因此在字典层一次性封堵。
    """
    _FROZEN = frozenset({'__builtins__', '.getattr', '.setattr'})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 冻结键通过 dict.__setitem__ 绕过保护
        dict.__setitem__(self, '__builtins__', {})
        dict.__setitem__(self, '.getattr', _build_getattr_guard())
        dict.__setitem__(self, '.setattr', _build_setattr_guard())
        # 安全内置函数（不覆盖用户同名键）
        for k, v in _safe_builtins.items():
            if k not in self:
                dict.__setitem__(self, k, v)

    def __delitem__(self, key):
        if key in self._FROZEN:
            return  # 静默忽略
        super().__delitem__(key)

    def __setitem__(self, key, value):
        if key in self._FROZEN:
            return  # 静默忽略
        super().__setitem__(key, value)
```

**为什么在字典层封堵而非 AST 层**：对 `__builtins__` 名称的写操作在 AST 层有无穷多种表达，而所有语法最终都经过 `dict.__setitem__` 或 `dict.__delitem__`，在字典层一次性封堵。详见 [`type-spec.md`](../design/type-spec.md#条件-2-的实现builtins-回填漏洞与封堵)。

**`__builtins__` 原地修改（如 `__builtins__["eval"] = 42`）不需要防范**：agent 只能往字典里塞它已经能引用到的对象，而这些对象中没有危险函数。原地修改不产生新能力，不构成权限逃逸——防范的目标是阻止逃逸，不是阻止 agent 自己折腾自己。

**同时冻结 `.getattr` 和 `.setattr`**：虽然非法标识符已经让源码层无法引用这两个键，但 `ScriptEnv` 提供了额外一层纵深防御。

##### 执行环境

`Script.exec` 内部调用 Python 内置 `exec(code, env, locals)`，对齐 Python 语义：

```python
class Script:
    def exec(self, env: ScriptEnv, locals: dict | None = None) -> None:
        """在受保护环境中执行。"""
        builtins.exec(self._code, env, locals)
```

`ScriptEnv` 构造时自动组装完整的执行环境：

```python
env = ScriptEnv(query=db.query, send=msg.send)

# env 内部包含（通过 __init__ 自动注入）：
# '.getattr': _getattr_guard     # 冻结
# '.setattr': _setattr_guard     # 冻结
# '__builtins__': {}              # 冻结
# 'len': len, 'range': range, ...# 安全内置函数
# 'query': db.query              # 用户注入
# 'send': msg.send               # 用户注入
```

安全内置函数的完整列表：

```python
_safe_builtins = {
    'len': len, 'range': range, 'enumerate': enumerate,
    'zip': zip, 'map': map, 'filter': filter,
    'sorted': sorted, 'reversed': reversed,
    'min': min, 'max': max, 'sum': sum,
    'any': any, 'all': all, 'abs': abs, 'round': round,
    'isinstance': isinstance, 'print': print,
    'int': int, 'float': float, 'str': str, 'bool': bool,
    'list': list, 'dict': dict, 'tuple': tuple, 'set': set,
    'bytes': bytes, 'repr': repr,
    'chr': chr, 'ord': ord, 'hex': hex, 'bin': bin, 'oct': oct,
    'hash': hash, 'id': id,  # id 返回内存地址，不构成逃逸但存在信息泄露。威胁模型聚焦于防逃逸，不防信息泄露；如需更严格的隔离，宿主可在构造 ScriptEnv 时覆盖
    'iter': iter, 'next': next,

    # 受限内置函数（见下文说明）
    'type': _safe_type,      # 仅允许单参数调用（类型查询）
    'callable': callable,    # 仅查询，不构成逃逸。与 dir 不同：dir 暴露完整属性名列表，是逃逸探测的路线图；callable 只返回一个 bool，信息量等价于 agent 直接尝试调用后看 TypeError

    # 异常类型
    'Exception': Exception, 'ValueError': ValueError,
    'TypeError': TypeError, 'KeyError': KeyError,
    'IndexError': IndexError, 'AttributeError': AttributeError,
    'RuntimeError': RuntimeError, 'StopIteration': StopIteration,
    'ZeroDivisionError': ZeroDivisionError,
    'NotImplementedError': NotImplementedError,
    'OverflowError': OverflowError,
}
```

注意：宿主业务接口通过 ScriptEnv 构造时传入，不在 `_safe_builtins` 中：

```python
env = ScriptEnv(query=db.query, send=msg.send)
# 等价于先填充 _safe_builtins，再 update({'query': db.query, 'send': msg.send})
```

#### 受限内置函数

部分内置函数存在多态调用风险，需包装为安全版本：

| 函数 | 风险 | 安全版本 |
|------|------|---------|
| `type` | 三参数调用 `type('X', (object,), {...})` 等价于 `class` 语句，绕过 AST 禁令 | 只允许单参数调用（类型查询），其余抛出 `TypeError` |

```python
_builtin_type = type

def _safe_type(*args):
    """只允许 type(obj) 类型查询，禁止 type(name, bases, dict) 动态建类"""
    if len(args) != 1:
        raise TypeError(
            "type() takes 1 argument"
        )
    return _builtin_type(args[0])
```

#### 显式排除的危险函数

以下 Python 内置函数**不注入**到 `ScriptEnv` 中。agent 代码调用时会得到 `NameError`——与未定义的变量行为一致。

| 函数 | 不注入的原因 |
|------|------------|
| `eval`、`exec`、`compile` | 执行任意代码，完全绕过 AST 转换和白名单检查 |
| `__import__`、`importlib` | 引入新模块，等价于 `import` 语句 |
| `getattr`、`setattr`、`delattr` | 绕过 `.getattr` / `.setattr` 守卫函数，直接访问任意属性 |
| `open` | 文件系统访问，超出沙箱能力边界 |
| `globals`、`locals`、`vars` | 暴露 globals 字典引用，可通过 `globals()['.getattr'] = ...` 覆盖守卫函数 |
| `dir` | 暴露对象的全部属性名，帮助 agent 探测白名单外的属性 |
| `breakpoint`、`input` | 阻塞执行或引入外部输入 |
| `exit`、`quit` | 终止解释器进程 |
| `memoryview` | 提供底层内存访问 |
| `super` | 无 `class` 语句时无意义，且可能暴露 MRO 链 |
| `classmethod`、`staticmethod`、`property` | 描述符协议，无 `class` 语句时无意义 |

**设计原则**：不注入 = 不存在。agent 看到 `NameError: name 'eval' is not defined`，会将其理解为"这个环境里没有这个函数"，而非"这个函数被禁用了"。这避免 agent 浪费 token 尝试绕过限制。

#### REPL 模式

通过共享 `locals` dict 实现跨调用状态保持，无需专门的 Session 类：

```python
env = ScriptEnv(query=db.query)
state = {}  # 共享的 locals

Script("x = query('SELECT ...')").exec(env, state)  # x 存入 state
Script("print(len(x))").exec(env, state)             # 从 state 中找到 x
```

- 不传 `locals` 时，`locals=env`（和 Python `exec` 一致），变量存入 env
- 传入同一个 `locals` dict = REPL 会话
- 不同的 `locals` dict = 独立会话（共享同一套能力但状态隔离）
- 会话生命周期由宿主管理（丢弃 dict 即销毁会话）

### 类型白名单（用 Declaration 表达）

每种子集内的类型，用 Declaration 子类声明其可用的属性和方法。dunder 和非 dunder 统一处理——白名单中有就能访问，没有就不能。

```python
class TypeSpec(mutobj.Declaration):
    """子集类型的基类"""
    ...

class IntSpec(TypeSpec):
    """int 类型的子集规范"""
    def bit_length(self) -> int: ...
    def to_bytes(self, length: int, byteorder: str) -> bytes: ...

class StrSpec(TypeSpec):
    """str 类型的子集规范"""
    def upper(self) -> str: ...
    def lower(self) -> str: ...
    def strip(self, chars: str = ...) -> str: ...
    def split(self, sep: str = ..., maxsplit: int = ...) -> list: ...
    def join(self, iterable: list) -> str: ...
    def replace(self, old: str, new: str, count: int = ...) -> str: ...
    def startswith(self, prefix: str) -> bool: ...
    def endswith(self, suffix: str) -> bool: ...
    def find(self, sub: str) -> int: ...
    def count(self, sub: str) -> int: ...
    def encode(self, encoding: str = ...) -> bytes: ...
    def format(self, *args: object, **kwargs: object) -> str: ...
    def format_map(self, mapping: dict) -> str: ...
    def isdigit(self) -> bool: ...
    def isalpha(self) -> bool: ...
    # ... 完整列表在实施阶段补全

class ListSpec(TypeSpec):
    """list 类型的子集规范"""
    def append(self, item: object) -> None: ...
    def extend(self, iterable: object) -> None: ...
    def insert(self, index: int, item: object) -> None: ...
    def pop(self, index: int = ...) -> object: ...
    def remove(self, item: object) -> None: ...
    def sort(self, key: object = ..., reverse: bool = ...) -> None: ...
    def reverse(self) -> None: ...
    def index(self, item: object) -> int: ...
    def count(self, item: object) -> int: ...
    def copy(self) -> list: ...
    def clear(self) -> None: ...

class DictSpec(TypeSpec):
    """dict 类型的子集规范"""
    def get(self, key: object, default: object = ...) -> object: ...
    def keys(self) -> object: ...
    def values(self) -> object: ...
    def items(self) -> object: ...
    def update(self, other: object = ..., **kwargs: object) -> None: ...
    def pop(self, key: object, default: object = ...) -> object: ...
    def setdefault(self, key: object, default: object = ...) -> object: ...
    def clear(self) -> None: ...
    def copy(self) -> dict: ...

class SetSpec(TypeSpec):
    """set 类型的子集规范"""
    def add(self, item: object) -> None: ...
    def remove(self, item: object) -> None: ...
    def discard(self, item: object) -> None: ...
    def pop(self) -> object: ...
    def clear(self) -> None: ...
    def union(self, other: object) -> set: ...
    def intersection(self, other: object) -> set: ...
    def difference(self, other: object) -> set: ...
    def issubset(self, other: object) -> bool: ...
    def issuperset(self, other: object) -> bool: ...

class TupleSpec(TypeSpec):
    """tuple 类型的子集规范"""
    def index(self, item: object) -> int: ...
    def count(self, item: object) -> int: ...

class BytesSpec(TypeSpec):
    """bytes 类型的子集规范"""
    def decode(self, encoding: str = ...) -> str: ...
    # ... 按需扩展

class BoolSpec(TypeSpec):
    """bool 类型的子集规范 — 继承 IntSpec"""
    ...

class NoneSpec(TypeSpec):
    """NoneType 的子集规范 — 无可用方法"""
    ...
```

**设计说明**：

- 运算符（`+`、`*`、`==` 等）不经过属性访问，由 Python 运行时直接调度，无需在白名单中声明
- 下标访问（`obj[key]`）同理，不经过属性访问
- 只有 `.attr` 语法触发白名单检查
- `TypeSpec` 继承 `Declaration`，利用 mutobj 的方法注册和内省机制
- 白名单可通过 `@impl` 扩展——上层项目可为子集类型添加新的允许方法
- 宿主注入的自定义对象需注册对应的 `TypeSpec`，声明允许的属性

**渐进扩展**：第一版 TypeSpec 覆盖范围是最小可用集（如 `BytesSpec` 仅声明 `decode`），后续通过 `@impl` 扩展机制按需添加方法。由于守卫函数默认拒绝（deny-by-default），未声明的方法自动不可访问，TypeSpec 的完整性影响**可用性**而非**安全性**。

### 异常策略

沙箱**不使用自定义异常类**，所有错误均抛出标准 Python 异常：

| 场景 | 异常类型 | 示例消息 |
|------|---------|---------|
| 属性访问被拒 | `AttributeError` | `'tuple' object has no attribute '__class__'` |
| AST 禁止语法 | `SyntaxError` | `import statements are not supported` |
| `type()` 多参数调用 | `TypeError` | `type() takes 1 argument` |
| 未注入的函数 | `NameError` | `name 'eval' is not defined`（CPython 原生行为，无需代码） |

**设计原因**：沙箱的使用者是 agent（LLM）。标准异常让 agent 认为"这个东西不存在"或"用法不对"，从而转向可用接口。自定义异常（如 `SubsetViolation`）会让 agent 意识到"存在但被限制"，可能浪费 token 尝试绕过。消息风格与 CPython 原生错误一致，进一步强化"不存在"的认知。

## 测试计划

### 正向测试：合法代码正常执行

- 基础类型操作：`"hello".upper()`、`[1,2,3].append(4)`、`{"a":1}.get("b", 0)`
- 控制流：循环、条件、异常处理、函数定义
- 宿主注入接口调用
- REPL 跨步骤状态保持（共享 locals dict）
- f-string 内的属性访问（经过 AST 转换）
- `type(obj)` 单参数类型查询

### 逃逸测试：已知攻击路径全部被拦截

所有逃逸尝试应产生标准 Python 异常，消息风格与 CPython 一致：

- dunder 链逃逸：`().__class__.__bases__[0].__subclasses__()` → `AttributeError: 'tuple' object has no attribute '__class__'`
- frame 逃逸：`(lambda: 0).__code__` → `AttributeError: 'function' object has no attribute '__code__'`
- import 语句：`import os` → `SyntaxError`
- class 语句：`class X: pass` → `SyntaxError`
- 动态建类：`type('X', (object,), {})` → `TypeError: type() takes 1 argument`
- format 逃逸：`"{0.__class__}".format(obj)` → `AttributeError`
- 守卫覆盖尝试：确认 `.getattr` / `.setattr` 不可通过任何语法引用

### 排除函数测试：未注入的危险函数返回 NameError

每个排除函数都应返回 `NameError: name 'xxx' is not defined`，与普通未定义变量行为一致：

- `eval("1+1")` → `NameError`
- `exec("x=1")` → `NameError`
- `compile("x", "", "exec")` → `NameError`
- `__import__("os")` → `NameError`
- `getattr([], "append")` → `NameError`
- `setattr(obj, "x", 1)` → `NameError`
- `delattr(obj, "x")` → `NameError`
- `open("file.txt")` → `NameError`
- `globals()` → `NameError`
- `locals()` → `NameError`
- `vars()` → `NameError`
- `dir([])` → `NameError`
- `breakpoint()` → `NameError`
- `input()` → `NameError`
- `super()` → `NameError`

### `__builtins__` 攻击路径测试

验证 `ScriptEnv` 正确封堵所有 `__builtins__` 相关攻击：

- `del __builtins__` → 静默忽略，`__builtins__` 仍存在于 globals 中，后续步骤 `eval` 仍为 `NameError`
- `__builtins__ = {"eval": 42}` → 静默忽略，`__builtins__` 不变
- `for __builtins__ in [1,2,3]: pass` → 静默忽略
- `except E as __builtins__` → 静默忽略
- `(__builtins__ := {"eval": 42})` → 静默忽略
- `__builtins__["eval"] = len` → 允许（原地修改不构成逃逸，agent 只能塞已有对象）
- REPL 跨步骤验证：step1 执行 `del __builtins__`，step2 确认 `eval` 仍为 `NameError`
- `.getattr` 和 `.setattr` 键同样不可删除/覆盖

### 对称性测试：读写行为一致

- 白名单内属性：读写均成功
- 白名单外属性：读写均拒绝，错误信息一致（`AttributeError`）
- 未注册类型：读写均拒绝（`AttributeError`）

### 边界测试

- 嵌套属性访问：`obj.a.b.c` 每一步都经过守卫
- 属性删除：不经过守卫，正常执行
- 描述符交互：白名单属性是 property 时的行为

### 性能基线测试

AST 转换后每次属性访问多一次函数调用 + 字典查找。建立基线认知，不设硬指标：

- 循环密集场景：`for i in range(10000): "hello".upper()` — 对比转换前后耗时
- 嵌套属性场景：`obj.a.b.c` 三次守卫调用的累积开销
- 纯计算场景（无属性访问）：`sum(range(10000))` — 确认无额外开销

## 已知不处理的边界

以下场景在当前设计中**不处理**，记录于此供未来评估：

| 场景 | 分析 | 影响 |
|------|------|------|
| `__del__` 回调 | agent 代码定义的局部对象被 GC 回收时触发 `__del__`，此时 frame 的 builtins 环境可能与沙箱不同 | 极端边界情况。agent 代码中的局部 class 已被 AST 禁止，因此无法定义 `__del__`；内置类型和宿主注入对象的 `__del__` 由宿主负责 |
| `@impl` 返回类型安全 | Declaration 子类的 `@impl` 可能返回任意类型的对象 | `@impl` 作者对返回值安全性负责，不在沙箱保证范围内。守卫的 deny-by-default 提供了保底：即使返回未知类型，其属性访问仍被拒绝 |
| 资源限制（CPU/内存） | `while True: pass` 或 `range(10**18)` 等代码会耗尽 CPU/内存 | 不属于逃逸问题，由宿主通过超时、内存上限等机制处理。沙箱保证的是"不能做什么"（能力边界），不保证"不会消耗多少资源" |

## 关键参考

- `mutobj/docs/design/type-spec.md` — 安全模型的形式化定义与证明
- `mutobj/src/mutobj/core.py` — mutobj 核心实现，Declaration/impl/Extension 机制
- `mutobj/docs/design/architecture.md` — mutobj 架构设计理念
- Python `ast` 模块文档 — AST 节点类型参考
- Python `compile()` + `exec()` — 受控执行的基础设施
