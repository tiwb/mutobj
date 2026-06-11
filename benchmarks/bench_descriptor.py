"""AttributeDescriptor get/set 性能基准测试。

用法:
    # 保存基线
    python benchmarks/bench_descriptor.py -o baseline.json

    # 改代码后再跑，自动对比
    python benchmarks/bench_descriptor.py -o v2.json
    python -m pyperf compare_to baseline.json v2.json --table
"""

from __future__ import annotations

import pyperf

# -- 共享 setup 模板 ------------------------------------------------

_COMMON_SETUP = """
from mutobj.core._fields import AttributeDescriptor, MISSING

class Obj:
    __slots__ = ("__mutobj_storage__",)
    def __init__(self, storage):
        self.__mutobj_storage__ = storage

# --- 已赋值字段 get ---
desc_hit = AttributeDescriptor("x", int, default=0)
obj_hit = Obj({"x": 42})

# --- 默认值字段 get ---
desc_default = AttributeDescriptor("x", int, default=0)
obj_default = Obj({})

# --- 有 impl getter ---
def custom_get(obj):
    return obj.__mutobj_storage__.get("x", 0) * 2

desc_impl_g = AttributeDescriptor("x", int, default=0)
desc_impl_g.fget = custom_get
obj_impl_g = Obj({"x": 42})

# --- 字段 set ---
desc_set = AttributeDescriptor("x", int)
obj_set = Obj({"x": 0})

# --- 有 impl setter ---
def custom_set(obj, v):
    obj.__mutobj_storage__["x"] = v

desc_impl_s = AttributeDescriptor("x", int)
desc_impl_s.fset = custom_set
obj_impl_s = Obj({"x": 0})
"""


def main() -> None:
    runner = pyperf.Runner()

    # baseline: 直接 dict 访问
    runner.timeit(
        "baseline: dict get (hit)",
        stmt="d['x']",
        setup="d = {'x': 42}",
    )
    runner.timeit(
        "baseline: dict get (miss→default)",
        stmt="d.get('x', 0)",
        setup="d = {}",
    )
    runner.timeit(
        "baseline: dict set",
        stmt="d['x'] = v",
        setup="d = {'x': 0}; v = 42",
    )

    # descriptor: 已赋值 get
    runner.timeit(
        "desc: get (hit)",
        stmt="desc_hit.__get__(obj_hit, type(obj_hit))",
        setup=_COMMON_SETUP,
    )

    # descriptor: 默认值 get
    runner.timeit(
        "desc: get (default)",
        stmt="desc_default.__get__(obj_default, type(obj_default))",
        setup=_COMMON_SETUP,
    )

    # descriptor: impl getter
    runner.timeit(
        "desc: impl getter",
        stmt="desc_impl_g.__get__(obj_impl_g, type(obj_impl_g))",
        setup=_COMMON_SETUP,
    )

    # descriptor: set
    runner.timeit(
        "desc: set",
        stmt="desc_set.__set__(obj_set, 42)",
        setup=_COMMON_SETUP,
    )

    # descriptor: impl setter
    runner.timeit(
        "desc: impl setter",
        stmt="desc_impl_s.__set__(obj_impl_s, 42)",
        setup=_COMMON_SETUP,
    )


if __name__ == "__main__":
    main()
