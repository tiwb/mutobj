"""
mutobj 核心模块

包含 Declaration 基类、Extension 泛型基类和 impl 装饰器
"""

from __future__ import annotations

import weakref
from typing import TypeVar, Generic, Callable, Any, get_type_hints, TYPE_CHECKING

__all__ = ["Declaration", "Extension", "impl", "unregister_module_impls", "field"]

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


_MISSING: Any = _MissingSentinel()


class Field:
    """属性默认值描述，由 field() 创建"""

    __slots__ = ("default", "default_factory")

    def __init__(
        self,
        default: Any = _MISSING,
        default_factory: Callable[[], Any] | None = None,
    ) -> None:
        if default is not _MISSING and default_factory is not None:
            raise TypeError("不能同时指定 default 和 default_factory")
        self.default = default
        self.default_factory = default_factory


def field(
    *,
    default: Any = _MISSING,
    default_factory: Callable[[], Any] | None = None,
) -> Any:
    """声明属性的默认值

    Args:
        default: 不可变默认值
        default_factory: 可变默认值的工厂函数，每次实例化时调用

    Returns:
        Field 哨兵对象（DeclarationMeta 会识别并提取）
    """
    return Field(default=default, default_factory=default_factory)


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


def _make_stub_classmethod(name: str, cls: type) -> classmethod:
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


def _make_stub_staticmethod(name: str, cls: type) -> staticmethod:
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
            prop._fget = func
    elif impl_key.endswith(".setter"):
        prop_name = impl_key[:-7]
        prop = _property_registry.get(cls, {}).get(prop_name)
        if prop is not None:
            prop._fset = func
    else:
        declared_cm = getattr(cls, _DECLARED_CLASSMETHODS, set())
        declared_sm = getattr(cls, _DECLARED_STATICMETHODS, set())
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
            prop._fget = None
    elif impl_key.endswith(".setter"):
        prop_name = impl_key[:-7]
        prop = _property_registry.get(cls, {}).get(prop_name)
        if prop is not None:
            prop._fset = None
    else:
        declared_cm = getattr(cls, _DECLARED_CLASSMETHODS, set())
        declared_sm = getattr(cls, _DECLARED_STATICMETHODS, set())
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
    return chain[-1][1] == source_module


