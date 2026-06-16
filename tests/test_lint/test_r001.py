from __future__ import annotations

from pathlib import Path

from mutobj.lint import check

from ._helpers import import_temp_pkg, make_pkg, write


class TestR001Runtime:
    def test_class_level_mix_reports(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "panel.py", """
            from mutobj import Declaration

            class Panel(Declaration):
                def title(self) -> str: ...

                def render(self) -> str:
                    return "ok"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        r001 = [message for message in messages if message.rule_id == "R001"]
        assert len(r001) == 1
        assert "Panel.render" in r001[0].message

    def test_cross_package_base_still_checked(self, tmp_path: Path) -> None:
        base_pkg = make_pkg(tmp_path, "basepkg")
        write(base_pkg, "view.py", """
            from mutobj import Declaration

            class View(Declaration):
                def render(self) -> str: ...
        """)

        app_pkg = make_pkg(tmp_path, "apppkg")
        write(app_pkg, "settings.py", """
            from basepkg.view import View

            class SettingsPanel(View):
                def header(self) -> str: ...

                def render(self) -> str:
                    return "bad"
        """)
        with import_temp_pkg(tmp_path, "basepkg"):
            with import_temp_pkg(tmp_path, "apppkg"):
                messages = check(["basepkg.*", "apppkg.*"]).messages
        assert any(message.rule_id == "R001" and "SettingsPanel.render" in message.message for message in messages)

    def test_file_level_mix_reports_both_classes(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "mixed.py", """
            from mutobj import Declaration

            class Decl(Declaration):
                def render(self) -> str: ...

            class Impl(Declaration):
                def render(self) -> str:
                    return "ok"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        file_level = [message for message in messages if message.rule_id == "R001" and "文件级" in message.message]
        assert len(file_level) == 2

    def test_behaviorless_class_not_mixed(self, tmp_path: Path) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "mixed.py", """
            from mutobj import Declaration

            class Empty(Declaration):
                pass

            class Decl(Declaration):
                def run(self) -> str: ...

            class Impl(Declaration):
                def run(self) -> str:
                    return "ok"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        file_level = [m for m in messages if m.rule_id == "R001" and "文件级" in m.message]
        assert len(file_level) == 2
        assert all("Empty" not in m.message for m in file_level)

    def test_underscore_prefixed_file_skipped(self, tmp_path: Path) -> None:
        """_ 开头的 impl 文件跳过 R001 文件级检查，允许混合声明类与实现类。"""
        pkg = make_pkg(tmp_path)
        write(pkg, "_panel.py", """
            from mutobj import Declaration

            class Decl(Declaration):
                def render(self) -> str: ...

            class Impl(Declaration):
                def render(self) -> str:
                    return "ok"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        file_level = [m for m in messages if m.rule_id == "R001" and "文件级" in m.message]
        assert not file_level, f"_ prefixed file should skip file-level R001, got: {[m.message for m in file_level]}"

    def test_non_underscore_file_still_checked(self, tmp_path: Path) -> None:
        """非 _ 开头的文件依然执行 R001 文件级检查。"""
        pkg = make_pkg(tmp_path)
        write(pkg, "panel.py", """
            from mutobj import Declaration

            class Decl(Declaration):
                def render(self) -> str: ...

            class Impl(Declaration):
                def render(self) -> str:
                    return "ok"
        """)
        with import_temp_pkg(tmp_path):
            messages = check(["pkg.*"]).messages
        file_level = [m for m in messages if m.rule_id == "R001" and "文件级" in m.message]
        assert len(file_level) == 2
        assert any("Decl" in m.message for m in file_level)
        assert any("Impl" in m.message for m in file_level)
