from __future__ import annotations

from typing import assert_type

import mutobj


class Loader(mutobj.Declaration):
    path: str

    def load(self) -> str: ...


class LoaderImpl(mutobj.Implementation[Loader]):
    cache: dict[str, str]

    def load(self) -> str:
        owner = mutobj.implementation_owner(self)
        assert_type(owner, Loader)
        return owner.path


def use(loader: Loader) -> str:
    impl = mutobj.implementation_of(loader, LoaderImpl)
    assert_type(impl, LoaderImpl)

    impl.cache = {}

    owner = mutobj.implementation_owner(impl)
    assert_type(owner, Loader)

    impl_cls = mutobj.implementation_class(Loader)
    assert_type(impl_cls, type[mutobj.Implementation[Loader]])

    return impl.load()
