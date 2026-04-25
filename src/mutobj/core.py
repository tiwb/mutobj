"""
mutobj 核心模块

包含 Declaration 基类、Extension 泛型基类和 impl 装饰器
"""

from __future__ import annotations

import importlib
import sys
import weakref
from typing import TypeVar, Generic, Callable, Any, Self

__all__ = ["Declaration", "Extension", "impl", "call_super_impl", "unregister_module_impls", "field", "MISSING",
           "discover_subclasses", "get_registry_generation", "resolve_class",
           "extensions", "extension_types"]

# 类型变量
T = TypeVar("T", bound="Declaration")

# 实现覆盖链：{(类, 方法名或属性访问器): [(实现函数, 来源模块, 注册序号), ...]}
# 按注册序号排序，列表尾部（最高序号）= 当前活跃实现
_impl_chain: dict[tuple[type, str], list[tuple[Callable[..., Any], str, int]]] = {}

# 全局注册序号计数器
_impl_seq: int = 0

# 模块首次注册序号（reload 时复用，保持链中位置不变）
_module_first_seq: dict[tuple[type, str, str], int] = {}  # (cls, key, module) -> seq

# 全局属性注册表: {类: {属性名: 类型注解}}
_attribute_registry: dict[type, dict[str, Any]] = {}

# 全局 property 注册表: {类: {property名: Property}}
_property_registry: dict[type, dict[str, "Property"]] = {}

# 全局类注册表: {(模块名, qualname): 类}，用于 reload 时的 in-place 更新
_class_registry: dict[tuple[str, str], type] = {}

# 注册表全局 generation 计数器：类注册/更新、@impl 注册/卸载时递增
_registry_generation: int = 0

# 声明方法标记
_DECLARED_METHODS: str = "__mutobj_declared_methods__"

# 声明 property 标记
_DECLARED_PROPERTIES: str = "__mutobj_declared_properties__"

# 声明 classmethod 标记
_DECLARED_CLASSMETHODS: str = "__mutobj_declared_classmethods__"

# 声明 staticmethod 标记
_DECLARED_STATICMETHODS: str = "__mutobj_declared_staticmethods__"

# 可变类型黑名单（直接赋值时报错，引导使用 field(default_factory=...)）
_MUTABLE_TYPES = (list, dict, set, bytearray)

# 不参与声明-实现机制的保留 dunder
# 这些是 Python 类协议钩子，注册它们会破坏类机制（实例化、子类创建、描述符等）
# 用户在 namespace 里显式定义的其他方法（含 __init__/__call__/_helper 等）一律走注册流程
_MUTOBJ_RESERVED_DUNDERS = frozenset({
    "__new__",                  # 实例化协议，Declaration 自己用
    "__init_subclass__",        # 子类创建钩子
    "__class_getitem__",        # 泛型语法 cls[T]
    "__set_name__",             # 描述符协议
    "__subclasshook__",         # ABC 子类判断
    "__instancecheck__",        # isinstance 钩子
    "__subclasscheck__",        # issubclass 钩子
})

# Declaration 基类上允许被标准注册流程处理的"用户钩子"白名单。
# 这些钩子默认 no-op,签名固定,可被 @impl 追加式覆盖,且每个子类应有独立委托。
# Declaration 自身的 __init__ / __new__ 等框架方法不进白名单 — 那些不是 hook,
# 而是构造协议的核心,不能被自动委托替换。
_DECLARATION_USER_HOOKS = frozenset({
    "__post_init__",
})


class _MissingSentinel:
    """默认值缺失哨兵，区分"无默认值"和"默认值为 None" """
    _instance: _MissingSentinel | None = None

    def __new__(cls) -> _MissingSentinel:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING: Any = _MissingSentinel()
_MISSING: Any = MISSING


class Field:
    """属性默认值描述，由 field() 创建"""

    __slots__ = ("default", "default_factory", "init")

    def __init__(
        self,
        default: Any = _MISSING,
        default_factory: Callable[[], Any] | None = None,
        init: bool = True,
    ) -> None:
        if default is not _MISSING and default_factory is not None:
            raise TypeError("cannot specify both default and default_factory")
        self.default = default
        self.default_factory = default_factory
        self.init = init


def field(
    *,
    default: Any = _MISSING,
    default_factory: Callable[[], Any] | None = None,
    init: bool = True,
) -> Any:
    """声明属性的默认值

    Args:
        default: 不可变默认值
        default_factory: 可变默认值的工厂函数，每次实例化时调用
        init: 是否参与构造参数绑定

    Returns:
        Field 哨兵对象（DeclarationMeta 会识别并提取）
    """
    return Field(default=default, default_factory=default_factory, init=init)


def _make_stub_method(name: str, cls: type) -> Callable[..., Any]:
    """创建一个桩方法，调用时抛出 NotImplementedError（覆盖链为空的异常回退）"""
    def stub(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            f"Method '{name}' is declared in {cls.__name__} but not implemented. "
            f"Use @mutobj.impl({cls.__name__}.{name}) to provide implementation."
        )
    stub.__name__ = name
    stub.__qualname__ = f"{cls.__name__}.{name}"
    stub.__mutobj_class__ = cls
    return stub


def _make_stub_classmethod(name: str, cls: type) -> classmethod[Any, ..., Any]:
    """创建一个 classmethod 桩方法（覆盖链为空的异常回退）"""
    def stub(cls_arg: type, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            f"Classmethod '{name}' is declared in {cls.__name__} but not implemented. "
            f"Use @mutobj.impl({cls.__name__}.{name}) to provide implementation."
        )
    stub.__name__ = name
    stub.__qualname__ = f"{cls.__name__}.{name}"
    stub.__mutobj_class__ = cls
    stub.__mutobj_is_classmethod__ = True
    return classmethod(stub)


def _make_stub_staticmethod(name: str, cls: type) -> staticmethod[Any, Any]:
    """创建一个 staticmethod 桩方法（覆盖链为空的异常回退）"""
    def stub(*args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            f"Staticmethod '{name}' is declared in {cls.__name__} but not implemented. "
            f"Use @mutobj.impl({cls.__name__}.{name}) to provide implementation."
        )
    stub.__name__ = name
    stub.__qualname__ = f"{cls.__name__}.{name}"
    stub.__mutobj_class__ = cls
    stub.__mutobj_is_staticmethod__ = True
    return staticmethod(stub)