class AttributeDescriptor:
    """属性描述符，用于拦截属性访问"""

    def __init__(
        self,
        name: str,
        annotation: Any,
        default: Any = _MISSING,
        default_factory: Callable[[], Any] | None = None,
    ):
        self.name = name
        self.annotation = annotation
        self.storage_name = f"_mutobj_attr_{name}"
        self.default = default
        self.default_factory = default_factory

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
            inner = val.__func__
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
            for i, (f, m, s) in enumerate(existing_chain):
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

        # 跳过 Declaration 基类本身
        if name == "Declaration" and not bases:
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
                )
            elif attr_name in namespace and not isinstance(value, AttributeDescriptor):
                if callable(value) or isinstance(value, property):
                    continue
                # 检测可变类型直接赋值
                if isinstance(value, _MUTABLE_TYPES):
                    raise TypeError(
                        f"Declaration '{name}' 的属性 '{attr_name}' 使用了可变默认值 "
                        f"{type(value).__name__}。"
                        f"请使用 field(default_factory={type(value).__name__}) 代替。"
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

        _attribute_registry[cls] = attr_registry

        # 处理 property 声明（所有 @property 转为 mutobj.Property，保存原始函数为默认实现）
        prop_registry: dict[str, Property] = {}
        for prop_name, prop_value in namespace.items():
            if prop_name.startswith("_"):
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
                    mutobj_prop._fget = prop_value.fget
                # 保存原始 setter 作为默认实现
                if prop_value.fset is not None:
                    _impl_chain.setdefault((cls, f"{prop_name}.setter"), []).append(
                        (prop_value.fset, "__default__", 0)
                    )
                    mutobj_prop._fset = prop_value.fset

        _property_registry[cls] = prop_registry
        setattr(cls, _DECLARED_PROPERTIES, declared_properties)

        # 处理 classmethod 声明（保存原始函数为默认实现）
        for method_name, method_value in namespace.items():
            if method_name.startswith("_"):
                continue
            if isinstance(method_value, classmethod):
                func = method_value.__func__
                declared_classmethods.add(method_name)
                _impl_chain.setdefault((cls, method_name), []).append(
                    (func, "__default__", 0)
                )
                func.__mutobj_class__ = cls

        setattr(cls, _DECLARED_CLASSMETHODS, declared_classmethods)

        # 处理 staticmethod 声明（保存原始函数为默认实现）
        for method_name, method_value in namespace.items():
            if method_name.startswith("_"):
                continue
            if isinstance(method_value, staticmethod):
                func = method_value.__func__
                declared_staticmethods.add(method_name)
                _impl_chain.setdefault((cls, method_name), []).append(
                    (func, "__default__", 0)
                )
                func.__mutobj_class__ = cls

        setattr(cls, _DECLARED_STATICMETHODS, declared_staticmethods)

        # 处理普通方法声明（保存原始函数为默认实现，不替换为 stub）
        for method_name, method_value in namespace.items():
            if method_name.startswith("_"):
                continue
            if callable(method_value) and not isinstance(method_value, (classmethod, staticmethod, property)):
                declared_methods.add(method_name)
                _impl_chain.setdefault((cls, method_name), []).append(
                    (method_value, "__default__", 0)
                )
                method_value.__mutobj_class__ = cls

        setattr(cls, _DECLARED_METHODS, declared_methods)

        # Reload: 如果已存在同 (module, qualname) 的类，就地更新
        if existing is not None and existing is not cls:
            _update_class_inplace(existing, cls)
            _migrate_registries(existing, cls)
            return existing

        # 首次定义：注册到 _class_registry
        _class_registry[key] = cls
        return cls


class Declaration(metaclass=DeclarationMeta):
    """
    mutobj 声明类的基类

    用于定义接口声明，方法实现通过 @impl 装饰器在其他文件中提供
    """

    def __init__(self, **kwargs: Any) -> None:
        """初始化对象，支持通过关键字参数设置属性，自动应用默认值"""
        # 遍历 MRO 中的所有类，收集所有属性（最派生类优先）
        applied: set[str] = set()
        for klass in type(self).__mro__:
            if klass in _attribute_registry:
                for attr_name in _attribute_registry[klass]:
                    if attr_name in applied:
                        continue
                    if attr_name in kwargs:
                        setattr(self, attr_name, kwargs[attr_name])
                        applied.add(attr_name)
                    else:
                        # 查找描述符上的默认值
                        desc = klass.__dict__.get(attr_name)
                        if isinstance(desc, AttributeDescriptor) and desc.has_default:
                            if desc.default_factory is not None:
                                setattr(self, attr_name, desc.default_factory())
                            else:
                                setattr(self, attr_name, desc.default)
                            applied.add(attr_name)


# Extension 视图缓存
_extension_cache: weakref.WeakKeyDictionary[Declaration, dict[type, Any]] = weakref.WeakKeyDictionary()


class ExtensionMeta(type):
    """Extension 的元类"""

    _target_class: type | None = None

    def __getitem__(cls, target: type[T]) -> type[Extension[T]]:
        """支持 Extension[User] 语法"""
        # 创建绑定到目标类的 Extension 子类
        new_cls = type(
            f"{cls.__name__}[{target.__name__}]",
            (cls,),
            {"_target_class": target}
        )
        return new_cls


class Extension(Generic[T], metaclass=ExtensionMeta):
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
    _instance: Declaration | None = None

    def __init__(self) -> None:
        self._instance = None

    @classmethod
    def of(cls, instance: T) -> Extension[T]:
        """
        获取实例的 Extension 视图

        Args:
            instance: mutobj.Declaration 的实例

        Returns:
            缓存的 Extension 视图对象
        """
        if instance not in _extension_cache:
            _extension_cache[instance] = {}

        cache = _extension_cache[instance]
        if cls not in cache:
            ext = cls()
            ext._instance = instance
            # 调用初始化钩子
            if hasattr(ext, "__extension_init__"):
                ext.__extension_init__()
            cache[cls] = ext

        return cache[cls]

    def __getattr__(self, name: str) -> Any:
        """代理访问目标实例的属性"""
        if name.startswith("_"):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        if self._instance is not None:
            return getattr(self._instance, name)
        raise AttributeError(f"Extension not bound to an instance")

    def __setattr__(self, name: str, value: Any) -> None:
        """设置属性"""
        if name.startswith("_") or name in ("_instance", "_target_class"):
            super().__setattr__(name, value)
        elif self._instance is not None:
            setattr(self._instance, name, value)
        else:
            super().__setattr__(name, value)


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
            prop = method._prop
            target_cls = prop.owner_cls
            impl_key = f"{prop.name}.getter"

            became_top = _register_to_chain(
                target_cls, impl_key, func, source_module
            )
            if became_top:
                prop._fget = func
            return func

        # 处理 property setter
        if isinstance(method, _PropertySetterPlaceholder):
            prop = method._prop
            target_cls = prop.owner_cls
            impl_key = f"{prop.name}.setter"

            became_top = _register_to_chain(
                target_cls, impl_key, func, source_module
            )
            if became_top:
                prop._fset = func
            return func

        # 获取目标类和方法名
        if not callable(method):
            raise TypeError(f"Expected a callable, got {type(method)}")

        method_name = getattr(method, "__name__", "")

        # 优先使用存储的类引用
        target_cls = getattr(method, "__mutobj_class__", None)

        if target_cls is None:
            # 从方法获取所属类
            qualname = getattr(method, "__qualname__", "")
            if "." in qualname:
                class_name = qualname.rsplit(".", 1)[0]
            else:
                raise ValueError(f"Cannot determine class for method {method}")

            # 查找目标类（使用 _class_registry）
            for cls in _class_registry.values():
                if cls.__name__ == class_name:
                    target_cls = cls
                    break

            if target_cls is None:
                # 尝试从方法的 __globals__ 中查找
                if hasattr(method, "__globals__"):
                    target_cls = method.__globals__.get(class_name)

        if target_cls is None:
            raise ValueError(f"Cannot find class for method {method_name}")

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
