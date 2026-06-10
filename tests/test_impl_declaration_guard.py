"""测试 @impl 及相关 API 对非 Declaration 类的守卫

参见 docs/specifications/refactor-impl-non-declaration-guard.md
"""

import pytest
import mutobj


class TestImplDeclarationGuard:
    """@impl 应拒绝作用于非 Declaration 子类"""

    def test_impl_rejects_non_declaration_class(self):
        """@impl 对非 Declaration 类抛 TypeError"""
        class PlainClass:
            def foo(self) -> str:
                return "stub"

        with pytest.raises(TypeError, match="not a mutobj.Declaration subclass"):
            @mutobj.impl(PlainClass.foo)
            def _foo_impl(self) -> str:
                return "nope"

    def test_impl_error_message_includes_class_and_method(self):
        """错误信息应包含目标类名和方法名"""
        class MenuTrigger:
            def handle(self) -> None: ...

        with pytest.raises(TypeError) as exc_info:
            @mutobj.impl(MenuTrigger.handle)
            def _handle_impl(self) -> None:
                pass

        msg = str(exc_info.value)
        assert "MenuTrigger" in msg
        assert "handle" in msg
        assert "Declaration" in msg
        # 给出修复指引
        assert "inherit from mutobj.Declaration" in msg or "class body" in msg


class TestImplChainAPIsRejectNonDeclaration:
    """查询类 API 同样应拒绝非 Declaration 类"""

    def test_impl_has_override_rejects_non_declaration(self):
        class PlainCls:
            def bar(self) -> None: ...

        with pytest.raises(TypeError, match="not a mutobj.Declaration subclass"):
            mutobj.impl_has_override(PlainCls.bar)

    def testimpl_chain_rejects_non_declaration(self):
        class PlainCls:
            def bar(self) -> None: ...

        with pytest.raises(TypeError, match="not a mutobj.Declaration subclass"):
            mutobj.impl_chain(PlainCls.bar)


class TestResolveImplKeyNoGlobalsFallback:
    """删除 __globals__ fallback 后, 非 Declaration 类直接走诊断路径

    这是回归锁：防止未来有人把诊断分支退化为 ValueError 或重新引入 fallback。
    """

    def test_query_api_raises_type_error_not_value_error(self):
        """非 Declaration 类应走诊断分支抛 TypeError, 而不是 ValueError"""
        class PlainCls:
            def bar(self) -> None: ...

        # 关键断言: TypeError 而非 ValueError —— ValueError 是"找不到类"的兜底路径,
        # 走到那里说明诊断分支已被去掉, 错误信息会退化
        with pytest.raises(TypeError):
            mutobj.impl_chain(PlainCls.bar)

    def test_truly_unresolvable_method_still_raises_value_error(self):
        """qualname 不含类名前缀的 callable (顶级函数) 仍抛 ValueError"""
        # 构造一个 __qualname__ 不含 "." 的 callable
        # 模拟从顶级作用域拿出的裸函数 (未绑定到任何类)
        def f(self) -> None: ...
        f.__qualname__ = "f"

        with pytest.raises(ValueError, match="Cannot determine class"):
            mutobj.impl_chain(f)

    def test_subclass_init_chain_is_resolved_without_falling_back_to_declaration(self):
        """未手写 __init__ 的子类现在也有独立链入口。"""
        class Box(mutobj.Declaration):
            width: float = 0.0

        @mutobj.impl(Box.__init__)
        def _box_init(self: Box, w: float) -> None:
            mutobj.impl_call_super(Box.__init__, self, w)

        assert Box(2.5).width == 2.5