def _apply_impl(cls: type, impl_key: str, func: Callable[..., Any]) -> None:
    """将实现应用到类上"""
    if impl_key.endswith(".getter"):
        prop_name = impl_key[:-7]
        prop = _property_registry.get(cls, {}).get(prop_name)
        if prop is not None:
            prop._fget = func  # pyright: ignore[reportPrivateUsage]
    elif impl_key.endswith(".setter"):
        prop_name = impl_key[:-7]
        prop = _property_registry.get(cls, {}).get(prop_name)
        if prop is not None:
            prop._fset = func  # pyright: ignore[reportPrivateUsage]
    else:
        declared_cm: set[str] = getattr(cls, _DECLARED_CLASSMETHODS, set())
        declared_sm: set[str] = getattr(cls, _DECLARED_STATICMETHODS, set())
        if impl_key in declared_cm:
            setattr(cls, impl_key, classmethod(func))
        elif impl_key in declared_sm:
            setattr(cls, impl_key, staticmethod(func))
        else:
            setattr(cls, impl_key, func)


def _restore_stub(cls: type, impl_key: str) -> None:
    """恢复桩方法（覆盖链异常为空时使用）"""
    if impl_key.endswith(".getter"):
        prop_name = impl_key[:-7]
        prop = _property_registry.get(cls, {}).get(prop_name)
        if prop is not None:
            prop._fget = None  # pyright: ignore[reportPrivateUsage]
    elif impl_key.endswith(".setter"):
        prop_name = impl_key[:-7]
        prop = _property_registry.get(cls, {}).get(prop_name)
        if prop is not None:
            prop._fset = None  # pyright: ignore[reportPrivateUsage]
    else:
        declared_cm: set[str] = getattr(cls, _DECLARED_CLASSMETHODS, set())
        declared_sm: set[str] = getattr(cls, _DECLARED_STATICMETHODS, set())
        if impl_key in declared_cm:
            setattr(cls, impl_key, _make_stub_classmethod(impl_key, cls))
        elif impl_key in declared_sm:
            setattr(cls, impl_key, _make_stub_staticmethod(impl_key, cls))
        else:
            setattr(cls, impl_key, _make_stub_method(impl_key, cls))


def _register_to_chain(
    target_cls: type,
    impl_key: str,
    func: Callable[..., Any],
    source_module: str,
) -> bool:
    """注册实现到覆盖链

    Returns:
        是否成为链顶（活跃实现）
    """
    global _impl_seq
    global _registry_generation

    key = (target_cls, impl_key)
    chain = _impl_chain.setdefault(key, [])
    seq_key = (target_cls, impl_key, source_module)

    # 1. 检查同模块已有注册（importlib.reload 直接重新执行，未卸载）
    existing_idx = next(
        (i for i, (_, m, _) in enumerate(chain) if m == source_module), None
    )
    if existing_idx is not None:
        old_seq = chain[existing_idx][2]
        chain[existing_idx] = (func, source_module, old_seq)
        _registry_generation += 1
        return existing_idx == len(chain) - 1

    # 2. 检查卸载后重新注册（unregister + reimport）
    if seq_key in _module_first_seq:
        seq = _module_first_seq[seq_key]
    else:
        # 3. 全新注册
        _impl_seq += 1
        seq = _impl_seq
        _module_first_seq[seq_key] = seq

    chain.append((func, source_module, seq))
    chain.sort(key=lambda x: x[2])
    _registry_generation += 1
    return chain[-1][1] == source_module


class AttributeDescriptor:
    """属性描述符，用于拦截属性访问"""

    def __init__(
        self,
        name: str,
        annotation: Any,
        default: Any = _MISSING,
        default_factory: Callable[[], Any] | None = None,
        init: bool = True,
    ):
        self.name = name
        self.annotation = annotation
        self.storage_name = f"_mutobj_attr_{name}"
        self.default = default
        self.default_factory = default_factory
        self.init = init

    @property
    def has_default(self) -> bool:
        """是否有默认值"""
        return self.default is not _MISSING or self.default_factory is not None

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        try:
            return getattr(obj, self.storage_name)
        except AttributeError:
            raise AttributeError(
                f"'{type(obj).__name__}' object has no attribute '{self.name}'"
            )

    def __set__(self, obj: Any, value: Any) -> None:
        setattr(obj, self.storage_name, value)

    def __delete__(self, obj: Any) -> None:
        try:
            delattr(obj, self.storage_name)
        except AttributeError:
            raise AttributeError(
                f"'{type(obj).__name__}' object has no attribute '{self.name}'"
            )


class Property:
    """Property 描述符，支持声明与实现分离"""

    def __init__(self, name: str, owner_cls: type):
        self.name = name
        self.owner_cls = owner_cls
        self._fget: Callable[..., Any] | None = None
        self._fset: Callable[..., Any] | None = None

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        if self._fget is None:
            raise NotImplementedError(
                f"Property '{self.name}' getter is not implemented. "
                f"Use @mutobj.impl({self.owner_cls.__name__}.{self.name}.getter) to provide implementation."
            )
        return self._fget(obj)

    def __set__(self, obj: Any, value: Any) -> None:
        if self._fset is None:
            raise AttributeError(
                f"Property '{self.name}' is read-only or setter is not implemented. "
                f"Use @mutobj.impl({self.owner_cls.__name__}.{self.name}.setter) to provide implementation."
            )
        self._fset(obj, value)

    @property
    def getter(self) -> "_PropertyGetterPlaceholder":
        """返回 getter 占位符，用于 @mutobj.impl(Cls.prop.getter) 语法"""
        return _PropertyGetterPlaceholder(self)

    @property
    def setter(self) -> "_PropertySetterPlaceholder":
        """返回 setter 占位符，用于 @mutobj.impl(Cls.prop.setter) 语法"""
        return _PropertySetterPlaceholder(self)


class _PropertyGetterPlaceholder:
    """Property getter 占位符"""

    def __init__(self, prop: Property):
        self._prop = prop


