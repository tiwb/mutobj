"""Tests for mutobj impl introspection and descriptor metadata APIs."""

from __future__ import annotations

import warnings

import mutobj


class TestImplHas:

    def test_ellipsis_body_counts_as_default_impl(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> None: ...

        assert mutobj.impl_has(Svc.run) is True
        assert mutobj.impl_has_override(Svc.run) is False

    def test_pass_body_counts_as_default_impl(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> None:
                pass

        assert mutobj.impl_has(Svc.run) is True
        assert mutobj.impl_has_override(Svc.run) is False

    def test_explicit_notimplemented_is_not_treated_as_real_impl(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> None:
                raise NotImplementedError

        assert mutobj.impl_has(Svc.run) is False
        assert mutobj.impl_has_override(Svc.run) is False

    def test_real_default_body_counts_as_impl(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> int:
                return 1

        assert mutobj.impl_has(Svc.run) is True
        assert mutobj.impl_has_override(Svc.run) is False

    def test_impl_override_sets_override_flag(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> None: ...

        @mutobj.impl(Svc.run)
        def run(self) -> int:
            return 7

        assert mutobj.impl_has(Svc.run) is True
        assert mutobj.impl_has_override(Svc.run) is True

    def test_inherited_delegate_from_unimplemented_base_is_false(self) -> None:
        class Base(mutobj.Declaration):
            def run(self) -> None:
                raise NotImplementedError

        class Child(Base):
            pass

        assert mutobj.impl_has(Child.run) is False
        assert mutobj.impl_has_override(Child.run) is False

    def test_inherited_delegate_from_real_base_is_true(self) -> None:
        class Base(mutobj.Declaration):
            def run(self) -> str:
                return "ok"

        class Child(Base):
            pass

        assert mutobj.impl_has(Child.run) is True
        assert mutobj.impl_has_override(Child.run) is False


class TestImplChain:

    def test_impl_chain_returns_copy(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self) -> int:
                return 1

        chain = mutobj.impl_chain(Svc.run)
        assert len(chain) == 1
        chain.clear()
        assert len(mutobj.impl_chain(Svc.run)) == 1


class TestImplCallSuperAlias:

    def test_impl_call_super_alias_works(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self, x: int) -> int:
                return x + 1

        @mutobj.impl(Svc.run)
        def run(self, x: int) -> int:
            return mutobj.impl_call_super(Svc.run, self, x) * 10

        assert Svc().run(3) == 40

    def test_call_super_impl_warns_and_delegates(self) -> None:
        class Svc(mutobj.Declaration):
            def run(self, x: int) -> int:
                return x + 1

        @mutobj.impl(Svc.run)
        def run(self, x: int) -> int:
            with warnings.catch_warnings(record=True) as records:
                warnings.simplefilter("always")
                result = mutobj.call_super_impl(Svc.run, self, x)
            assert result == 4
            assert any(issubclass(r.category, DeprecationWarning) for r in records)
            return result * 10

        assert Svc().run(3) == 40


class TestAttributeDescriptorDefaults:

    def test_get_default_returns_scalar_default(self) -> None:
        class Item(mutobj.Declaration):
            count: int = 3

        assert Item.count.get_default() == 3
        assert Item.count.make_default() == 3

    def test_get_default_returns_factory_and_make_default_executes_it(self) -> None:
        class Item(mutobj.Declaration):
            entries: list[int] = mutobj.field(default_factory=lambda: [1, 2, 3])

        factory = Item.entries.get_default()
        assert callable(factory)
        assert factory() == [1, 2, 3]
        made = Item.entries.make_default()
        assert made == [1, 2, 3]
        assert made is not factory()

    def test_get_default_without_default_raises(self) -> None:
        class Item(mutobj.Declaration):
            value: int

        try:
            Item.value.get_default()
        except ValueError as exc:
            assert "has no default" in str(exc)
        else:
            raise AssertionError("expected ValueError")

    def test_make_default_without_default_raises(self) -> None:
        class Item(mutobj.Declaration):
            value: int

        try:
            Item.value.make_default()
        except ValueError as exc:
            assert "has no default" in str(exc)
        else:
            raise AssertionError("expected ValueError")
