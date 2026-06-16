"""R004：@impl 函数签名必须与声明一致。

比较维度：async/sync 形态、参数数量/名称/种类、默认值、参数类型、返回类型。
- 常规方法：跳过 self 的类型检查
- staticmethod：不跳过第一个参数（没有 self）
- descriptor getter：只能有 1 个参数，返回类型与 descriptor 注解一致
- descriptor setter：必须有 2 个参数，value 类型与 descriptor 注解一致
- Implementation 子类：取 impl 类上的真实方法签名与声明对比，而非 bridge 泛型签名

抑制方式（按优先级）：
  - SignatureOverride：完全跳过
  - AsyncAllowed：仅跳过 async/sync 检查
严重度：error
"""

from __future__ import annotations

import importlib
import inspect
from typing import TYPE_CHECKING, Any, cast

from mutobj.core._classmeta import decl_meta_cache
from mutobj.core._declaration import Declaration, get_declaration_func
from mutobj.core._fields import AttributeDescriptor

from ._helpers import (
    R004,
    SEVERITY_ERROR,
    _EMPTY,  # pyright: ignore[reportPrivateUsage]
    ClassSourceInfo,
    function_definition_line,
    iter_own_impl_entries,
)
from mutobj import annotation_match

if TYPE_CHECKING:
    from mutobj.lint._api import LintMessage


def check_r004(infos: list[ClassSourceInfo]) -> list["LintMessage"]:
    from mutobj.lint._api import AsyncAllowed, LintMessage, SignatureOverride

    results: list[LintMessage] = []
    for info in infos:
        for key, entry in iter_own_impl_entries(info):
            if any(isinstance(meta, SignatureOverride) for meta in entry.metas):
                continue

            impl_func = _resolve_impl_method(key, entry)
            path, line, _def_line = function_definition_line(impl_func)
            if path is None:
                continue

            async_allowed = any(isinstance(meta, AsyncAllowed) for meta in entry.metas)
            mismatch = _signature_mismatch(info.cls, key, impl_func, async_allowed)
            if mismatch is None:
                continue

            results.append(LintMessage(
                path=str(path),
                line=line,
                column=0,
                rule_id=R004,
                message=mismatch,
                severity=SEVERITY_ERROR,
                symbol=f"@impl {info.class_name}.{key}",
            ))
    return results


def _resolve_impl_method(key: str, entry: Any) -> Any:
    """对 Implementation 子类条目取 impl 类上的真实方法签名。

    普通 @impl 直接返回 entry.func；Implementation 子类的 bridge 函数签名
    是泛型的 ``(decl, *args, **kwargs)``，需要取 impl 类上的真实方法对比。
    """
    source_module: str = entry.source_module
    if "::implementation::" not in source_module:
        return entry.func

    module_name, impl_cls_name = source_module.split("::implementation::", 1)
    try:
        mod = importlib.import_module(module_name)
    except ImportError:
        return entry.func
    impl_cls = getattr(mod, impl_cls_name, None)
    if impl_cls is None:
        return entry.func

    method_name = key.split(".", 1)[0]
    impl_method = getattr(impl_cls, method_name, None)
    if impl_method is None:
        return entry.func

    if key.endswith(".getter") and isinstance(impl_method, property):
        return impl_method.fget or entry.func
    if key.endswith(".setter") and isinstance(impl_method, property):
        return impl_method.fset or entry.func

    return impl_method


# ── signature comparison ───────────────────────────────────────────────────────

def _signature_mismatch(
    cls: type[Declaration],
    key: str,
    impl_func: Any,
    async_allowed: bool,
) -> str | None:
    if key.endswith(".getter") or key.endswith(".setter"):
        descriptor = cast(AttributeDescriptor, cls.__dict__[key.split(".", 1)[0]])
        return _descriptor_signature_mismatch(cls, key, descriptor, impl_func, async_allowed)

    decl_func = get_declaration_func(cls, key)
    if decl_func is None:
        return None
    return _callable_signature_mismatch(
        cls,
        key,
        decl_func,
        impl_func,
        async_allowed,
        skip_first_annotation=key not in decl_meta_cache[cls].staticmethods,
    )


