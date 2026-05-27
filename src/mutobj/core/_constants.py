_DECLARED_METHODS: str = "__mutobj_declared_methods__"
_DECLARED_PROPERTIES: str = "__mutobj_declared_properties__"
_DECLARED_CLASSMETHODS: str = "__mutobj_declared_classmethods__"
_DECLARED_STATICMETHODS: str = "__mutobj_declared_staticmethods__"

_MUTABLE_TYPES = (list, dict, set, bytearray)

_MUTOBJ_RESERVED_DUNDERS = frozenset({
    "__new__",
    "__init_subclass__",
    "__class_getitem__",
    "__set_name__",
    "__subclasshook__",
    "__instancecheck__",
    "__subclasscheck__",
})

_DECLARATION_USER_HOOKS = frozenset({
    "__post_init__",
})
