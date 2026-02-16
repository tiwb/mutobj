"""Tests for the impl override chain mechanism."""

import pytest
import mutobj
from mutobj.core import (
    _impl_chain,
    _module_first_seq,
    unregister_module_impls,
)


def _exec_class(source: str, module_name: str = "test_virtual"):
    """Helper: exec source code that defines a class, simulating module re-execution."""
    filename = f"mutobj://{module_name}"
    code = compile(source, filename, "exec")
    globs = {"__name__": module_name, "mutobj": mutobj}
    exec(code, globs)
    return globs


class TestOverrideChainBasic:
    """覆盖链基本测试"""

    def test_a_impl_b_override_unload_b_restores_a(self):
        """A impl → B override → 卸载 B → A 恢复"""
        class Svc(mutobj.Declaration):
            def run(self) -> str: ...

        def run_a(self) -> str:
            return "A"
        run_a.__module__ = "chain_mod_a"
        mutobj.impl(Svc.run)(run_a)

        s = Svc()
        assert s.run() == "A"

        def run_b(self) -> str:
            return "B"
        run_b.__module__ = "chain_mod_b"
        mutobj.impl(Svc.run)(run_b)

        assert s.run() == "B"

        unregister_module_impls("chain_mod_b")
        assert s.run() == "A"

    def test_a_b_c_unload_b_c_still_active(self):
        """A impl → B override → C override → 卸载 B → C 仍活跃"""
        class Svc2(mutobj.Declaration):
            def run(self) -> str: ...

        def run_a(self) -> str:
            return "A"
        run_a.__module__ = "chain2_mod_a"
        mutobj.impl(Svc2.run)(run_a)

        def run_b(self) -> str:
            return "B"
        run_b.__module__ = "chain2_mod_b"
        mutobj.impl(Svc2.run)(run_b)

        def run_c(self) -> str:
            return "C"
        run_c.__module__ = "chain2_mod_c"
        mutobj.impl(Svc2.run)(run_c)

        s = Svc2()
        assert s.run() == "C"

        # 卸载中间层 B
        unregister_module_impls("chain2_mod_b")
        # C 仍为活跃实现
        assert s.run() == "C"

    def test_unload_all_external_restores_default(self):
        """全部外部 impl 卸载 → 默认实现恢复"""
        class Svc3(mutobj.Declaration):
            def run(self) -> str: ...

        def run_a(self) -> str:
            return "A"
        run_a.__module__ = "chain3_mod_a"
        mutobj.impl(Svc3.run)(run_a)

        s = Svc3()
        assert s.run() == "A"

        unregister_module_impls("chain3_mod_a")
        # 恢复默认实现（方法体为 ...，返回 None）
        assert s.run() is None

    def test_unload_nonexistent_module_noop(self):
        """卸载不存在的模块 → 无操作"""
        count = unregister_module_impls("nonexistent_chain_module_xyz")
        assert count == 0


class TestOverrideChainReload:
    """覆盖链 reload 测试"""

    def test_middle_layer_reload_top_stays_active(self):
        """A → B → C → reload B → C 仍活跃（中间层 reload）"""
        class Svc4(mutobj.Declaration):
            def run(self) -> str: ...

        def run_a(self) -> str:
            return "A"
        run_a.__module__ = "chain4_mod_a"
        mutobj.impl(Svc4.run)(run_a)

        def run_b(self) -> str:
            return "B"
        run_b.__module__ = "chain4_mod_b"
        mutobj.impl(Svc4.run)(run_b)

        def run_c(self) -> str:
            return "C"
        run_c.__module__ = "chain4_mod_c"
        mutobj.impl(Svc4.run)(run_c)

        s = Svc4()
        assert s.run() == "C"

        # 模拟 reload B（同模块就地替换）
        def run_b_v2(self) -> str:
            return "B_v2"
        run_b_v2.__module__ = "chain4_mod_b"
        mutobj.impl(Svc4.run)(run_b_v2)

        # C 仍为活跃实现（中间层 reload 不影响链顶）
        assert s.run() == "C"

    def test_top_layer_reload_updates_active(self):
        """A → B → reload B → B 更新为新函数（链顶 reload）"""
        class Svc5(mutobj.Declaration):
            def run(self) -> str: ...

        def run_a(self) -> str:
            return "A"
        run_a.__module__ = "chain5_mod_a"
        mutobj.impl(Svc5.run)(run_a)

        def run_b(self) -> str:
            return "B"
        run_b.__module__ = "chain5_mod_b"
        mutobj.impl(Svc5.run)(run_b)

        s = Svc5()
        assert s.run() == "B"

        # 模拟 reload B（同模块就地替换，B 仍在链顶）
        def run_b_v2(self) -> str:
            return "B_v2"
        run_b_v2.__module__ = "chain5_mod_b"
        mutobj.impl(Svc5.run)(run_b_v2)

        assert s.run() == "B_v2"

    def test_unregister_reimport_reuses_seq(self):
        """A → B → C → 卸载 B + reimport → B 回到原位置，C 仍活跃"""
        class Svc6(mutobj.Declaration):
            def run(self) -> str: ...

        def run_a(self) -> str:
            return "A"
        run_a.__module__ = "chain6_mod_a"
        mutobj.impl(Svc6.run)(run_a)

        def run_b(self) -> str:
            return "B"
        run_b.__module__ = "chain6_mod_b"
        mutobj.impl(Svc6.run)(run_b)

        def run_c(self) -> str:
            return "C"
        run_c.__module__ = "chain6_mod_c"
        mutobj.impl(Svc6.run)(run_c)

        s = Svc6()
        assert s.run() == "C"

        # 卸载 B
        unregister_module_impls("chain6_mod_b")
        assert s.run() == "C"  # C 仍活跃

        # Reimport B（通过 _module_first_seq 复用序号回到原位置）
        def run_b_v2(self) -> str:
            return "B_v2"
        run_b_v2.__module__ = "chain6_mod_b"
        mutobj.impl(Svc6.run)(run_b_v2)

        # C 仍为活跃实现（B 序号低于 C）
        assert s.run() == "C"

        # 卸载 C 后 B 恢复
        unregister_module_impls("chain6_mod_c")
        assert s.run() == "B_v2"


