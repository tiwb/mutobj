"""mutobj.lint 测试 — R003: @impl 函数 _ 前缀检测"""

from __future__ import annotations

from pathlib import Path

import pytest

from ._helpers import make_pkg, write
from mutobj.lint import lint_directory, lint_file


# ============================================================ R003: @impl 函数 _ 前缀检测


class TestR003UnderscorePrefix:
    """@impl 函数以 _ 开头的检测"""

    def test_no_underscore_no_report(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                def render(self) -> str: ...
        """)
        write(pkg, "_view_impl.py", """
            from mutobj import impl

            @impl(MyView.render)
            def my_view_render(self) -> str:
                return "ok"
        """)
        msgs = lint_file(pkg / "_view_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        assert r003 == []

    def test_underscore_prefix_reports(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py",  """
            from mutobj import Declaration

            class MyView(Declaration):
                def render(self) -> str: ...
        """)
        write(pkg, "_view_impl.py", """
            from mutobj import impl

            @impl(MyView.render)
            def _my_view_render(self) -> str:
                return "ok"
        """)
        msgs = lint_file(pkg / "_view_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        # R003a: _ 前缀 → 1 条；函数名 my_view_render 满足 R003b 前缀
        assert len(r003) == 1
        assert r003[0].severity == "warning"
        assert "_my_view_render" in r003[0].message

    def test_mixed_functions(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                def render(self) -> str: ...
                def on_event(self) -> None: ...
                def on_close(self) -> None: ...
        """)
        write(pkg, "_view_impl.py", """
            from mutobj import impl

            @impl(MyView.render)
            def my_view_render(self) -> str:
                return "ok"

            @impl(MyView.on_event)
            def _my_view_on_event(self) -> None:
                pass

            @impl(MyView.on_close)
            def _my_view_on_close(self) -> None:
                pass
        """)
        msgs = lint_file(pkg / "_view_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        # 仅 R003a × 2（_ 前缀），my_view_render 满足 R003b
        assert len(r003) == 2
        assert r003[0].severity == "warning"
        assert r003[1].severity == "warning"

    def test_non_impl_underscore_no_report(self, tmp_path: Path) -> None:
        """没有 @impl 装饰的 _ 前缀函数不报 R003"""
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                def render(self) -> str: ...
        """)
        write(pkg, "_view_impl.py", """
            from mutobj import impl

            def _internal_helper() -> int:
                return 42

            @impl(MyView.render)
            def my_view_render(self) -> str:
                return str(_internal_helper())
        """)
        msgs = lint_file(pkg / "_view_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        assert r003 == []


class TestR003ImportMutobj:
    """import mutobj 形式 @mutobj.impl(...) 的检测"""

    def test_import_mutobj_underscore_reports(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                def render(self) -> str: ...
        """)
        write(pkg, "_view_impl.py", """
            import mutobj

            @mutobj.impl(MyView.render)
            def _my_view_render(self) -> str:
                return "ok"
        """)
        msgs = lint_file(pkg / "_view_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        # R003a: _ 前缀
        assert len(r003) == 1
        assert "_my_view_render" in r003[0].message

    def test_import_mutobj_as_underscore_reports(self, tmp_path: Path) -> None:
        """import mutobj as m → @m.impl(...)"""
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                def render(self) -> str: ...
        """)
        write(pkg, "_view_impl.py", """
            import mutobj as mo

            @mo.impl(MyView.render)
            def _my_view_render(self) -> str:
                return "ok"
        """)
        msgs = lint_file(pkg / "_view_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        assert len(r003) == 1


class TestR003ImportAsAlias:
    """from mutobj import impl as 别名 的检测"""

    def test_import_as_reports(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                def render(self) -> str: ...
        """)
        write(pkg, "_view_impl.py", """
            from mutobj import impl as reg

            @reg(MyView.render)
            def _my_view_render(self) -> str:
                return "ok"
        """)
        msgs = lint_file(pkg / "_view_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        assert len(r003) == 1
        assert "_my_view_render" in r003[0].message


class TestR003PyrightIgnore:
    """pyright: ignore[reportUnusedFunction] 注释豁免"""

    def test_pyright_ignore_suppresses(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                def render(self) -> str: ...
        """)
        write(pkg, "_view_impl.py", """
            from mutobj import impl

            @impl(MyView.render)
            def _my_view_render(self) -> str:  # pyright: ignore[reportUnusedFunction]
                return "ok"
        """)
        msgs = lint_file(pkg / "_view_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        # pyright: ignore 同时豁免 R003a 和 R003b
        assert r003 == []


class TestR003NonImplFile:
    """非 _*_impl.py 文件不检测"""

    def test_non_impl_file_no_report(self, tmp_path: Path) -> None:
        """普通 .py 文件中的 @impl + _ 前缀不应被检测"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "demo.py", """
            from mutobj import Declaration, impl

            class App(Declaration):
                title: str = "demo"

            @impl(App.title)
            def _app_title(self) -> str:  # noqa: F811
                return self.title.upper()
        """)
        msgs = lint_file(f)
        r003 = [m for m in msgs if m.rule_id == "R003"]
        assert r003 == []


class TestR003LintDirectory:
    """lint_directory 批量扫描"""

    def test_directory_scans_only_impl_files(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        # 合规 impl
        write(pkg, "view.py", """
            from mutobj import Declaration

            class MyView(Declaration):
                def render(self) -> str: ...
        """)
        write(pkg, "_view_impl.py", """
            from mutobj import impl

            @impl(MyView.render)
            def my_view_render(self) -> str:
                return "ok"
        """)
        # 违规 impl — 含 _ 前缀 + 缺少类型前缀
        write(pkg, "model.py", """
            from mutobj import Declaration

            class MyModel(Declaration):
                def save(self) -> None: ...
        """)
        write(pkg, "_model_impl.py", """
            from mutobj import impl

            @impl(MyModel.save)
            def _save(self) -> None:
                pass
        """)
        # 普通文件的 @impl + _ 前缀（不应被检测）
        write(pkg, "demo.py", """
            from mutobj import Declaration, impl

            class App(Declaration):
                name: str = "demo"

            @impl(App.name)
            def _app_name(self) -> str:
                return self.name.upper()
        """)

        msgs = lint_directory(pkg)
        r003 = [m for m in msgs if m.rule_id == "R003"]
        # _save: R003a（_ 前缀）触发，R003b 跳过（冗余）；my_view_render 合规无 R003
        assert len(r003) == 1
        assert "_save" in r003[0].message
        assert "_model_impl.py" in r003[0].path


# ============================================================ R003b: 类型名前缀检测


class TestR003TypePrefix:
    """@impl 函数名以 snake_case(类型名) 开头的检测"""

    def test_correct_prefix_with_suffix(self, tmp_path: Path) -> None:
        """函数名以类型前缀 + _ + 后缀开头 → 无 R003b"""
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class View(Declaration):
                def get(self) -> str: ...
        """)
        write(pkg, "_view_impl.py", """
            from mutobj import impl

            @impl(View.get)
            def view_get(self) -> str:
                return "ok"
        """)
        msgs = lint_file(pkg / "_view_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        assert r003 == []

    def test_correct_prefix_no_suffix(self, tmp_path: Path) -> None:
        """函数名等于 snake_type（无后缀）→ 无 R003b（如 __init__）"""
        pkg = make_pkg(tmp_path)
        write(pkg, "response.py", """
            from mutobj import Declaration

            class JSONResponse(Declaration):
                def __init__(self, content: str, status: int = 200) -> None: ...
        """)
        write(pkg, "_response_impl.py", """
            from mutobj import impl

            @impl(JSONResponse.__init__)
            def json_response(self, content: str, status: int = 200) -> None:
                self.content = content
        """)
        msgs = lint_file(pkg / "_response_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        assert r003 == []

    def test_missing_prefix(self, tmp_path: Path) -> None:
        """函数名缺少类型前缀 → R003b"""
        pkg = make_pkg(tmp_path)
        write(pkg, "client.py", """
            from mutobj import Declaration

            class MCPClient(Declaration):
                def connect(self) -> None: ...
        """)
        write(pkg, "_client_impl.py", """
            from mutobj import impl

            @impl(MCPClient.connect)
            def connect(self) -> None:
                pass
        """)
        msgs = lint_file(pkg / "_client_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        assert len(r003) == 1
        assert "connect" in r003[0].message
        assert "mcp_client" in r003[0].message

    def test_multi_word_type_correct(self, tmp_path: Path) -> None:
        """多词类型名 + 正确全称前缀 → 无 R003b"""
        pkg = make_pkg(tmp_path)
        write(pkg, "ws.py", """
            from mutobj import Declaration

            class WebSocketConnection(Declaration):
                def accept(self) -> None: ...
        """)
        write(pkg, "_ws_impl.py", """
            from mutobj import impl

            @impl(WebSocketConnection.accept)
            def web_socket_connection_accept(self) -> None:
                pass
        """)
        msgs = lint_file(pkg / "_ws_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        assert r003 == []

    def test_multi_word_type_abbreviated_prefix(self, tmp_path: Path) -> None:
        """多词类型名用缩写前缀 → R003b"""
        pkg = make_pkg(tmp_path)
        write(pkg, "ws.py", """
            from mutobj import Declaration

            class WebSocketConnection(Declaration):
                def accept(self) -> None: ...
        """)
        write(pkg, "_ws_impl.py", """
            from mutobj import impl

            @impl(WebSocketConnection.accept)
            def ws_accept(self) -> None:
                pass
        """)
        msgs = lint_file(pkg / "_ws_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        assert len(r003) == 1
        assert "ws_accept" in r003[0].message

    def test_mutobj_dot_impl_form(self, tmp_path: Path) -> None:
        """@mutobj.impl(...) 形式应正确识别"""
        pkg = make_pkg(tmp_path)
        write(pkg, "server.py", """
            from mutobj import Declaration

            class Server(Declaration):
                def run(self) -> None: ...
        """)
        write(pkg, "_server_impl.py", """
            import mutobj

            @mutobj.impl(Server.run)
            def server_run(self) -> None:
                pass
        """)
        msgs = lint_file(pkg / "_server_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        assert r003 == []

    def test_init_with_init_suffix(self, tmp_path: Path) -> None:
        """__init__ + 类型前缀 + _init 后缀 → 无 R003b"""
        pkg = make_pkg(tmp_path)
        write(pkg, "response.py", """
            from mutobj import Declaration

            class JSONResponse(Declaration):
                def __init__(self, content: str, status: int = 200) -> None: ...
        """)
        write(pkg, "_response_impl.py", """
            from mutobj import impl

            @impl(JSONResponse.__init__)
            def json_response_init(self, content: str, status: int = 200) -> None:
                self.content = content
        """)
        msgs = lint_file(pkg / "_response_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        assert r003 == []

    def test_decorator_non_attr_skips(self, tmp_path: Path) -> None:
        """装饰器参数非简单 Attribute 链 → 跳过 R003b"""
        pkg = make_pkg(tmp_path)
        # 不需要真实的 Declaration；AST 解析阶段不 import
        write(pkg, "_test_impl.py", """
            from mutobj import impl

            @impl(get_target())
            def foo(self) -> None:
                pass
        """)
        msgs = lint_file(pkg / "_test_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        # 装饰器参数无法解析类型名 → 跳过 R003b；函数名不以 _ 开头 → 无 R003a
        assert r003 == []

    def test_mixed_types_in_file(self, tmp_path: Path) -> None:
        """同一文件多类型混合：合规 + 违规"""
        pkg = make_pkg(tmp_path)
        write(pkg, "decls.py", """
            from mutobj import Declaration

            class View(Declaration):
                def get(self) -> str: ...
            class MCPClient(Declaration):
                def connect(self) -> None: ...
        """)
        write(pkg, "_decls_impl.py", """
            from mutobj import impl

            @impl(View.get)
            def view_get(self) -> str:
                return "ok"

            @impl(MCPClient.connect)
            def connect(self) -> None:
                pass
        """)
        msgs = lint_file(pkg / "_decls_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        assert len(r003) == 1
        assert "connect" in r003[0].message
        assert "mcp_client" in r003[0].message

    def test_prefix_typo(self, tmp_path: Path) -> None:
        """函数名以类型前缀开头但拼错 → R003b"""
        pkg = make_pkg(tmp_path)
        write(pkg, "file.py", """
            from mutobj import Declaration

            class FileResponse(Declaration):
                def __init__(self, path: str) -> None: ...
        """)
        write(pkg, "_file_impl.py", """
            from mutobj import impl

            @impl(FileResponse.__init__)
            def file_resp(self, path: str) -> None:
                self.path = path
        """)
        msgs = lint_file(pkg / "_file_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        assert len(r003) == 1
        assert "file_resp" in r003[0].message

    def test_non_impl_file_skipped(self, tmp_path: Path) -> None:
        """非 _*_impl.py 文件中的 @impl 不检测 R003b"""
        pkg = make_pkg(tmp_path)
        write(pkg, "server.py", """
            from mutobj import Declaration, impl

            class View(Declaration):
                def get(self) -> str: ...

            @impl(View.get)
            def view_get(self) -> str:
                return "ok"
        """)
        msgs = lint_file(pkg / "server.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        assert r003 == []

    def test_init_no_suffix_with_nested_attr(self, tmp_path: Path) -> None:
        """链式引用如 pkg.Cls.__init__ → 取最后一节类型名"""
        pkg = make_pkg(tmp_path)
        # 声明侧用嵌套 module 模拟
        write(pkg, "nested_decl.py", """
            from mutobj import Declaration

            class Handler(Declaration):
                def handle(self) -> None: ...
        """)
        # impl 侧用 pkg.nested_decl.Handler.handle 链式引用
        write(pkg, "_nested_impl.py", """
            from mutobj import impl

            @impl(pkg.nested_decl.Handler.handle)
            def handler_handle(self) -> None:
                pass
        """)
        msgs = lint_file(pkg / "_nested_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        assert r003 == []

    def test_r003a_and_b_both_no_violation(self, tmp_path: Path) -> None:
        """合规函数零误报：无 _ 前缀 + 有类型名前缀"""
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class View(Declaration):
                def get(self) -> str: ...
                def post(self) -> str: ...
        """)
        write(pkg, "_view_impl.py", """
            from mutobj import impl

            @impl(View.get)
            def view_get(self) -> str:
                return "ok"

            @impl(View.post)
            def view_post(self) -> str:
                return "ok"
        """)
        msgs = lint_file(pkg / "_view_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        assert r003 == []

    def test_underscore_r003a_and_wrong_prefix_r003b(self, tmp_path: Path) -> None:
        """同时违反 R003a 和 R003b → 仅报 R003a（R003b 冗余跳过）"""
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class View(Declaration):
                def get(self) -> str: ...
        """)
        write(pkg, "_view_impl.py", """
            from mutobj import impl

            @impl(View.get)
            def _bad_view(self) -> str:
                return "ok"
        """)
        msgs = lint_file(pkg / "_view_impl.py")
        r003 = [m for m in msgs if m.rule_id == "R003"]
        # _bad_view: _ 前缀 → R003a；前缀检查跳过
        assert len(r003) == 1
        assert "_bad_view" in r003[0].message
