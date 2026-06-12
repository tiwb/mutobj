"""mutobj.lint 测试 — CLI: 文本/JSON/退出码/--exclude/默认路径"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from ._helpers import make_pkg, write
from mutobj.lint.__main__ import (
    main as cli_main,
    _find_pyproject,
    _load_mutobj_lint_config,
)


class TestCLI:
    def test_text_output_clean(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "ok.py", """
            from mutobj import Declaration
            class A(Declaration):
                def m(self): ...
        """)
        rc = cli_main([str(f)])
        captured = capsys.readouterr()
        assert rc == 0
        assert "0 error" in captured.out

    def test_text_output_violations(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "bad.py", """
            from mutobj import Declaration
            class B(Declaration):
                def stub(self): ...
                def impl(self):
                    return 1
        """)
        rc = cli_main([str(f)])
        captured = capsys.readouterr()
        assert rc == 1
        assert "R001" in captured.out
        assert "bad.py" in captured.out
        # 形如 path:line:col: R001 ...
        assert ":" in captured.out

    def test_json_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        pkg = make_pkg(tmp_path)
        f = write(pkg, "bad.py", """
            from mutobj import Declaration
            class B(Declaration):
                def stub(self): ...
                def impl(self):
                    return 1
        """)
        rc = cli_main([str(f), "--json"])
        captured = capsys.readouterr()
        assert rc == 1
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert data
        item = data[0]
        assert item["type"] == "issue"
        assert item["check_name"] == "R001"
        assert item["location"]["path"]
        assert "begin" in item["location"]["positions"]

    def test_exclude_option(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        pkg = make_pkg(tmp_path)
        write(pkg, "vendor/bad.py", """
            from mutobj import Declaration
            class B(Declaration):
                def stub(self): ...
                def impl(self):
                    return 1
        """)
        rc = cli_main([str(pkg), "--exclude", "vendor"])
        captured = capsys.readouterr()
        assert rc == 0
        assert "bad.py" not in captured.out

    def test_module_invocation(self, tmp_path: Path) -> None:
        """python -m mutobj.lint <path> 应可调用"""
        pkg = make_pkg(tmp_path)
        f = write(pkg, "ok.py", """
            from mutobj import Declaration
            class A(Declaration):
                def m(self): ...
        """)
        result = subprocess.run(
            [sys.executable, "-m", "mutobj.lint", str(f)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0


class TestDefaultPath:
    """测试无参数默认行为"""

    def test_no_args_defaults_to_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """无参数时默认扫描当前目录"""
        pkg = make_pkg(tmp_path)
        write(pkg, "ok.py", """
            from mutobj import Declaration
            class A(Declaration):
                def m(self): ...
        """)
        monkeypatch.setattr(Path, "cwd", staticmethod(lambda: pkg))
        # _find_pyproject 向上查找不应命中（没有 pyproject.toml），fallback 到 cwd
        with patch.object(Path, "cwd", return_value=pkg):
            rc = cli_main([])
        captured = capsys.readouterr()
        assert rc == 0
        assert "0 error" in captured.out

    def test_no_args_with_violations(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """无参数扫描当前目录时能检测违规"""
        pkg = make_pkg(tmp_path)
        write(pkg, "bad.py", """
            from mutobj import Declaration
            class B(Declaration):
                def stub(self): ...
                def impl(self):
                    return 1
        """)
        with patch.object(Path, "cwd", return_value=pkg):
            rc = cli_main([])
        captured = capsys.readouterr()
        assert rc == 1
        assert "R001" in captured.out


class TestPyprojectConfig:
    """测试 pyproject.toml [tool.mutobj-lint] 配置读取"""

    def test_config_include(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """读取 pyproject.toml 的 include 路径作为默认扫描路径"""
        # 创建子目录放置源码
        src_dir = tmp_path / "src"
        pkg = make_pkg(src_dir)
        write(pkg, "ok.py", """
            from mutobj import Declaration
            class A(Declaration):
                def m(self): ...
        """)
        # 在 tmp_path 根创建 pyproject.toml
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.mutobj-lint]
include = ["src"]
""", encoding="utf-8")
        with patch.object(Path, "cwd", return_value=tmp_path):
            rc = cli_main([])
        captured = capsys.readouterr()
        assert rc == 0
        assert "0 error" in captured.out

    def test_config_include_with_violations(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """config include 路径中的违规被检测到"""
        src_dir = tmp_path / "src"
        pkg = make_pkg(src_dir)
        write(pkg, "bad.py", """
            from mutobj import Declaration
            class B(Declaration):
                def stub(self): ...
                def impl(self):
                    return 1
        """)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.mutobj-lint]
