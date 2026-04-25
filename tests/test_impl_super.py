"""Tests for mutobj.call_super_impl — invoking the previous impl in the override chain."""

from __future__ import annotations

import asyncio
import pytest
import mutobj
from mutobj.core import _impl_chain, unregister_module_impls


def _make_module(module_name: str) -> dict:
    """构造一个伪模块的 globals 字典，使 exec 出来的函数 __module__ / __name__ 正确。"""
    return {
        "__name__": module_name,
        "__builtins__": __builtins__,
        "mutobj": mutobj,
    }


# ---------- 基础链式调用 ----------

class TestBasicChain:

    def test_two_level_super(self):
        class Svc(mutobj.Declaration):
            def run(self, x: int) -> int: ...

        mod_a = _make_module("super_two_mod_a")
        mod_a["Svc"] = Svc
        exec(
            "@mutobj.impl(Svc.run)\n"
            "def run(self, x):\n"
            "    return x + 1\n",
            mod_a,
        )

        mod_b = _make_module("super_two_mod_b")
        mod_b["Svc"] = Svc
        exec(
            "@mutobj.impl(Svc.run)\n"
            "def run(self, x):\n"
            "    return mutobj.call_super_impl(Svc.run, self, x) * 10\n",
            mod_b,
        )

        try:
            assert Svc().run(3) == 40  # (3+1)*10
        finally:
            unregister_module_impls("super_two_mod_a")
            unregister_module_impls("super_two_mod_b")

    def test_three_level_super(self):
        class Svc(mutobj.Declaration):
            def run(self, x: int) -> int: ...

        for name, body in [
            ("super_three_mod_a", "return x + 1"),
            ("super_three_mod_b", "return mutobj.call_super_impl(Svc.run, self, x) * 2"),
            ("super_three_mod_c", "return mutobj.call_super_impl(Svc.run, self, x) + 100"),
        ]:
            mod = _make_module(name)
            mod["Svc"] = Svc
            exec(
                f"@mutobj.impl(Svc.run)\n"
                f"def run(self, x):\n"
                f"    {body}\n",
                mod,
            )

        try:
            # C: super(B) + 100;  B: super(A) * 2;  A: x + 1
            # x=3 → A=4 → B=8 → C=108
            assert Svc().run(3) == 108
        finally:
            for name in (
                "super_three_mod_a",
                "super_three_mod_b",
                "super_three_mod_c",
            ):
                unregister_module_impls(name)


# ---------- 错误场景 ----------

class TestErrors:

    def test_super_at_chain_bottom_raises(self):
        class Svc(mutobj.Declaration):
            def run(self) -> str: ...

        mod = _make_module("super_bottom_mod")
        mod["Svc"] = Svc
        exec(
            "@mutobj.impl(Svc.run)\n"
            "def run(self):\n"
            "    return mutobj.call_super_impl(Svc.run, self)\n",
            mod,
        )

        try:
            with pytest.raises(NotImplementedError, match="No super implementation"):
                Svc().run()
        finally:
            unregister_module_impls("super_bottom_mod")

    def test_super_outside_impl_context_raises(self):
        class Svc(mutobj.Declaration):
            def run(self) -> str: ...

        # 只在别的模块里注册 impl，本测试模块不在链中
        mod = _make_module("super_outside_mod")
        mod["Svc"] = Svc
        exec(
            "@mutobj.impl(Svc.run)\n"
            "def run(self):\n"
            "    return 'ok'\n",
            mod,
        )

        try:
            with pytest.raises(RuntimeError, match="must be called from within"):
                mutobj.call_super_impl(Svc.run, Svc())
        finally:
            unregister_module_impls("super_outside_mod")

    def test_super_with_unknown_method_raises(self):
        class Svc(mutobj.Declaration):
            def run(self) -> str: ...

        # 完全没注册过任何 impl，链为空 → caller 不在链中 → RuntimeError
        with pytest.raises(RuntimeError):
            mutobj.call_super_impl(Svc.run, Svc())


# ---------- 函数同名不影响定位 ----------

class TestSameName:

    def test_homonymous_impls_resolved_by_module(self):
        class Svc(mutobj.Declaration):
            def run(self) -> str: ...

        # 两个 impl 函数都叫 _do —— 仅模块名区分
        mod_a = _make_module("super_homonym_mod_a")
        mod_a["Svc"] = Svc
        exec(
            "@mutobj.impl(Svc.run)\n"
            "def _do(self):\n"
            "    return 'A'\n",
            mod_a,
        )

        mod_b = _make_module("super_homonym_mod_b")
        mod_b["Svc"] = Svc
        exec(
            "@mutobj.impl(Svc.run)\n"
            "def _do(self):\n"
            "    return mutobj.call_super_impl(Svc.run, self) + 'B'\n",
            mod_b,
        )

        try:
            assert Svc().run() == "AB"
        finally:
            unregister_module_impls("super_homonym_mod_a")
            unregister_module_impls("super_homonym_mod_b")


# ---------- async ----------

class TestAsync:

    def test_async_super(self):
        class Svc(mutobj.Declaration):
            async def fetch(self, x: int) -> int: ...

        mod_a = _make_module("super_async_mod_a")
        mod_a["Svc"] = Svc
        exec(
            "@mutobj.impl(Svc.fetch)\n"
            "async def fetch(self, x):\n"
            "    return x * 2\n",
            mod_a,
        )

        mod_b = _make_module("super_async_mod_b")
        mod_b["Svc"] = Svc
        exec(
            "@mutobj.impl(Svc.fetch)\n"
            "async def fetch(self, x):\n"
            "    base = await mutobj.call_super_impl(Svc.fetch, self, x)\n"
            "    return base + 1\n",
            mod_b,
        )

        try:
            result = asyncio.run(Svc().fetch(5))
            assert result == 11  # 5*2 + 1
        finally:
            unregister_module_impls("super_async_mod_a")
            unregister_module_impls("super_async_mod_b")