class _PropertySetterPlaceholder:
    """Property setter 占位符"""

    def __init__(self, prop: Property):
        self._prop = prop


def _update_class_inplace(existing: type, new_cls: type) -> None:
    """Update an existing class in-place with attributes from a new definition.

    Transplants user-defined attributes from new_cls onto existing,
    removes attributes that were deleted in the new definition,
    and fixes mutobj internal references.
    """
    _SKIP = frozenset({
        "__dict__", "__weakref__", "__class__", "__mro__",
        "__subclasses__", "__bases__", "__name__", "__qualname__",
        "__module__",
    })

    old_attrs = set(existing.__dict__.keys())
    new_attrs = set(new_cls.__dict__.keys())

    # Delete attributes removed in new definition
    for attr in old_attrs - new_attrs - _SKIP:
        try:
            delattr(existing, attr)
        except (AttributeError, TypeError):
            pass

    # Set/update attributes from new definition
    for attr in new_attrs - _SKIP:
        val = new_cls.__dict__[attr]
        try:
            setattr(existing, attr, val)
        except (AttributeError, TypeError):
            pass

        # Fix __mutobj_class__ references on stubs/impls
        if callable(val) and hasattr(val, "__mutobj_class__"):
            val.__mutobj_class__ = existing
        # Handle classmethod/staticmethod wrappers
        if isinstance(val, (classmethod, staticmethod)):
            inner: Callable[..., Any] = val.__func__  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            if hasattr(inner, "__mutobj_class__"):
                inner.__mutobj_class__ = existing
        # Fix Property.owner_cls
        if isinstance(val, Property):
            val.owner_cls = existing

    # Update annotations
    if "__annotations__" in new_cls.__dict__:
        existing.__annotations__ = dict(new_cls.__dict__["__annotations__"])


def _migrate_registries(existing: type, new_cls: type) -> None:
    """Move mutobj registry entries from new_cls to existing.

    合并 _impl_chain：将新默认实现替换到已有链中，保留外部 @impl 条目。
    """
    # 合并 _impl_chain
    for key in list(_impl_chain):
        cls, impl_key = key
        if cls is not new_cls:
            continue

        new_chain = _impl_chain.pop(key)
        existing_key = (existing, impl_key)
        existing_chain = _impl_chain.get(existing_key, [])

        # 从新链中提取新的默认实现
        new_default = next(
            ((f, m, s) for f, m, s in new_chain if m == "__default__"), None
        )

        if existing_chain:
            # 替换已有链中的默认实现条目
            for i, (_f, m, _s) in enumerate(existing_chain):
                if m == "__default__":
                    if new_default is not None:
                        existing_chain[i] = new_default
                    break
        else:
            # 无已有链，直接使用新链
            existing_chain = new_chain

        _impl_chain[existing_key] = existing_chain

        # 重新应用链顶实现到类上
        if existing_chain:
            _apply_impl(existing, impl_key, existing_chain[-1][0])

    # 迁移 _module_first_seq 条目
    keys_to_migrate = [k for k in _module_first_seq if k[0] is new_cls]
    for k in keys_to_migrate:
        _module_first_seq[(existing, k[1], k[2])] = _module_first_seq.pop(k)

    # Attribute registry: replace (new definition is authoritative)
    if new_cls in _attribute_registry:
        _attribute_registry[existing] = _attribute_registry.pop(new_cls)

    # Property registry: replace, fixing owner_cls references
    if new_cls in _property_registry:
        props = _property_registry.pop(new_cls)
        for prop in props.values():
            prop.owner_cls = existing
        _property_registry[existing] = props


