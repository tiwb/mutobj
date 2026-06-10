DECLARED_METHODS: str = "__mutobj_declared_methods__"
DECLARED_CLASSMETHODS: str = "__mutobj_declared_classmethods__"
DECLARED_STATICMETHODS: str = "__mutobj_declared_staticmethods__"

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

DECLARATION_USER_HOOKS = frozenset({
    "__post_init__",
})