def _descriptor_signature_mismatch(
    cls: type[Declaration],
    key: str,
    descriptor: AttributeDescriptor,
    impl_func: Any,
    async_allowed: bool,
) -> str | None:
    impl_sig = inspect.signature(impl_func)
    impl_params = list(impl_sig.parameters.values())
    accessor = key.split(".", 1)[1]

    if not async_allowed and inspect.iscoroutinefunction(impl_func):
        return f"{cls.__name__}.{key} 的 @impl 不能把同步 accessor 改成 async"

    if accessor == "getter":
        if len(impl_params) != 1:
            return f"{cls.__name__}.{key} 的 @impl 应只接收一个实例参数"
        return _compare_return_annotation(
            cls, key, descriptor.annotation, impl_sig.return_annotation,
            impl_func=impl_func,
        )

    if len(impl_params) != 2:
        return f"{cls.__name__}.{key} 的 @impl 应接收实例参数和值参数"

    value_param = impl_params[1]
    if not _annotations_match(descriptor.annotation, value_param.annotation, impl_func=impl_func):
        return (
            f"{cls.__name__}.{key} 的值参数类型不匹配："
            f"期望 {_describe_annotation(descriptor.annotation)}，"
            f"实际 {_describe_annotation(value_param.annotation)}"
        )

    return _compare_return_annotation(cls, key, None, impl_sig.return_annotation, impl_func=impl_func)


def _callable_signature_mismatch(
    cls: type[Declaration],
    key: str,
    decl_func: Any,
    impl_func: Any,
    async_allowed: bool,
    *,
    skip_first_annotation: bool,
) -> str | None:
    if (
        not async_allowed
        and inspect.iscoroutinefunction(decl_func) != inspect.iscoroutinefunction(impl_func)
    ):
        return f"{cls.__name__}.{key} 的 async/sync 形态与声明不一致"

    decl_sig = inspect.signature(decl_func)
    impl_sig = inspect.signature(impl_func)
    decl_params = list(decl_sig.parameters.values())
    impl_params = list(impl_sig.parameters.values())

    if len(decl_params) != len(impl_params):
        return (
            f"{cls.__name__}.{key} 的参数数量与声明不一致："
            f"期望 {len(decl_params)} 个，实际 {len(impl_params)} 个"
        )

    for index, (decl_param, impl_param) in enumerate(zip(decl_params, impl_params, strict=False)):
        if decl_param.kind != impl_param.kind:
            return (
                f"{cls.__name__}.{key} 的参数 {impl_param.name!r} 种类与声明不一致："
                f"期望 {decl_param.kind!s}，实际 {impl_param.kind!s}"
            )
        if decl_param.name != impl_param.name:
            return (
                f"{cls.__name__}.{key} 的参数名与声明不一致："
                f"期望 {decl_param.name!r}，实际 {impl_param.name!r}"
            )
        if _default_state(decl_param.default) != _default_state(impl_param.default):
            return f"{cls.__name__}.{key} 的参数 {impl_param.name!r} 默认值存在性与声明不一致"
        if (
            decl_param.default is not _EMPTY
            and impl_param.default is not _EMPTY
            and decl_param.default != impl_param.default
        ):
            return (
                f"{cls.__name__}.{key} 的参数 {impl_param.name!r} 默认值与声明不一致："
                f"期望 {decl_param.default!r}，实际 {impl_param.default!r}"
            )

        if skip_first_annotation and index == 0:
            continue

        if not _annotations_match(decl_param.annotation, impl_param.annotation, impl_func=impl_func):
            return (
                f"{cls.__name__}.{key} 的参数 {impl_param.name!r} 类型不匹配："
                f"期望 {_describe_annotation(decl_param.annotation)}，"
                f"实际 {_describe_annotation(impl_param.annotation)}"
            )

    return _compare_return_annotation(
        cls, key, decl_sig.return_annotation, impl_sig.return_annotation,
        impl_func=impl_func,
    )


def _compare_return_annotation(
    cls: type[Declaration],
    key: str,
    decl_raw: Any,
    impl_raw: Any,
    *,
    impl_func: object = None,
) -> str | None:
    if decl_raw is None and impl_raw in {_EMPTY, None}:
        return None
    if decl_raw is _EMPTY and impl_raw is _EMPTY:
        return None
    if not _annotations_match(decl_raw, impl_raw, impl_func=impl_func):
        return (
            f"{cls.__name__}.{key} 的返回类型与声明不一致："
            f"期望 {_describe_annotation(decl_raw)}，实际 {_describe_annotation(impl_raw)}"
        )
    return None


def _annotations_match(expected: Any, actual: Any, *, impl_func: object = None) -> bool:
    """R004 内部使用的类型比对，额外处理 _EMPTY 哨兵。

    先处理 _EMPTY 哨兵，再委托给公开的 ``_typing_utils.annotation_match``。
    """
    if expected is _EMPTY and actual is _EMPTY:
        return True
    if expected is _EMPTY or actual is _EMPTY:
        return False

    globals_dict: dict[str, Any] | None = None
    if impl_func is not None:
        module = inspect.getmodule(impl_func)
        if module is not None:
            globals_dict = vars(module)

    return annotation_match(expected, actual, globals=globals_dict)


def _default_state(default: Any) -> str:
    return "missing" if default is _EMPTY else "present"


def _describe_annotation(annotation: Any) -> str:
    if annotation is _EMPTY:
        return "<missing>"
    if annotation is None:
        return "None"
    if isinstance(annotation, str):
        return annotation
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation)