class DeclarationMeta(type):
    """mutobj.Declaration 的元类，处理声明解析和方法注册"""

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any]
    ) -> DeclarationMeta:
        # 获取 reload 用的 key
        module = namespace.get("__module__", "")
        qualname = namespace.get("__qualname__", name)
        key = (module, qualname)

        # 查找已存在的类（reload 场景）
        existing = _class_registry.get(key)

        # 识别声明的方法
        declared_methods: set[str] = set()
        declared_properties: set[str] = set()
        declared_classmethods: set[str] = set()
        declared_staticmethods: set[str] = set()

        # 创建类
        cls = super().__new__(mcs, name, bases, namespace)

        # Declaration 基类本身：只把白名单中的"用户钩子"登记为已声明方法,
        # __init__ / __new__ 等框架基础设施不进 _DECLARED_METHODS,避免被自动委托替换
        if name == "Declaration" and not bases:
            declared = set()
            for hook_name in _DECLARATION_USER_HOOKS:
                hook = namespace.get(hook_name)
                if callable(hook):
                    hook.__mutobj_class__ = cls
                    _impl_chain.setdefault((cls, hook_name), []).append(
                        (hook, "__default__", 0)
                    )
                    declared.add(hook_name)
            setattr(cls, _DECLARED_METHODS, declared)
            return cls

        # 获取类型注解
        annotations = getattr(cls, "__annotations__", {})

        # 处理属性声明
        attr_registry: dict[str, Any] = {}
        for attr_name, attr_type in annotations.items():
            value = namespace.get(attr_name)

            if isinstance(value, Field):
                # field() 声明
                descriptor = AttributeDescriptor(
                    attr_name, attr_type,
                    default=value.default,
                    default_factory=value.default_factory,
                    init=value.init,
                )
            elif attr_name in namespace and not isinstance(value, AttributeDescriptor):
                if callable(value) or isinstance(value, property):
                    continue
                # 检测可变类型直接赋值
                if isinstance(value, _MUTABLE_TYPES):
                    type_name = type(value).__name__  # pyright: ignore[reportUnknownArgumentType]
                    raise TypeError(
                        f"Declaration '{name}' attribute '{attr_name}' uses mutable default "
                        f"value {type_name}. "
                        f"Use field(default_factory={type_name}) instead."
                    )
                # 不可变默认值
                descriptor = AttributeDescriptor(attr_name, attr_type, default=value)
            elif not hasattr(cls, attr_name) or not isinstance(getattr(cls, attr_name), AttributeDescriptor):
                # 无默认值
                descriptor = AttributeDescriptor(attr_name, attr_type)
            else:
                attr_registry[attr_name] = attr_type
                continue

            setattr(cls, attr_name, descriptor)
            attr_registry[attr_name] = attr_type

        # 处理无注解的属性覆盖：子类用 attr = value 覆盖父类声明属性
        own_annotations = namespace.get("__annotations__", {})
        for attr_name, value in namespace.items():
            if attr_name in own_annotations:
                continue  # 已经在上面的注解属性处理中处理过
            if attr_name.startswith("_"):
                continue
            if callable(value) or isinstance(value, (property, classmethod, staticmethod)):
                continue
            if isinstance(value, AttributeDescriptor):
                continue
            # 查找父类 MRO 中的 AttributeDescriptor
            parent_desc: AttributeDescriptor | None = None
            for base in cls.__mro__[1:]:
                base_val = base.__dict__.get(attr_name)
                if isinstance(base_val, AttributeDescriptor):
                    parent_desc = base_val
                    break
            if parent_desc is None:
                continue
            # 子类意图覆盖父类声明属性
            if isinstance(value, Field):
                descriptor = AttributeDescriptor(
                    attr_name, parent_desc.annotation,
                    default=value.default,
                    default_factory=value.default_factory,
                    init=value.init,
                )
            elif isinstance(value, _MUTABLE_TYPES):
                type_name = type(value).__name__  # pyright: ignore[reportUnknownArgumentType]
                raise TypeError(
                    f"Declaration '{name}' attribute '{attr_name}' uses mutable default "
                    f"value {type_name}. "
                    f"Use field(default_factory={type_name}) instead."
                )
            else:
                descriptor = AttributeDescriptor(attr_name, parent_desc.annotation, default=value)
            setattr(cls, attr_name, descriptor)
            attr_registry[attr_name] = parent_desc.annotation

        _attribute_registry[cls] = attr_registry

        # 处理 property 声明（所有 @property 转为 mutobj.Property，保存原始函数为默认实现）
        prop_registry: dict[str, Property] = {}
        for prop_name, prop_value in namespace.items():
            if prop_name in _MUTOBJ_RESERVED_DUNDERS:
                continue
            if isinstance(prop_value, property):
                declared_properties.add(prop_name)
                mutobj_prop = Property(prop_name, cls)
                setattr(cls, prop_name, mutobj_prop)
                prop_registry[prop_name] = mutobj_prop
                # 保存原始 getter 作为默认实现
                if prop_value.fget is not None:
                    _impl_chain.setdefault((cls, f"{prop_name}.getter"), []).append(
                        (prop_value.fget, "__default__", 0)
                    )
                    mutobj_prop._fget = prop_value.fget  # pyright: ignore[reportPrivateUsage]
                # 保存原始 setter 作为默认实现
                if prop_value.fset is not None:
                    _impl_chain.setdefault((cls, f"{prop_name}.setter"), []).append(
                        (prop_value.fset, "__default__", 0)
                    )
                    mutobj_prop._fset = prop_value.fset  # pyright: ignore[reportPrivateUsage]

        _property_registry[cls] = prop_registry
        setattr(cls, _DECLARED_PROPERTIES, declared_properties)

        # 处理 classmethod 声明（保存原始函数为默认实现）
        for method_name, method_value in namespace.items():
            if method_name in _MUTOBJ_RESERVED_DUNDERS:
                continue
            if isinstance(method_value, classmethod):
                func: Callable[..., Any] = method_value.__func__  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                declared_classmethods.add(method_name)
                _impl_chain.setdefault((cls, method_name), []).append(
                    (func, "__default__", 0)
                )
                func.__mutobj_class__ = cls

        setattr(cls, _DECLARED_CLASSMETHODS, declared_classmethods)

        # 处理 staticmethod 声明（保存原始函数为默认实现）
        for method_name, method_value in namespace.items():
            if method_name in _MUTOBJ_RESERVED_DUNDERS:
                continue
            if isinstance(method_value, staticmethod):
                func: Callable[..., Any] = method_value.__func__  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                declared_staticmethods.add(method_name)
                _impl_chain.setdefault((cls, method_name), []).append(
                    (func, "__default__", 0)
                )
                func.__mutobj_class__ = cls

        setattr(cls, _DECLARED_STATICMETHODS, declared_staticmethods)

        # 处理普通方法声明（保存原始函数为默认实现，不替换为 stub）
        for method_name, method_value in namespace.items():
            if method_name in _MUTOBJ_RESERVED_DUNDERS:
                continue
            if callable(method_value) and not isinstance(method_value, (classmethod, staticmethod, property)):
                declared_methods.add(method_name)
                _impl_chain.setdefault((cls, method_name), []).append(
                    (method_value, "__default__", 0)
                )
                method_value.__mutobj_class__ = cls

        setattr(cls, _DECLARED_METHODS, declared_methods)

        # 子类继承声明方法时，自动创建独立链条
        # 解决多子类继承同一桩方法后 @impl 冲突问题
        for base in cls.__mro__[1:]:
            if base is cls or base is object:  # pyright: ignore[reportUnnecessaryComparison]
                continue

            # 继承普通方法
            for method_name in getattr(base, _DECLARED_METHODS, set[str]()):
                if method_name in declared_methods:
                    continue  # 当前类已重新定义
                if (cls, method_name) in _impl_chain:
                    continue  # 已有链条
                # 创建委托函数：late-bind 查找基类当前实现
                def _make_delegate(b: type, mn: str) -> Callable[..., Any]:
                    def delegate(self: Any, *args: Any, **kwargs: Any) -> Any:
                        return getattr(b, mn)(self, *args, **kwargs)
                    delegate.__name__ = mn
                    delegate.__qualname__ = f"{cls.__name__}.{mn}"
                    delegate.__mutobj_class__ = cls
                    return delegate
                delegate = _make_delegate(base, method_name)
                _impl_chain[(cls, method_name)] = [
                    (delegate, "__default__", 0)
                ]
                setattr(cls, method_name, delegate)
                declared_methods.add(method_name)

            # 继承 classmethod
            for method_name in getattr(base, _DECLARED_CLASSMETHODS, set[str]()):
                if method_name in declared_classmethods:
                    continue
                if (cls, method_name) in _impl_chain:
                    continue
                def _make_cm_delegate(b: type, mn: str) -> Callable[..., Any]:
                    def delegate(cls_arg: type, *args: Any, **kwargs: Any) -> Any:
                        # 获取基类的底层函数，用子类的 cls 调用
                        base_cm = b.__dict__.get(mn)
                        if base_cm is not None:
                            func = base_cm.__func__ if hasattr(base_cm, '__func__') else base_cm
                            return func(cls_arg, *args, **kwargs)
                        return getattr(b, mn)(*args, **kwargs)
                    delegate.__name__ = mn
                    delegate.__qualname__ = f"{cls.__name__}.{mn}"
                    delegate.__mutobj_class__ = cls
                    delegate.__mutobj_is_classmethod__ = True
                    return delegate
                delegate = _make_cm_delegate(base, method_name)
                _impl_chain[(cls, method_name)] = [
                    (delegate, "__default__", 0)
                ]
                setattr(cls, method_name, classmethod(delegate))
                declared_classmethods.add(method_name)

            # 继承 staticmethod
            for method_name in getattr(base, _DECLARED_STATICMETHODS, set[str]()):
                if method_name in declared_staticmethods:
                    continue
                if (cls, method_name) in _impl_chain:
                    continue
                def _make_sm_delegate(b: type, mn: str) -> Callable[..., Any]:
                    def delegate(*args: Any, **kwargs: Any) -> Any:
                        return getattr(b, mn)(*args, **kwargs)
                    delegate.__name__ = mn
                    delegate.__qualname__ = f"{cls.__name__}.{mn}"
                    delegate.__mutobj_class__ = cls
                    delegate.__mutobj_is_staticmethod__ = True
                    return delegate
                delegate = _make_sm_delegate(base, method_name)
                _impl_chain[(cls, method_name)] = [
                    (delegate, "__default__", 0)
                ]
                setattr(cls, method_name, staticmethod(delegate))
                declared_staticmethods.add(method_name)

        # 更新声明集合（可能因继承扩展了）
        setattr(cls, _DECLARED_METHODS, declared_methods)
        setattr(cls, _DECLARED_CLASSMETHODS, declared_classmethods)
        setattr(cls, _DECLARED_STATICMETHODS, declared_staticmethods)

        # Reload: 如果已存在同 (module, qualname) 的类，就地更新
        if existing is not None and existing is not cls:  # pyright: ignore[reportUnnecessaryComparison]
            _update_class_inplace(existing, cls)
            _migrate_registries(existing, cls)
            global _registry_generation
            _registry_generation += 1
            return existing

        # 首次定义：注册到 _class_registry
        _class_registry[key] = cls
        _registry_generation += 1
        return cls

    def __call__(cls: type[T], *args: Any, **kwargs: Any) -> T:  # type: ignore[misc]
        """构造流程: __new__ → __init__ → __post_init__。

        __post_init__ 由元类强制调用,不依赖 __init__ 调 super(),
        让用户在 @impl(Cls.__init__) 自定义构造时无需关心 hook 触发。
        """
        obj = cls.__new__(cls, *args, **kwargs)
        if isinstance(obj, cls):
            cls.__init__(obj, *args, **kwargs)
            obj.__post_init__()  # type: ignore[attr-defined]
        return obj

    def __setattr__(cls, name: str, value: Any) -> None:
        if isinstance(value, AttributeDescriptor):
            super().__setattr__(name, value)
            return

        desc: AttributeDescriptor | None = None
        from_base = False
        own = cls.__dict__.get(name)
        if isinstance(own, AttributeDescriptor):
            desc = own
        else:
            for base in cls.__mro__[1:]:
                base_val = base.__dict__.get(name)
                if isinstance(base_val, AttributeDescriptor):
                    desc = base_val
                    from_base = True
                    break

        if desc is None:
            super().__setattr__(name, value)
            return

        if isinstance(value, _MUTABLE_TYPES):
            type_name = type(value).__name__  # pyright: ignore[reportUnknownArgumentType]
            raise TypeError(
                f"Declaration '{cls.__name__}' attribute '{name}' uses mutable default "
                f"value {type_name}. "
                f"Use field(default_factory={type_name}) instead."
            )
        if isinstance(value, Field):
            new_desc = AttributeDescriptor(
                name, desc.annotation,
                default=value.default,
                default_factory=value.default_factory,
                init=value.init,
            )
        else:
            new_desc = AttributeDescriptor(name, desc.annotation, default=value)
        super().__setattr__(name, new_desc)

        if from_base and cls in _attribute_registry and name not in _attribute_registry[cls]:  # pyright: ignore[reportUnnecessaryContains]
            _attribute_registry[cls][name] = desc.annotation
            _ordered_fields_cache.pop(cls, None)


