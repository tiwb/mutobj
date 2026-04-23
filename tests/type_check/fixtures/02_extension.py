"""Extension subclass static type inference regression fixture.

Verifies that `Extension.get_or_create(...)` returns `Self` — i.e. calling
`_SessionExt.get_or_create(session)` yields `_SessionExt` (not the base
`Extension[Session]`), so that subclass-specific fields remain statically
visible.

This file must produce **zero** pyright diagnostics. Field names here use
public-style naming (no `_` prefix) so the fixture also passes pyright
strict mode, independent of any `reportPrivateUsage` configuration.
"""
from __future__ import annotations

from typing import assert_type

import mutobj


class Session(mutobj.Declaration):
    session_id: str = ""


class SessionExt(mutobj.Extension[Session]):
    channels: list[str] = mutobj.field(default_factory=list)
    client: object | None = None


def attach(session: Session, name: str) -> list[str]:
    ext = SessionExt.get_or_create(session)
    assert_type(ext, SessionExt)

    ext.channels.append(name)
    ext.client = object()
    return ext.channels


def lookup(session: Session) -> SessionExt | None:
    ext = SessionExt.get(session)
    assert_type(ext, SessionExt | None)
    return ext
