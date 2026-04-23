"""Static type inference regression fixture for Declaration subclasses.

Goal: this file must produce **zero** pyright diagnostics when mutobj is
correctly typed. Any error/warning/info means a regression.

Verifies the fix from `docs/specifications/feature-declaration-static-type-support.md`:
- `Declaration.__new__` returns `Self`, so `MCPClient(...)` is inferred as
  `MCPClient` (not the base `Declaration`).
- Stub methods with `...` body are recognised as callables with the declared
  signature.
"""
from __future__ import annotations

from typing import Any, assert_type

import mutobj


class MCPClient(mutobj.Declaration):
    url: str = ""

    async def connect(self) -> None: ...
    async def call_tool(self, name: str, **arguments: Any) -> dict[str, Any]: ...
    async def close(self) -> None: ...


async def use_client() -> dict[str, Any]:
    client = MCPClient(url="http://example.com")
    assert_type(client, MCPClient)

    await client.connect()
    result: dict[str, Any] = await client.call_tool("pysandbox", code="print(1)")
    await client.close()
    return result