class TestDeclarationReloadWithChain:
    """Declaration 类 reload 与覆盖链的交互"""

    def test_declaration_reload_no_external_impl(self):
        """Declaration reload（无外部 impl）→ 默认实现更新为新函数"""
        g1 = _exec_class(
            "class R1(mutobj.Declaration):\n"
            "    def work(self) -> str:\n"
            "        return 'v1'\n",
            "reload_chain_mod_1"
        )
        cls = g1["R1"]
        obj = cls()
        assert obj.work() == "v1"

        # Reload with new default
        g2 = _exec_class(
            "class R1(mutobj.Declaration):\n"
            "    def work(self) -> str:\n"
            "        return 'v2'\n",
            "reload_chain_mod_1"
        )
        cls2 = g2["R1"]
        assert cls is cls2
        assert obj.work() == "v2"

    def test_declaration_reload_with_external_impl(self):
        """Declaration reload（有外部 impl）→ 默认实现更新，外部 impl 保留且仍为活跃"""
        g1 = _exec_class(
            "class R2(mutobj.Declaration):\n"
            "    def work(self) -> str:\n"
            "        return 'default_v1'\n",
            "reload_chain_mod_2"
        )
        cls = g1["R2"]

        def work_impl(self) -> str:
            return "impl"
        work_impl.__module__ = "reload_chain_ext_mod"
        mutobj.impl(cls.work)(work_impl)

        obj = cls()
        assert obj.work() == "impl"

        # Reload Declaration
        g2 = _exec_class(
            "class R2(mutobj.Declaration):\n"
            "    def work(self) -> str:\n"
            "        return 'default_v2'\n",
            "reload_chain_mod_2"
        )
        cls2 = g2["R2"]
        assert cls is cls2

        # 外部 impl 仍为活跃
        assert obj.work() == "impl"

        # 卸载外部 impl 后恢复为新默认实现
        unregister_module_impls("reload_chain_ext_mod")
        assert obj.work() == "default_v2"

    def test_declaration_reload_external_impl_already_unloaded(self):
        """Declaration reload（外部 impl 已卸载）→ 默认实现更新并恢复为活跃"""
        g1 = _exec_class(
            "class R3(mutobj.Declaration):\n"
            "    def work(self) -> str:\n"
            "        return 'default_v1'\n",
            "reload_chain_mod_3"
        )
        cls = g1["R3"]

        def work_impl(self) -> str:
            return "impl"
        work_impl.__module__ = "reload_chain_ext_mod_3"
        mutobj.impl(cls.work)(work_impl)

        obj = cls()
        assert obj.work() == "impl"

        # 卸载外部 impl
        unregister_module_impls("reload_chain_ext_mod_3")
        assert obj.work() == "default_v1"

        # Reload Declaration with new default
        g2 = _exec_class(
            "class R3(mutobj.Declaration):\n"
            "    def work(self) -> str:\n"
            "        return 'default_v2'\n",
            "reload_chain_mod_3"
        )
        cls2 = g2["R3"]
        assert cls is cls2

        # 默认实现更新为新函数
        assert obj.work() == "default_v2"


