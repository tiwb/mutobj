from __future__ import annotations

import importlib
import re
import sys
from typing import Any, ClassVar as ClassVarType, ForwardRef, get_origin as _typing_get_origin


def _resolve_annotation_name(base: str, module_name: str) -> Any:
    """Resolve a string annotation base name in module globals."""
    parts = [part for part in base.split(".") if part]
    if not parts:
        return None

    root_name = parts[0]
    root: Any = None
    root_found = False

    module = sys.modules.get(module_name)
    if module is not None:
        module_globals = vars(module)
        if root_name in module_globals:
            root = module_globals[root_name]
            root_found = True

    if not root_found and root_name == "typing":
        root = importlib.import_module("typing")
        root_found = True

    if not root_found:
        return None

    obj = root
    for part in parts[1:]:
        try:
            obj = getattr(obj, part)
        except AttributeError:
            return None
    return obj


def is_classvar(annotation: Any, module_name: str) -> bool:
    if annotation is ClassVarType:
        return True
    origin = _typing_get_origin(annotation)
    if origin is not None and origin is ClassVarType:
        return True

    if isinstance(annotation, str):
        ann = annotation.strip()
        bracket = ann.find("[")
        base = ann[:bracket].strip() if bracket != -1 else ann

        if base == "ClassVar" or base == "typing.ClassVar":
            return True

        obj = _resolve_annotation_name(base, module_name)
        if obj is ClassVarType:
            return True
        origin2 = _typing_get_origin(obj)
        if origin2 is not None and origin2 is ClassVarType:
            return True

    return False


# ── 注解解析与比对 ─────────────────────────────────────────────────────────


def annotation_resolve(annotation: Any, globals: dict[str, Any]) -> Any:
    """将字符串注解解析为实际类型。

    处理 PEP 563 嵌套引号：
    ``"str | Foo"`` 被 PEP 563 存为 ``"'str | Foo'"``，
    本函数反复 eval 直到不再变化或不再是字符串。

    Args:
        annotation: 待解析的注解（字符串或已解析的类型）。
        globals: 解析时使用的命名空间字典。

    Returns:
        解析后的类型对象，或无法解析时返回 :class:`ForwardRef`。
    """
    if not isinstance(annotation, str):
        return annotation
    try:
        result = eval(annotation, globals)
        # 反复 eval 以处理 PEP 563 嵌套引号
        while isinstance(result, str) and result != annotation:
            annotation = result
            result = eval(annotation, globals)
        return result
    except NameError:
        return ForwardRef(annotation)


def annotation_match(
    expected: Any,
    actual: Any,
    *,
    globals: dict[str, Any] | None = None,
) -> bool:
    """比较两个类型注解是否等价。

    比对策略（按优先级）：
    1. 直接相等
    2. 通过 ``annotation_resolve`` 解析字符串注解后比较
    3. 字符串归一化比较（处理 PEP 563 嵌套引号与前向引用）

    Args:
        expected: 声明侧注解。
        actual: 实现侧注解。
        globals: 解析字符串注解时使用的命名空间字典。

    Returns:
        True 如果注解等价，False 否则。
    """
    if expected == actual:
        return True

    if globals is not None and (isinstance(expected, str) or isinstance(actual, str)):
        resolved_expected = annotation_resolve(expected, globals)
        resolved_actual = annotation_resolve(actual, globals)
        if resolved_expected is not expected or resolved_actual is not actual:
            if resolved_expected == resolved_actual:
                return True

    # 字符串归一化兜底：声明侧 "str | Foo" 被 PEP 563 存为 "'str | Foo'"
    # impl 侧 str | Foo 被存为 "str | Foo"。归一化后都应变成 str | Foo。
    if globals is not None and (isinstance(expected, str) or isinstance(actual, str)):
        return _annotation_normalize(expected) == _annotation_normalize(actual)

    return False


def _annotation_normalize(annotation: Any) -> str:
    """将注解归一化为无模块前缀、无冗余引号的字符串形式。

    - 剥除外层嵌套引号：``"'str | Foo'"`` → ``"str | Foo"``
    - 去除注解内单词标识符的引号（前向引用标记）：
      ``"Callable[..., 'Foo']"`` → ``"Callable[..., Foo]"``
    - 非字符串类型转为简单字符串
    """
    if isinstance(annotation, str):
        s = annotation
        # 剥除外层嵌套引号
        while len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
            s = s[1:-1]
        # 去除内层标识符（\w+）的引号：'Foo' → Foo
        s = re.sub(r"[\"'](\w+)[\"']", r"\1", s)
        return s
    return _type_to_simple_str(annotation)


def _type_to_simple_str(annotation: Any) -> str:
    """将 typing construct 转为无模块前缀的简单字符串。

    ``collections.abc.Callable[..., Foo]`` → ``"Callable[..., Foo]"``
    """
    import typing as _typing

    origin = _typing.get_origin(annotation)
    if origin is not None:
        args = _typing.get_args(annotation)
        args_str = ", ".join(_type_to_simple_str(a) for a in args)
        return f"{origin.__name__}[{args_str}]"
    if isinstance(annotation, type):
        return annotation.__name__
    if annotation is Ellipsis:
        return "..."
    return repr(annotation)
