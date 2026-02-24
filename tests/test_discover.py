"""Tests for discover_subclasses and get_registry_generation."""

import mutobj
from mutobj.core import _class_registry, _impl_chain


class TestDiscoverSubclasses:

    def test_discover_basic(self):
        """定义 A(Declaration), B(A), C(A)，discover_subclasses(A) 返回 {B, C}"""
        class A(mutobj.Declaration):
            def run(self) -> str: ...

        class B(A):
            pass

        class C(A):
            pass

        result = mutobj.discover_subclasses(A)
        assert set(result) == {B, C}

    def test_discover_deep(self):
        """定义 A, B(A), C(B)，discover_subclasses(A) 返回 {B, C}"""
        class A(mutobj.Declaration):
            def run(self) -> str: ...

        class B(A):
            pass

        class C(B):
            pass

        result = mutobj.discover_subclasses(A)
        assert set(result) == {B, C}

    def test_discover_empty(self):
        """无子类时返回空列表"""
        class Lonely(mutobj.Declaration):
            def run(self) -> str: ...

        result = mutobj.discover_subclasses(Lonely)
        assert result == []

    def test_discover_excludes_base(self):
        """base_cls 自身不在结果中"""
        class Base(mutobj.Declaration):
            def run(self) -> str: ...

        class Child(Base):
            pass

        result = mutobj.discover_subclasses(Base)
        assert Base not in result
        assert Child in result

    def test_discover_after_unregister(self):
        """模块卸载后，通过从 _class_registry 移除类来验证不再被发现"""
        class Base2(mutobj.Declaration):
            def run(self) -> str: ...

        class Sub2(Base2):
            pass

        assert Sub2 in mutobj.discover_subclasses(Base2)

        # 模拟模块卸载：从 registry 中移除 Sub2
        key_to_remove = None
        for key, cls in _class_registry.items():
            if cls is Sub2:
                key_to_remove = key
                break
        assert key_to_remove is not None
        del _class_registry[key_to_remove]

        assert Sub2 not in mutobj.discover_subclasses(Base2)

    def test_discover_non_declaration(self):
        """传入非 Declaration 类返回空列表"""
        result = mutobj.discover_subclasses(int)
        assert result == []


class TestGetRegistryGeneration:

    def test_generation_increments_on_class_define(self):
        """定义新 Declaration 子类后 generation 递增"""
        gen_before = mutobj.get_registry_generation()

        class NewCls(mutobj.Declaration):
            def run(self) -> str: ...

        gen_after = mutobj.get_registry_generation()
        assert gen_after > gen_before

    def test_generation_increments_on_impl(self):
        """@impl 注册后 generation 递增"""
        class Svc(mutobj.Declaration):
            def run(self) -> str: ...

        gen_before = mutobj.get_registry_generation()

        @mutobj.impl(Svc.run)
        def run(self: object) -> str:
            return "ok"

        gen_after = mutobj.get_registry_generation()
        assert gen_after > gen_before

    def test_generation_increments_on_unregister(self):
        """模块卸载后 generation 递增"""
        class Svc2(mutobj.Declaration):
            def run(self) -> str: ...

        def run_impl(self: object) -> str:
            return "impl"
        run_impl.__module__ = "fake_module_for_gen_test"
        mutobj.impl(Svc2.run)(run_impl)

        gen_before = mutobj.get_registry_generation()
        removed = mutobj.unregister_module_impls("fake_module_for_gen_test")
        gen_after = mutobj.get_registry_generation()

        assert removed >= 1
        assert gen_after > gen_before

    def test_generation_stable_without_changes(self):
        """无操作时 generation 保持不变"""
        gen1 = mutobj.get_registry_generation()
        gen2 = mutobj.get_registry_generation()
        assert gen1 == gen2

    def test_generation_as_short_circuit(self):
        """验证 generation 不变时可安全跳过扫描"""
        class Base3(mutobj.Declaration):
            def run(self) -> str: ...

        gen1 = mutobj.get_registry_generation()
        result1 = mutobj.discover_subclasses(Base3)

        gen2 = mutobj.get_registry_generation()
        assert gen1 == gen2  # 无变更，generation 不变

        # 新增子类后 generation 变化
        class Sub3(Base3):
            pass

        gen3 = mutobj.get_registry_generation()
        assert gen3 > gen2  # generation 递增，需要重新扫描

        result2 = mutobj.discover_subclasses(Base3)
        assert Sub3 in result2
        assert len(result2) > len(result1)

    def test_generation_no_increment_on_empty_unregister(self):
        """卸载不存在的模块不递增 generation"""
        gen_before = mutobj.get_registry_generation()
        removed = mutobj.unregister_module_impls("nonexistent.module.xyz.gen")
        gen_after = mutobj.get_registry_generation()

        assert removed == 0
        assert gen_after == gen_before