class TestOverrideChainProperty:
    """覆盖链 property 测试"""

    def test_property_getter_override_chain(self):
        """property getter 的覆盖链：A impl → B override → 卸载 B → A 恢复"""
        class PropSvc(mutobj.Declaration):
            @property
            def value(self) -> str: ...

        def getter_a(self) -> str:
            return "A"
        getter_a.__module__ = "prop_chain_mod_a"
        mutobj.impl(PropSvc.value.getter)(getter_a)

        obj = PropSvc()
        assert obj.value == "A"

        def getter_b(self) -> str:
            return "B"
        getter_b.__module__ = "prop_chain_mod_b"
        mutobj.impl(PropSvc.value.getter)(getter_b)

        assert obj.value == "B"

        unregister_module_impls("prop_chain_mod_b")
        assert obj.value == "A"

    def test_property_setter_override_chain(self):
        """property setter 的覆盖链"""
        class PropSvc2(mutobj.Declaration):
            _val: str

            @property
            def value(self) -> str: ...

        def getter(self) -> str:
            return self._val
        getter.__module__ = "prop_chain2_getter"
        mutobj.impl(PropSvc2.value.getter)(getter)

        def setter_a(self, v: str) -> None:
            self._val = f"A:{v}"
        setter_a.__module__ = "prop_chain2_mod_a"
        mutobj.impl(PropSvc2.value.setter)(setter_a)

        obj = PropSvc2()
        obj.value = "test"
        assert obj.value == "A:test"

        def setter_b(self, v: str) -> None:
            self._val = f"B:{v}"
        setter_b.__module__ = "prop_chain2_mod_b"
        mutobj.impl(PropSvc2.value.setter)(setter_b)

        obj.value = "test"
        assert obj.value == "B:test"

        unregister_module_impls("prop_chain2_mod_b")
        obj.value = "test"
        assert obj.value == "A:test"


class TestOverrideChainClassmethodStaticmethod:
    """覆盖链 classmethod/staticmethod 测试"""

    def test_classmethod_override_chain(self):
        """classmethod 的覆盖链"""
        class CmSvc(mutobj.Declaration):
            @classmethod
            def create(cls) -> str: ...

        def create_a(cls) -> str:
            return "A"
        create_a.__module__ = "cm_chain_mod_a"
        mutobj.impl(CmSvc.create)(create_a)

        assert CmSvc.create() == "A"

        def create_b(cls) -> str:
            return "B"
        create_b.__module__ = "cm_chain_mod_b"
        mutobj.impl(CmSvc.create)(create_b)

        assert CmSvc.create() == "B"

        unregister_module_impls("cm_chain_mod_b")
        assert CmSvc.create() == "A"

    def test_staticmethod_override_chain(self):
        """staticmethod 的覆盖链"""
        class SmSvc(mutobj.Declaration):
            @staticmethod
            def helper() -> str: ...

        def helper_a() -> str:
            return "A"
        helper_a.__module__ = "sm_chain_mod_a"
        mutobj.impl(SmSvc.helper)(helper_a)

        assert SmSvc.helper() == "A"

        def helper_b() -> str:
            return "B"
        helper_b.__module__ = "sm_chain_mod_b"
        mutobj.impl(SmSvc.helper)(helper_b)

        assert SmSvc.helper() == "B"

        unregister_module_impls("sm_chain_mod_b")
        assert SmSvc.helper() == "A"


class TestDefaultImplVariants:
    """测试不同方法体形式的默认实现"""

    def test_ellipsis_body_as_default(self):
        """方法体为 ... 保存为默认实现"""
        class D1(mutobj.Declaration):
            def work(self) -> str: ...

        obj = D1()
        # ... 是表达式，函数隐式返回 None
        assert obj.work() is None

    def test_pass_body_as_default(self):
        """方法体为 pass 保存为默认实现"""
        class D2(mutobj.Declaration):
            def work(self) -> None:
                pass

        obj = D2()
        assert obj.work() is None

    def test_real_code_body_as_default(self):
        """方法体有实际代码也保存为默认实现"""
        class D3(mutobj.Declaration):
            def work(self) -> str:
                return "default_impl"

        obj = D3()
        assert obj.work() == "default_impl"

        # @impl 覆盖后
        @mutobj.impl(D3.work)
        def work_impl(self) -> str:
            return "override"

        assert obj.work() == "override"

    def test_all_body_types_are_declared(self):
        """所有方法体形式都被识别为声明方法"""
        from mutobj.core import _DECLARED_METHODS

        class D4(mutobj.Declaration):
            def m1(self) -> str: ...
            def m2(self) -> None: pass
            def m3(self) -> str: return "hello"

        declared = getattr(D4, _DECLARED_METHODS, set())
        assert "m1" in declared
        assert "m2" in declared
        assert "m3" in declared
