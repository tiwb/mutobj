"""Tests for resolve_class."""

import sys
import tempfile
import types
from pathlib import Path

import pytest
import mutobj


# 模块级 Declaration 子类，用于全路径测试
class _TestAlreadyReg(mutobj.Declaration):
    def run(self) -> str: ...


class _TestProvBase(mutobj.Declaration):
    def run(self) -> str: ...


class _TestProvSub(_TestProvBase):
    pass


class _TestUnrelatedX(mutobj.Declaration):
    def run(self) -> str: ...


class _TestUnrelatedY(mutobj.Declaration):
    def run(self) -> str: ...


class TestResolveClassShortName:
    """短名解析：在已注册类中按 qualname 或 __name__ 搜索"""

    def test_resolve_by_short_name(self):
        """已注册的 Declaration 子类可通过短名解析"""
        class MyProvider(mutobj.Declaration):
            def run(self) -> str: ...

        result = mutobj.resolve_class("MyProvider", mutobj.Declaration)
        assert result is MyProvider

    def test_resolve_short_name_with_base_cls(self):
        """base_cls 匹配时正常返回"""
        class Base(mutobj.Declaration):
            def run(self) -> str: ...

        class Sub(Base):
            pass

        result = mutobj.resolve_class("Sub", base_cls=Base)
        assert result is Sub

    def test_resolve_short_name_base_cls_mismatch(self):
        """base_cls 不匹配时抛出 ValueError"""
        class MismatchA(mutobj.Declaration):
            def run(self) -> str: ...

        class MismatchB(mutobj.Declaration):
            def run(self) -> str: ...

        with pytest.raises(ValueError, match="not a subclass"):
            mutobj.resolve_class("MismatchB", base_cls=MismatchA)

    def test_resolve_nonexistent_short_name(self):
        """不存在的短名抛出 ValueError"""
        with pytest.raises(ValueError, match="Cannot resolve class"):
            mutobj.resolve_class("NoSuchClassXYZ12345", mutobj.Declaration)


class TestResolveClassFullPath:
    """全路径解析：先搜索已注册，未找到则自动 import"""

    def test_resolve_already_registered_by_full_path(self):
        """已注册的模块级类可通过全路径解析"""
        mod = _TestAlreadyReg.__module__
        full_path = f"{mod}._TestAlreadyReg"
        result = mutobj.resolve_class(full_path, mutobj.Declaration)
        assert result is _TestAlreadyReg

    def test_resolve_auto_import(self):
        """全路径指向未加载模块时，自动 import 并解析"""
        mod_name = "_test_resolve_auto_import_mod"
        mod = types.ModuleType(mod_name)
        mod.__file__ = "<test>"

        code = """
import mutobj

class AutoImported(mutobj.Declaration):
    def run(self) -> str: ...
"""
        exec(compile(code, "<test>", "exec"), mod.__dict__)
        sys.modules[mod_name] = mod

        try:
            result = mutobj.resolve_class(f"{mod_name}.AutoImported", mutobj.Declaration)
            assert result is mod.__dict__["AutoImported"]
        finally:
            sys.modules.pop(mod_name, None)

    def test_resolve_full_path_import_error(self):
        """import 失败时抛出 ValueError"""
        with pytest.raises(ValueError, match="Cannot import module"):
            mutobj.resolve_class("no.such.module.FakeClass", mutobj.Declaration)

    def test_resolve_full_path_class_not_in_module(self):
        """模块存在但类不在其中时抛出 ValueError"""
        with pytest.raises(ValueError, match="Cannot resolve class"):
            mutobj.resolve_class("os.path.NoSuchDeclaration", mutobj.Declaration)

    def test_resolve_auto_import_via_file(self):
        """全路径指向磁盘文件时，自动 import 并解析（行 52, 57 覆盖）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mod_name = "_test_auto_import_file_mod"
            code = (
                "import mutobj\n"
                "class AutoImportedFile(mutobj.Declaration):\n"
                "    def run(self) -> str: ...\n"
            )
            Path(tmpdir, f"{mod_name}.py").write_text(code)
            sys.path.insert(0, tmpdir)
            try:
                result = mutobj.resolve_class(
                    f"{mod_name}.AutoImportedFile", mutobj.Declaration
                )
                assert result.__name__ == "AutoImportedFile"
            finally:
                sys.path.remove(tmpdir)
                sys.modules.pop(mod_name, None)

    def test_resolve_auto_import_base_cls_mismatch(self):
        """auto import 成功后 base_cls 不匹配时抛出 ValueError（行 53-56 覆盖）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mod_name = "_test_auto_import_mismatch_mod"
            code = (
                "import mutobj\n"
                "class AutoMismatch(mutobj.Declaration):\n"
                "    def run(self) -> str: ...\n"
            )
            Path(tmpdir, f"{mod_name}.py").write_text(code)
            sys.path.insert(0, tmpdir)
            try:
                class UnrelatedBase(mutobj.Declaration):
                    def run(self) -> str: ...
                with pytest.raises(ValueError, match="not a subclass"):
                    mutobj.resolve_class(
                        f"{mod_name}.AutoMismatch", base_cls=UnrelatedBase
                    )
            finally:
                sys.path.remove(tmpdir)
                sys.modules.pop(mod_name, None)

    def test_resolve_full_path_with_base_cls(self):
        """全路径 + base_cls 校验"""
        mod = _TestProvSub.__module__
        result = mutobj.resolve_class(f"{mod}._TestProvSub", base_cls=_TestProvBase)
        assert result is _TestProvSub

    def test_resolve_full_path_base_cls_mismatch(self):
        """全路径 + base_cls 不匹配时抛出 ValueError"""
        mod = _TestUnrelatedY.__module__
        with pytest.raises(ValueError, match="not a subclass"):
            mutobj.resolve_class(f"{mod}._TestUnrelatedY", base_cls=_TestUnrelatedX)