# 有序字段缓存：{类: [字段名, ...]}（基类在前，与 dataclass 一致）
_ordered_fields_cache: dict[type, list[str]] = {}


def _get_ordered_fields(cls: type) -> list[str]:
    """获取类的有序字段列表（基类在前，子类在后），结果缓存。

    顺序与 dataclass 一致：沿 MRO 从基类到派生类收集，去重保留首次出现。
    MRO [C, A, B, Declaration, object] → 基类顺序 [A, B]，然后 C → 字段 x, y, z。
    """
    cached = _ordered_fields_cache.get(cls)
    if cached is not None:
        return cached
    seen: set[str] = set()
    fields: list[str] = []
    # MRO 中 cls 自身以外的基类，按 MRO 顺序（即 dataclass 的基类顺序）
    for klass in cls.__mro__[1:]:
        if klass in _attribute_registry:
            for attr_name in _attribute_registry[klass]:
                if attr_name not in seen:
                    seen.add(attr_name)
                    fields.append(attr_name)
    # 最后追加 cls 自身的字段
    if cls in _attribute_registry:
        for attr_name in _attribute_registry[cls]:
            if attr_name not in seen:
                seen.add(attr_name)
                fields.append(attr_name)
    _ordered_fields_cache[cls] = fields
    return fields


def _get_attribute_descriptor(cls: type, attr_name: str) -> AttributeDescriptor | None:
    """沿 MRO 查找字段描述符，优先返回最派生类定义。"""
    for klass in cls.__mro__:
        desc = klass.__dict__.get(attr_name)
        if isinstance(desc, AttributeDescriptor):
            return desc
    return None


