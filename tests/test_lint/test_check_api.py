from __future__ import annotations

from pathlib import Path

from mutobj.lint import check

from ._helpers import import_temp_pkg, make_pkg, write


class TestCheckApi:
    def test_empty_patterns_return_empty(self) -> None:
        assert check([]).messages == []

    def test_wildcard_and_exclude(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "alpha.py", """
            from mutobj import Declaration

            class Alpha(Declaration):
                def run(self) -> int: ...
        """)
        write(pkg, "beta.py", """
            from mutobj import Declaration

            class Beta(Declaration):
                def run(self) -> int: ...
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"], exclude=["pkg.beta"]).messages
        assert len(messages) == 1
        assert messages[0].symbol == "Declaration:Alpha.run"

    def test_exact_module_loads_runtime_checks(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "view.py", """
            from mutobj import Declaration

            class View(Declaration):
                def render(self, value: int) -> str: ...


            from . import _view_impl as _view_impl  # noqa: F401, E402
        """)
        write(pkg, "_view_impl.py", """
            from mutobj import impl

            from .view import View


            @impl(View.render)
            def view_render(self, value: str) -> str:
                return value
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.view"]).messages
        assert any(message.rule_id == "R004" for message in messages)

    def test_duplicate_pattern_dedup(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "alpha.py", """
            from mutobj import Declaration

            class Alpha(Declaration):
                def run(self) -> int: ...
        """)
        with import_temp_pkg(tmp_path):
            messages1 = check(["pkg.*"]).messages
            messages2 = check(["pkg.*", "pkg.alpha"]).messages
        assert len(messages1) == len(messages2)

    def test_wildcard_on_non_package(self, tmp_path: Path) -> None:
        write(tmp_path, "single.py", """
            from mutobj import Declaration

            class Single(Declaration):
                def run(self) -> int: ...
        """)
        with import_temp_pkg(tmp_path, "single"):
            messages = check(["single.*"]).messages
        assert len(messages) == 1

