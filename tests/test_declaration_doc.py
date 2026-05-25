"""Tests for get_declaration_doc / get_declaration_func."""

import mutobj
from mutobj import get_declaration_doc, get_declaration_func


class TestGetDeclarationDoc:
    """get_declaration_doc 基本功能测试"""

    def test_returns_declaration_docstring(self):
        """声明方法有 docstring 时，能正确取回"""
        class Svc(mutobj.Declaration):
            def run(self) -> str:
                """Run the service."""
                ...

        assert get_declaration_doc(Svc, "run") == "Run the service."

    def test_returns_none_for_no_docstring(self):
        """声明方法没有 docstring 时，返回 None"""
        class Svc2(mutobj.Declaration):
            def run(self) -> str: ...

        assert get_declaration_doc(Svc2, "run") is None

    def test_returns_none_for_nonexistent_method(self):
        """查询不存在的方法时，返回 None"""
        class Svc3(mutobj.Declaration):
            def run(self) -> str:
                """Run."""
                ...

        assert get_declaration_doc(Svc3, "no_such_method") is None

    def test_returns_original_after_impl_override(self):
        """@impl 覆盖后，仍能取回原始声明的 docstring"""
        class Svc4(mutobj.Declaration):
            def greet(self) -> str:
                """Original greeting doc."""
                ...

        def greet_override(self) -> str:
            """Overridden doc."""
            return "hello"
        greet_override.__module__ = "test_doc_override"
        mutobj.impl(Svc4.greet)(greet_override)

        # @impl 覆盖了类方法的 __doc__
        assert Svc4.greet.__doc__ == "Overridden doc."
        # get_declaration_doc 取回的是原始声明的 docstring
        assert get_declaration_doc(Svc4, "greet") == "Original greeting doc."

    def test_returns_none_for_non_declaration_class(self):
        """对非 Declaration 类查询，返回 None"""
        class Plain:
            def run(self): ...

        assert get_declaration_doc(Plain, "run") is None


class TestGetDeclarationFunc:
    """get_declaration_func 基本功能测试"""

    def test_returns_declaration_function(self):
        """声明方法能正确取回原始函数"""
        class Svc(mutobj.Declaration):
            def run(self) -> str:
                """Run the service."""
                ...

        func = get_declaration_func(Svc, "run")
        assert func is not None
        assert func.__name__ == "run"
        assert func.__doc__ == "Run the service."

    def test_returns_function_for_no_docstring(self):
        """声明方法没有 docstring 时，仍能取回函数"""
        class Svc(mutobj.Declaration):
            def run(self) -> str: ...

        func = get_declaration_func(Svc, "run")
        assert func is not None
        assert func.__name__ == "run"
        assert func.__doc__ is None

    def test_returns_none_for_nonexistent_method(self):
        """查询不存在的方法时，返回 None"""
        class Svc(mutobj.Declaration):
            def run(self) -> str:
                """Run."""
                ...

        assert get_declaration_func(Svc, "no_such_method") is None

    def test_returns_original_after_impl_override(self):
        """@impl 覆盖后，仍能取回原始声明函数"""
        class Svc(mutobj.Declaration):
            def greet(self) -> str:
                """Original greeting doc."""
                ...

        def greet_override(self) -> str:
            """Overridden doc."""
            return "hello"
        greet_override.__module__ = "test_func_override"
        mutobj.impl(Svc.greet)(greet_override)

        func = get_declaration_func(Svc, "greet")
        assert func is not None
        assert func.__doc__ == "Original greeting doc."
        # 不是 @impl 替换后的版本
        assert func.__doc__ != "Overridden doc."

    def test_consistency_with_declaration_doc(self):
        """get_declaration_doc 与 get_declaration_func 一致性"""
        class Svc(mutobj.Declaration):
            def process(self, item: str) -> str:
                """Process an item."""
                ...

        func = get_declaration_func(Svc, "process")
        doc = get_declaration_doc(Svc, "process")
        assert func is not None
        assert doc == func.__doc__

    def test_returns_none_for_non_declaration_class(self):
        """对非 Declaration 类查询，返回 None"""
        class Plain:
            def run(self): ...

        assert get_declaration_func(Plain, "run") is None