def _get_init_fields(cls: type) -> list[str]:
    """获取参与构造参数绑定的字段列表。"""
    return [
        attr_name
        for attr_name in _get_ordered_fields(cls)
        if (desc := _get_attribute_descriptor(cls, attr_name)) is not None and desc.init
    ]


class Declaration(metaclass=DeclarationMeta):
    """
    mutobj 声明类的基类

    用于定义接口声明，方法实现通过 @impl 装饰器在其他文件中提供
    """

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        """创建实例并应用声明属性的默认值（不依赖 __init__ 调用链）"""
        obj = super().__new__(cls)
        # 遍历 MRO 中的所有类，为有默认值的属性设置初始值（最派生类优先）
        applied: set[str] = set()
        for klass in cls.__mro__:
            if klass in _attribute_registry:
                for attr_name in _attribute_registry[klass]:
                    if attr_name in applied:
                        continue
                    desc = klass.__dict__.get(attr_name)
                    if isinstance(desc, AttributeDescriptor) and desc.has_default:
                        if desc.default_factory is not None:
                            setattr(obj, attr_name, desc.default_factory())
                        else:
                            setattr(obj, attr_name, desc.default)
                        applied.add(attr_name)
        return obj

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """初始化对象，支持通过位置参数和关键字参数设置属性"""
        # 位置参数映射到字段名（按字段声明顺序，基类在前）
        if args:
            fields = _get_init_fields(type(self))
            if len(args) > len(fields):
                raise TypeError(
                    f"{type(self).__name__}() takes {len(fields)} positional "
                    f"arguments but {len(args)} were given"
                )
            for i, value in enumerate(args):
                name = fields[i]
                if name in kwargs:
                    raise TypeError(
                        f"{type(self).__name__}() got multiple values "
                        f"for argument '{name}'"
                    )
                kwargs[name] = value

        # 应用关键字参数（覆盖 __new__ 中设置的默认值）
        for attr_name, value in kwargs.items():
            desc = _get_attribute_descriptor(type(self), attr_name)
            if isinstance(desc, AttributeDescriptor) and not desc.init:
                raise TypeError(
                    f"{type(self).__name__}() got an unexpected keyword argument '{attr_name}'"
                )
            setattr(self, attr_name, value)

    def __post_init__(self) -> None:
        """构造完成后自动调用，子类可覆盖做派生计算。

        子类既可在类体内重新声明 ``def __post_init__(self) -> None: ...``
        把它作为自身覆盖链入口（推荐，IDE 可见），也可以省略声明、直接
        ``@mutobj.impl(MyClass.__post_init__)`` 注入实现 —— 元类会为每个
        子类生成独立的委托，覆盖不会污染兄弟类或基类。
        """
        ...


# Extension 视图缓存
_extension_cache: weakref.WeakKeyDictionary[Declaration, dict[type, Any]] = weakref.WeakKeyDictionary()

# Extension 注册表：{Declaration 类: [Extension 子类, ...]}
_extension_registry: dict[type, list[type[Extension[Any]]]] = {}


class Extension(Generic[T]):
    """
    Extension 泛型基类

    用于为 Declaration 子类提供扩展功能和私有状态

    示例::

        class UserExt(mutobj.Extension[User]):
            _counter: int = 0

            def _helper(self) -> str:
                return f"Counter: {self._counter}"
    """

    _target_class: type | None = None
    target: Declaration | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # 只检查当前类直接声明的 __orig_bases__（不继承父类的）
        for base in cls.__dict__.get("__orig_bases__", ()):
            origin = getattr(base, "__origin__", None)
            if origin is not None and issubclass(origin, Extension):
                args = getattr(base, "__args__", None)
                if args:
                    cls._target_class = args[0]
                    _extension_registry.setdefault(args[0], []).append(cls)
                return

    @classmethod
    def get_or_create(cls, instance: T) -> Self:
        """
        确保存在并返回 Extension 实例

        不存在则创建，存在则返回缓存实例。

        Args:
            instance: mutobj.Declaration 的实例

        Returns:
            缓存的 Extension 实例
        """
        if instance not in _extension_cache:
            _extension_cache[instance] = {}

        cache = _extension_cache[instance]
        if cls not in cache:
            ext = cls.__new__(cls)
            ext.target = instance
            # 处理 field 描述符：遍历 MRO 收集 Field 实例
            processed: set[str] = set()
            for klass in cls.__mro__:
                for attr_name in getattr(klass, "__annotations__", {}):
                    if attr_name in processed:
                        continue
                    processed.add(attr_name)
                    attr_value = getattr(klass, attr_name, _MISSING)
                    if isinstance(attr_value, Field):
                        if attr_value.default_factory is not None:
                            setattr(ext, attr_name, attr_value.default_factory())
                        elif attr_value.default is not _MISSING:
                            setattr(ext, attr_name, attr_value.default)
            ext.__init__()
            cache[cls] = ext

        return cache[cls]

    @classmethod
    def get(cls, instance: T) -> Self | None:
        """
        查询 Extension 实例，不存在返回 None

        Args:
            instance: mutobj.Declaration 的实例

        Returns:
            已缓存的 Extension 实例，或 None
        """
        cache = _extension_cache.get(instance)
        if cache is not None:
            return cache.get(cls)
        return None

    def __init__(self) -> None:
        pass