include = ["src"]
""", encoding="utf-8")
        with patch.object(Path, "cwd", return_value=tmp_path):
            rc = cli_main([])
        captured = capsys.readouterr()
        assert rc == 1
        assert "R001" in captured.out

    def test_config_exclude(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """config exclude 目录被排除"""
        src_dir = tmp_path / "src"
        pkg = make_pkg(src_dir)
        write(pkg, "vendor/bad.py", """
            from mutobj import Declaration
            class B(Declaration):
                def stub(self): ...
                def impl(self):
                    return 1
        """)
        write(pkg, "ok.py", """
            from mutobj import Declaration
            class A(Declaration):
                def m(self): ...
        """)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.mutobj-lint]
include = ["src"]
exclude = ["vendor"]
""", encoding="utf-8")
        with patch.object(Path, "cwd", return_value=tmp_path):
            rc = cli_main([])
        captured = capsys.readouterr()
        assert rc == 0
        assert "bad.py" not in captured.out

    def test_config_exclude_merged_with_cli(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """config exclude 与 CLI --exclude 合并"""
        pkg = make_pkg(tmp_path)
        write(pkg, "vendor/bad.py", """
            from mutobj import Declaration
            class B(Declaration):
                def stub(self): ...
                def impl(self):
                    return 1
        """)
        write(pkg, "tests/bad2.py", """
            from mutobj import Declaration
            class C(Declaration):
                def stub(self): ...
                def impl(self):
                    return 1
        """)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.mutobj-lint]
exclude = ["vendor"]
""", encoding="utf-8")
        with patch.object(Path, "cwd", return_value=tmp_path):
            rc = cli_main([str(pkg), "--exclude", "tests"])
        captured = capsys.readouterr()
        # vendor 由 config 排除，tests 由 CLI 排除，两者都被排除 → 干净
        assert rc == 0
        assert "bad.py" not in captured.out
        assert "bad2.py" not in captured.out

    def test_no_config_falls_back_to_cwd(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """无 pyproject.toml 或未配置时 fallback 到 cwd"""
        pkg = make_pkg(tmp_path)
        write(pkg, "ok.py", """
            from mutobj import Declaration
            class A(Declaration):
                def m(self): ...
        """)
        with patch.object(Path, "cwd", return_value=tmp_path):
            rc = cli_main([])
        _ = capsys.readouterr()
        assert rc == 0

    def test_cli_paths_overrides_config(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """CLI 传了路径时不读 config"""
        src_dir = tmp_path / "src"
        pkg_src = make_pkg(src_dir)
        f = write(pkg_src, "ok.py", """
            from mutobj import Declaration
            class A(Declaration):
                def m(self): ...
        """)
        # 配置指向另一个不存在的目录，确认 CLI 路径优先
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.mutobj-lint]
include = ["other"]
""", encoding="utf-8")
        with patch.object(Path, "cwd", return_value=tmp_path):
            rc = cli_main([str(f)])
        _ = capsys.readouterr()
        assert rc == 0

    def test_find_pyproject_finds_config(
        self, tmp_path: Path,
    ) -> None:
        """_find_pyproject 从 cwd 向上搜索 pyproject.toml"""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("", encoding="utf-8")
        subdir = tmp_path / "a" / "b" / "c"
        subdir.mkdir(parents=True)
        with patch.object(Path, "cwd", return_value=subdir):
            found = _find_pyproject()
        assert found is not None
        assert found.resolve() == pyproject.resolve()

    def test_load_config_empty_when_no_file(
        self, tmp_path: Path,
    ) -> None:
        """无 pyproject.toml 时返回空"""
        with patch.object(Path, "cwd", return_value=tmp_path):
            include, exclude = _load_mutobj_lint_config()
        assert include == []
        assert exclude == []

    def test_load_config_reads_params(
        self, tmp_path: Path,
    ) -> None:
        """正常读取 include 和 exclude"""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.mutobj-lint]
include = ["src", "lib"]
exclude = ["tests"]
""", encoding="utf-8")
        with patch.object(Path, "cwd", return_value=tmp_path):
            include, exclude = _load_mutobj_lint_config()
        assert include == ["src", "lib"]
        assert exclude == ["tests"]

    def test_load_config_broken_toml(
        self, tmp_path: Path,
    ) -> None:
        """损坏的 TOML → 返回空配置，不崩溃"""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("this is not valid toml [[[\n", encoding="utf-8")
        with patch.object(Path, "cwd", return_value=tmp_path):
            include, exclude = _load_mutobj_lint_config()
        assert include == []
        assert exclude == []

    def test_load_config_broken_toml_cli_fallback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """损坏的 TOML + CLI 无参数 → fallback 到 cwd"""
        pkg = make_pkg(tmp_path)
        write(pkg, "ok.py", """
            from mutobj import Declaration
            class A(Declaration):
                def m(self): ...
        """)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("invalid[[[\n", encoding="utf-8")
        with patch.object(Path, "cwd", return_value=tmp_path):
            rc = cli_main([])
            _ = capsys.readouterr()
        assert rc == 0

    def test_load_config_partial(
        self, tmp_path: Path,
    ) -> None:
        """只配置了部分字段"""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.mutobj-lint]
exclude = ["generated"]
""", encoding="utf-8")
        with patch.object(Path, "cwd", return_value=tmp_path):
            include, exclude = _load_mutobj_lint_config()
        assert include == []
        assert exclude == ["generated"]