# ---------- property ----------

class TestProperty:

    def test_property_getter_super(self):
        class Product(mutobj.Declaration):
            name: str

            @property
            def display_name(self) -> str: ...

        mod_a = _make_module("super_prop_mod_a")
        mod_a["Product"] = Product
        exec(
            "@mutobj.impl(Product.display_name.getter)\n"
            "def display_name(self):\n"
            "    return self.name.upper()\n",
            mod_a,
        )

        mod_b = _make_module("super_prop_mod_b")
        mod_b["Product"] = Product
        exec(
            "@mutobj.impl(Product.display_name.getter)\n"
            "def display_name(self):\n"
            "    return '[' + mutobj.call_super_impl(Product.display_name.getter, self) + ']'\n",
            mod_b,
        )

        try:
            assert Product(name="widget").display_name == "[WIDGET]"
        finally:
            unregister_module_impls("super_prop_mod_a")
            unregister_module_impls("super_prop_mod_b")

    def test_property_setter_super(self):
        class Counter(mutobj.Declaration):
            _value: int = 0

            @property
            def value(self) -> int: ...

            @value.setter
            def value(self, v: int) -> None: ...

        @mutobj.impl(Counter.value.getter)
        def _get(self: Counter) -> int:
            return self._value

        mod_a = _make_module("super_propset_mod_a")
        mod_a["Counter"] = Counter
        exec(
            "@mutobj.impl(Counter.value.setter)\n"
            "def _set(self, v):\n"
            "    self._value = v\n",
            mod_a,
        )

        mod_b = _make_module("super_propset_mod_b")
        mod_b["Counter"] = Counter
        exec(
            "@mutobj.impl(Counter.value.setter)\n"
            "def _set(self, v):\n"
            "    mutobj.call_super_impl(Counter.value.setter, self, v + 100)\n",
            mod_b,
        )

        try:
            c = Counter()
            c.value = 5
            assert c.value == 105
        finally:
            unregister_module_impls("super_propset_mod_a")
            unregister_module_impls("super_propset_mod_b")
            unregister_module_impls(__name__)


# ---------- classmethod / staticmethod ----------

class TestClassmethodStaticmethod:

    def test_classmethod_super(self):
        class Svc(mutobj.Declaration):
            @classmethod
            def make(cls, x: int) -> int: ...

        mod_a = _make_module("super_cm_mod_a")
        mod_a["Svc"] = Svc
        exec(
            "@mutobj.impl(Svc.make)\n"
            "def make(cls, x):\n"
            "    return x + 1\n",
            mod_a,
        )

        mod_b = _make_module("super_cm_mod_b")
        mod_b["Svc"] = Svc
        exec(
            "@mutobj.impl(Svc.make)\n"
            "def make(cls, x):\n"
            "    return mutobj.call_super_impl(Svc.make, cls, x) * 10\n",
            mod_b,
        )

        try:
            assert Svc.make(3) == 40
        finally:
            unregister_module_impls("super_cm_mod_a")
            unregister_module_impls("super_cm_mod_b")

    def test_staticmethod_super(self):
        class Svc(mutobj.Declaration):
            @staticmethod
            def calc(x: int) -> int: ...

        mod_a = _make_module("super_sm_mod_a")
        mod_a["Svc"] = Svc
        exec(
            "@mutobj.impl(Svc.calc)\n"
            "def calc(x):\n"
            "    return x + 1\n",
            mod_a,
        )

        mod_b = _make_module("super_sm_mod_b")
        mod_b["Svc"] = Svc
        exec(
            "@mutobj.impl(Svc.calc)\n"
            "def calc(x):\n"
            "    return mutobj.call_super_impl(Svc.calc, x) * 10\n",
            mod_b,
        )

        try:
            assert Svc.calc(3) == 40
        finally:
            unregister_module_impls("super_sm_mod_a")
            unregister_module_impls("super_sm_mod_b")


# ---------- 卸载中间层 ----------

class TestUnregisterMiddle:

    def test_unregister_middle_layer(self):
        """三层链 A→B→C，卸载中间层 B 后，C 调 super 应跳到 A。"""
        class Svc(mutobj.Declaration):
            def run(self, x: int) -> int: ...

        for name, body in [
            ("super_unreg_mod_a", "return x + 1"),
            ("super_unreg_mod_b", "return mutobj.call_super_impl(Svc.run, self, x) * 2"),
            ("super_unreg_mod_c", "return mutobj.call_super_impl(Svc.run, self, x) + 100"),
        ]:
            mod = _make_module(name)
            mod["Svc"] = Svc
            exec(
                f"@mutobj.impl(Svc.run)\n"
                f"def run(self, x):\n"
                f"    {body}\n",
                mod,
            )

        try:
            # 完整链：x=3 → A=4 → B=8 → C=108
            assert Svc().run(3) == 108

            # 卸载 B 后链变为 A→C
            unregister_module_impls("super_unreg_mod_b")
            # x=3 → A=4 → C=104
            assert Svc().run(3) == 104
        finally:
            unregister_module_impls("super_unreg_mod_a")
            unregister_module_impls("super_unreg_mod_b")
            unregister_module_impls("super_unreg_mod_c")