def _resolve_impl_key(
    method: Any,
) -> tuple[type, str]:
    """将 method 句柄解析为 (target_cls, impl_key)。

    支持 property getter/setter placeholder、普通方法、classmethod、staticmethod。
    被 @impl 装饰器和 call_super_impl 共用，保证两者对同一 method 的解析一致。

    Raises:
        TypeError: method 不是合法的方法句柄
        ValueError: 无法定位目标类
    """
    # property getter
    if isinstance(method, _PropertyGetterPlaceholder):
        prop = method._prop  # pyright: ignore[reportPrivateUsage]
        return prop.owner_cls, f"{prop.name}.getter"

    # property setter
    if isinstance(method, _PropertySetterPlaceholder):
        prop = method._prop  # pyright: ignore[reportPrivateUsage]
        return prop.owner_cls, f"{prop.name}.setter"

    if not callable(method):
        raise TypeError(f"Expected a callable or property accessor, got {type(method)}")

    method_name = getattr(method, "__name__", "")

    # 优先使用存储的类引用
    target_cls = getattr(method, "__mutobj_class__", None)

    if target_cls is None:
        qualname = getattr(method, "__qualname__", "")
        if "." in qualname:
            class_name = qualname.rsplit(".", 1)[0]
        else:
            raise ValueError(f"Cannot determine class for method {method}")

        candidates = [
            cls for cls in _class_registry.values()
            if cls.__name__ == class_name
        ]
        if len(candidates) > 1:
            paths = [f"{c.__module__}.{c.__qualname__}" for c in candidates]
            raise ValueError(
                f"@impl({method_name!r}): ambiguous target — multiple "
                f"Declaration classes named {class_name!r} are registered: "
                f"{paths}. This usually means the method does not have "
                f"__mutobj_class__ set; if it's a dunder method declared "
                f"by the user, ensure it's defined in the class body "
                f"(mutobj should auto-tag it)."
            )
        elif len(candidates) == 1:
            target_cls = candidates[0]

        if target_cls is None and hasattr(method, "__globals__"):
            target_cls = method.__globals__.get(class_name)

    if target_cls is None:
        raise ValueError(f"Cannot find class for method {method_name}")

    return target_cls, method_name


def call_super_impl(method: Any, *args: Any, **kwargs: Any) -> Any:
    """调用 @impl 链中当前实现的上一级实现。

    必须从 @impl 函数体内调用。框架通过调用栈定位调用方所在模块，
    在 method 对应的覆盖链中找到当前条目，返回执行链中前一条记录的结果。

    Args:
        method: 被覆盖的方法句柄（如 ``JinaSearchImpl.search``、property 的 getter/setter）
        *args, **kwargs: 转发给上一级实现的参数（首参一般是 self/cls）

    Raises:
        NotImplementedError: 当前实现已是链底，无上级可调
        RuntimeError: 调用方不在 method 的 @impl 链中（如从普通函数 / 测试代码调用）

    示例::

        @mutagent.impl(JinaSearchImpl.search)
        async def _jina_search(self, query, max_results=5):
            try:
                return await mutobj.call_super_impl(
                    JinaSearchImpl.search, self, query, max_results
                )
            except RuntimeError as e:
                raise _enrich_error(e) from e
    """
    cls, key = _resolve_impl_key(method)
    caller_module = sys._getframe(1).f_globals.get("__name__", "")
    chain = _impl_chain.get((cls, key), [])
    for i, (_fn, mod, _seq) in enumerate(chain):
        if mod == caller_module:
            # 跳过链底的 __default__ 桩条目（调用它只会抛桌NotImplementedError）
            if i == 0 or chain[i - 1][1] == "__default__":
                raise NotImplementedError(
                    f"No super implementation for {cls.__name__}.{key} "
                    f"below module {mod!r}"
                )
            return chain[i - 1][0](*args, **kwargs)
    raise RuntimeError(
        f"call_super_impl({cls.__name__}.{key}) must be called from within "
        f"an @impl function for that method (caller module: {caller_module!r})"
    )


