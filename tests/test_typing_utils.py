"""annotation_resolve / annotation_match 基础单元测试。

测试 mutobj.core._typing_utils 的类型比对 API。
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, ForwardRef

from mutobj import annotation_match, annotation_resolve


# ── 测试用的类型和 globals ──

class Foo:
    pass


def _dummy_func() -> None:
    pass


_GLOBALS: dict[str, Any] = vars(inspect.getmodule(_dummy_func))


# ── annotation_resolve ────────────────────────────────────────────────────────

class TestAnnotationResolve:
    """annotation_resolve 单元测试。"""

    def test_non_string_passthrough(self) -> None:
        """非字符串注解原样返回。"""
        assert annotation_resolve(42, _GLOBALS) == 42
        assert annotation_resolve(Foo, _GLOBALS) is Foo

    def test_simple_type_resolution(self) -> None:
        """简单类型名字符串 → eval 解析为类型。"""
        assert annotation_resolve("int", _GLOBALS) is int

    def test_unresolvable_name_returns_forwardref(self) -> None:
        """无法解析的标识符 → 返回 ForwardRef。"""
        result = annotation_resolve("NoSuchType", _GLOBALS)
        assert isinstance(result, ForwardRef)
        assert result.__forward_arg__ == "NoSuchType"

    def test_union_type_resolution(self) -> None:
        """联合类型字符串 → eval 解析为 UnionType。"""
        assert annotation_resolve("str | Foo", _GLOBALS) == str | Foo

    def test_pep563_nested_quoting_union(self) -> None:
        """PEP 563 嵌套引号：\"'str | Foo'\" → 递归 eval → str | Foo 类型。"""
        assert annotation_resolve("'str | Foo'", _GLOBALS) == str | Foo

    def test_pep563_nested_quoting_single_type(self) -> None:
        """PEP 563 嵌套引号：\"'Foo'\" → 递归 eval → Foo 类型。"""
        assert annotation_resolve("'Foo'", _GLOBALS) is Foo

    def test_deeply_nested_quoting(self) -> None:
        """多次嵌套引号也应全部剥开。"""
        assert annotation_resolve("\"'int'\"", _GLOBALS) is int

    def test_non_resolvable_nested_string(self) -> None:
        """嵌套引号剥开后仍是无法解析的 → 返回 ForwardRef。"""
        result = annotation_resolve("'NoSuch'", _GLOBALS)
        assert isinstance(result, ForwardRef)
        assert result.__forward_arg__ == "NoSuch"


# ── annotation_match ─────────────────────────────────────────────────────────

class TestAnnotationMatch:
    """annotation_match 单元测试。"""

    def test_identical_non_string(self) -> None:
        assert annotation_match(int, int) is True
        assert annotation_match(Foo, Foo) is True

    def test_different_non_string(self) -> None:
        assert annotation_match(int, str) is False

    def test_identical_strings(self) -> None:
        assert annotation_match("int", "int") is True

    def test_different_strings(self) -> None:
        assert annotation_match("int", "str") is False

    def test_string_vs_type_resolved(self) -> None:
        """字符串 \"int\" vs 类型 int → 通过解析后匹配。"""
        assert annotation_match("int", int, globals=_GLOBALS) is True

    def test_string_vs_type_mismatch_resolved(self) -> None:
        """字符串 \"int\" vs 类型 str → 解析后不匹配。"""
        assert annotation_match("int", str, globals=_GLOBALS) is False

    def test_pep563_nested_quoting_union_vs_type(self) -> None:
        """PEP 563: \"'str | Foo'\" vs str | Foo → 应匹配。"""
        assert annotation_match("'str | Foo'", str | Foo, globals=_GLOBALS) is True

    def test_pep563_nested_quoting_union_vs_string(self) -> None:
        """PEP 563: \"'str | Foo'\" vs \"str | Foo\"（两边都是字符串）→ 应匹配。"""
        assert annotation_match("'str | Foo'", "str | Foo", globals=_GLOBALS) is True

    def test_pep563_nested_quoting_single_type(self) -> None:
        """PEP 563: \"'Foo'\" vs Foo → 应匹配。"""
        assert annotation_match("'Foo'", Foo, globals=_GLOBALS) is True

    def test_pep563_nested_quoting_both_nested(self) -> None:
        """PEP 563: 两边都有嵌套引号也应对齐。"""
        assert annotation_match("'int'", "'int'", globals=_GLOBALS) is True

    def test_without_globals_no_resolution(self) -> None:
        """不传 globals 时不尝试解析，纯值比对。"""
        assert annotation_match("int", int) is False

    def test_callable_string_vs_type_identical(self) -> None:
        """Callable[..., Foo] 字符串 vs 类型 — 解析后匹配。"""
        assert annotation_match(
            "Callable[..., Foo]", Callable[..., Foo], globals=_GLOBALS,
        ) is True

    def test_pep563_callable_nested_quoting(self) -> None:
        """PEP 563: \"Callable[..., 'Foo']\" vs Callable[..., Foo]
        → 应通过归一化匹配。
        """
        assert annotation_match(
            "Callable[..., 'Foo']", Callable[..., Foo], globals=_GLOBALS,
        ) is True

    def test_callable_mismatch(self) -> None:
        """Callable[..., Foo] vs Callable[..., int] → 不匹配。"""
        assert annotation_match(
            Callable[..., Foo], Callable[..., int], globals=_GLOBALS,
        ) is False

    def test_callable_string_mismatch(self) -> None:
        """不同 Callable 的字符串形式也不匹配。"""
        assert annotation_match(
            "Callable[..., Foo]", "Callable[..., int]", globals=_GLOBALS,
        ) is False

