MUTABLE_TYPES = (list, dict, set, bytearray)

DECLARATION_CHAIN_HOOKS = frozenset({
    "__init__",
    "__post_init__",
})

MUTOBJ_RESERVED_DUNDERS = frozenset({
    "__new__",
    "__init_subclass__",
    "__class_getitem__",
    "__set_name__",
    "__subclasshook__",
    "__instancecheck__",
    "__subclasscheck__",
})

# 内部基础设施属性——不进 field 系统，不被 process_field_annotations 包装。
MUTOBJ_INFRA_ATTRS = frozenset({
    "__mutobj_storage__",
    "target",
})

DECLARATION_USER_HOOKS = frozenset({
    "__post_init__",
})

def is_dunder(name: str) -> bool:
    """Python 语言约定保留命名空间：以 __ 开头且结尾（不含空壳如 ____）。"""
    return len(name) > 4 and name.startswith("__") and name.endswith("__")