def impl(
    method: Callable[..., Any] | _PropertyGetterPlaceholder | _PropertySetterPlaceholder,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    方法实现装饰器

    Args:
        method: 要实现的方法（来自 Declaration 子类）

    Returns:
        装饰器函数

    示例::

        @mutobj.impl(User.greet)
        def greet(self: User) -> str:
            return f"Hello, {self.name}"
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        source_module = getattr(func, "__module__", "") or ""

        # 处理 property getter
        if isinstance(method, _PropertyGetterPlaceholder):
            target_cls, impl_key = _resolve_impl_key(method)
            prop = method._prop  # pyright: ignore[reportPrivateUsage]

            became_top = _register_to_chain(
                target_cls, impl_key, func, source_module
            )
            if became_top:
                prop._fget = func  # pyright: ignore[reportPrivateUsage]
            return func

        # 处理 property setter
        if isinstance(method, _PropertySetterPlaceholder):
            target_cls, impl_key = _resolve_impl_key(method)
            prop = method._prop  # pyright: ignore[reportPrivateUsage]

            became_top = _register_to_chain(
                target_cls, impl_key, func, source_module
            )
            if became_top:
                prop._fset = func  # pyright: ignore[reportPrivateUsage]
            return func

        # 普通方法 / classmethod / staticmethod —— 复用 _resolve_impl_key
        target_cls, method_name = _resolve_impl_key(method)

        # 防污染: 除白名单钩子外, 不允许 @impl 直接挂到 Declaration 基类。
        # 触发场景: 子类未声明桩, @impl(MyCls.some_method) 反推到 Declaration —
        # 此时若放行,会替换所有 Declaration 子类的该方法 (典型如 __init__ / __new__)。
        if target_cls is Declaration and method_name not in _DECLARATION_USER_HOOKS:
            raise ValueError(
                f"@impl({method_name!r}): refusing to register on Declaration base "
                f"class. The method was resolved to Declaration because the "
                f"subclass does not declare its own {method_name!r}. Add a stub "
                f"on the subclass first, e.g.\n"
                f"    class MySubclass(mutobj.Declaration):\n"
                f"        def {method_name}(self, ...) -> ...: ...\n"
                f"then re-run @impl(MySubclass.{method_name})."
            )

        # 检查方法是否存在于类上
        if not hasattr(target_cls, method_name):
            raise ValueError(
                f"Method '{method_name}' does not exist in {target_cls.__name__}"
            )

        # 检查 classmethod/staticmethod 类型
        existing = target_cls.__dict__.get(method_name)
        is_classmethod = isinstance(existing, classmethod)
        is_staticmethod = isinstance(existing, staticmethod)

        # 注册到覆盖链
        became_top = _register_to_chain(
            target_cls, method_name, func, source_module
        )

        # 保留类引用，便于后续 override
        func.__mutobj_class__ = target_cls
        func.__name__ = method_name
        func.__qualname__ = f"{target_cls.__name__}.{method_name}"

        # 仅当新条目成为链顶时才更新类方法
        if became_top:
            if is_classmethod:
                setattr(target_cls, method_name, classmethod(func))
            elif is_staticmethod:
                setattr(target_cls, method_name, staticmethod(func))
            else:
                setattr(target_cls, method_name, func)

        return func

    return decorator


def unregister_module_impls(module_name: str) -> int:
    """移除指定模块注册的所有 @impl，恢复覆盖链上一层实现

    Args:
        module_name: 来源模块的 __name__

    Returns:
        被卸载的 impl 数量
    """
    removed = 0

    for key in list(_impl_chain):
        cls, impl_key = key
        chain = _impl_chain[key]
        was_top_module = chain[-1][1] == module_name if chain else False

        # 移除指定模块的所有条目（不删除 __default__，不删除 _module_first_seq）
        before = len(chain)
        chain[:] = [(f, m, s) for f, m, s in chain if m != module_name]
        removed += before - len(chain)

        if not chain:
            # 链为空（无默认实现的异常情况），恢复 stub
            _restore_stub(cls, impl_key)
            del _impl_chain[key]
        elif was_top_module:
            # 活跃实现被卸载，恢复为新链顶
            _apply_impl(cls, impl_key, chain[-1][0])
        # 若卸载的是中间层，活跃实现不变，无需操作

    if removed > 0:
        global _registry_generation
        _registry_generation += 1

    return removed


def register_module_impls(*modules: Any) -> None:
    """加载实现模块（当前为空操作，预留未来统一处理）

    用于在声明文件中显式导入实现模块，防止 IDE 将 import 标记为未使用。

    示例::

        from . import user_impl
        register_module_impls(user_impl)

    Args:
        modules: 实现模块（当前不做任何处理）
    """


def discover_subclasses(base_cls: type) -> list[type]:
    """返回 _class_registry 中 base_cls 的所有已注册子类（不含 base_cls 自身）。

    每次调用重新扫描 registry，结果反映当前注册状态。
    支持运行时新增类（模块加载）和移除类（模块卸载）。

    Args:
        base_cls: 要查找子类的基类，必须是 Declaration 的子类

    Returns:
        base_cls 的所有已注册子类列表（不保证顺序）
    """
    return [
        cls for cls in _class_registry.values()
        if cls is not base_cls and isinstance(cls, type) and issubclass(cls, base_cls)  # pyright: ignore[reportUnnecessaryIsInstance]
    ]


def resolve_class(class_path: str, base_cls: type | None = None) -> type:
    """通过类路径字符串解析 Declaration 子类，未注册时自动 import。

    支持两种格式：
    - 短名：``"AnthropicProvider"``（在已注册类中按 qualname 搜索）
    - 全路径：``"mutbot.copilot.provider.CopilotProvider"``（先搜索，未找到则自动 import）

    Args:
        class_path: 类的短名或全路径（``模块.类名``）
        base_cls: 可选，验证解析结果是否为指定基类的子类

    Returns:
        解析到的 Declaration 子类

    Raises:
        ValueError: 找不到类、类型不匹配、或 import 失败
    """
    # 1. 已注册类中查找（短名、简单类名或全路径均可匹配）
    for (mod, qualname), cls in _class_registry.items():
        if class_path in (qualname, cls.__name__, f"{mod}.{qualname}"):
            if base_cls is not None and not issubclass(cls, base_cls):
                raise ValueError(
                    f"Class {class_path} is not a subclass of {base_cls.__name__}"
                )
            return cls

    # 2. 全路径时，自动 import 模块（DeclarationMeta.__new__ 会自动注册）
    if "." in class_path:
        module_path, class_name = class_path.rsplit(".", 1)
        try:
            importlib.import_module(module_path)
        except ImportError as e:
            raise ValueError(f"Cannot import module for {class_path}: {e}") from e

        key = (module_path, class_name)
        if key in _class_registry:
            cls = _class_registry[key]
            if base_cls is not None and not issubclass(cls, base_cls):
                raise ValueError(
                    f"Class {class_path} is not a subclass of {base_cls.__name__}"
                )
            return cls

    raise ValueError(f"Cannot resolve class: {class_path}")


def get_registry_generation() -> int:
    """返回注册表的当前 generation 号。

    任何类注册/更新、@impl 注册/卸载都会导致 generation 递增。
    调用方可通过比较前后 generation 判断是否需要重新扫描。
    """
    return _registry_generation


def get_declaration_doc(cls: type, method_name: str) -> str | None:
    """获取 Declaration 类中方法的声明 docstring。

    @impl 会覆盖类方法（包括 __doc__），此函数从 _impl_chain 中
    取回声明时的原始 docstring。

    Args:
        cls: Declaration 子类
        method_name: 方法名

    Returns:
        声明的 docstring，如果没有则返回 None
    """
    chain = _impl_chain.get((cls, method_name))
    if not chain:
        return None
    for func, source_module, _seq in chain:
        if source_module == "__default__":
            return getattr(func, "__doc__", None)
    return None


def extension_types(
    decl_class: type[Declaration],
    filter_type: type | None = None,
) -> list[type[Extension[Any]]]:
    """查询 Declaration 类注册了哪些 Extension 类型

    沿 Declaration 的 MRO 收集所有注册的 Extension 类型。

    Args:
        decl_class: Declaration 类（非实例）
        filter_type: 可选，按类型过滤（issubclass 检查）

    Returns:
        注册的 Extension 类型列表
    """
    result: list[type[Extension[Any]]] = []
    seen: set[type] = set()
    for klass in decl_class.__mro__:
        for ext_cls in _extension_registry.get(klass, []):
            if ext_cls not in seen:
                seen.add(ext_cls)
                if filter_type is None or issubclass(ext_cls, filter_type):
                    result.append(ext_cls)
    return result


def extensions(
    instance: Declaration,
    filter_type: type | None = None,
) -> list[Extension[Any]]:
    """枚举实例上已创建的 Extension 实例（不触发创建）

    Args:
        instance: Declaration 实例
        filter_type: 可选，按类型过滤（isinstance 检查）

    Returns:
        已创建的 Extension 实例列表
    """
    cache = _extension_cache.get(instance)
    if cache is None:
        return []
    if filter_type is None:
        return list(cache.values())
    return [ext for ext in cache.values() if isinstance(ext, filter_type)]
