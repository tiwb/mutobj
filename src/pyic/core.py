"""
pyic 核心模块

包含 Object 基类、Extension 泛型基类和 impl 装饰器
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import weakref
from typing import TypeVar, Generic, Callable, Any, get_type_hints, TYPE_CHECKING

__all__ = ["Object", "Extension", "impl"]

# 类型变量
T = TypeVar("T", bound="Object")

# 全局方法注册表: {类: {方法名: 实现函数}}
_method_registry: dict[type, dict[str, Callable[..., Any]]] = {}

# 全局属性注册表: {类: {属性名: 类型注解}}
_attribute_registry: dict[type, dict[str, Any]] = {}

# 全局 property 注册表: {类: {property名: PyicProperty}}
_property_registry: dict[type, dict[str, "PyicProperty"]] = {}

# 声明方法标记（用于标识未实现的方法）
_DECLARED_METHODS: str = "__pyic_declared_methods__"

# 声明 property 标记
_DECLARED_PROPERTIES: str = "__pyic_declared_properties__"

# 声明 classmethod 标记
_DECLARED_CLASSMETHODS: str = "__pyic_declared_classmethods__"

# 声明 staticmethod 标记
_DECLARED_STATICMETHODS: str = "__pyic_declared_staticmethods__"


def _is_stub_method(func: Callable[..., Any]) -> bool:
    """检查方法是否为桩方法（只有 docstring + ... 或 pass）"""
    try:
        source = inspect.getsource(func)
        # 移除缩进
        source = textwrap.dedent(source)
        # 解析AST
        tree = ast.parse(source)
        if not tree.body:
            return False

        # 获取函数定义
        func_def = tree.body[0]
        if not isinstance(func_def, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return False

        body = func_def.body
        if not body:
            return True

        # 跳过 docstring
        start_idx = 0
        if (isinstance(body[0], ast.Expr) and
            isinstance(body[0].value, ast.Constant) and
            isinstance(body[0].value.value, str)):
            start_idx = 1

        remaining = body[start_idx:]

        # 检查剩余语句
        if not remaining:
            return True

        if len(remaining) == 1:
            stmt = remaining[0]
            # ... (Ellipsis)
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                if stmt.value.value is ...:
                    return True
            # pass
            if isinstance(stmt, ast.Pass):
                return True

        return False
    except (OSError, TypeError):
        # 无法获取源码（内置方法等）
        return False


def _make_stub_method(name: str, cls: type) -> Callable[..., Any]:
    """创建一个桩方法，调用时抛出 NotImplementedError"""
    def stub(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            f"Method '{name}' is declared in {cls.__name__} but not implemented. "
            f"Use @pyic.impl({cls.__name__}.{name}) to provide implementation."
        )
    stub.__name__ = name
    stub.__qualname__ = f"{cls.__name__}.{name}"
    # 存储对类的引用，便于 impl 装饰器查找
    stub.__pyic_class__ = cls
    return stub


def _make_stub_classmethod(name: str, cls: type) -> classmethod:
    """创建一个 classmethod 桩方法"""
    def stub(cls_arg: type, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            f"Classmethod '{name}' is declared in {cls.__name__} but not implemented. "
            f"Use @pyic.impl({cls.__name__}.{name}) to provide implementation."
        )
    stub.__name__ = name
    stub.__qualname__ = f"{cls.__name__}.{name}"
    stub.__pyic_class__ = cls
    stub.__pyic_is_classmethod__ = True
    return classmethod(stub)


def _make_stub_staticmethod(name: str, cls: type) -> staticmethod:
    """创建一个 staticmethod 桩方法"""
    def stub(*args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            f"Staticmethod '{name}' is declared in {cls.__name__} but not implemented. "
            f"Use @pyic.impl({cls.__name__}.{name}) to provide implementation."
        )
    stub.__name__ = name
    stub.__qualname__ = f"{cls.__name__}.{name}"
    stub.__pyic_class__ = cls
    stub.__pyic_is_staticmethod__ = True
    return staticmethod(stub)


class PyicAttributeDescriptor:
    """pyic 属性描述符，用于拦截属性访问"""

    def __init__(self, name: str, annotation: Any):
        self.name = name
        self.annotation = annotation
        self.storage_name = f"_pyic_attr_{name}"

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


class PyicProperty:
    """pyic property 描述符，支持声明与实现分离"""

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
                f"Use @pyic.impl({self.owner_cls.__name__}.{self.name}.getter) to provide implementation."
            )
        return self._fget(obj)

    def __set__(self, obj: Any, value: Any) -> None:
        if self._fset is None:
            raise AttributeError(
                f"Property '{self.name}' is read-only or setter is not implemented. "
                f"Use @pyic.impl({self.owner_cls.__name__}.{self.name}.setter) to provide implementation."
            )
        self._fset(obj, value)

    @property
    def getter(self) -> "_PyicPropertyGetterPlaceholder":
        """返回 getter 占位符，用于 @pyic.impl(Cls.prop.getter) 语法"""
        return _PyicPropertyGetterPlaceholder(self)

    @property
    def setter(self) -> "_PyicPropertySetterPlaceholder":
        """返回 setter 占位符，用于 @pyic.impl(Cls.prop.setter) 语法"""
        return _PyicPropertySetterPlaceholder(self)


class _PyicPropertyGetterPlaceholder:
    """Property getter 占位符"""

    def __init__(self, prop: PyicProperty):
        self._prop = prop


class _PyicPropertySetterPlaceholder:
    """Property setter 占位符"""

    def __init__(self, prop: PyicProperty):
        self._prop = prop


class ObjectMeta(type):
    """pyic.Object 的元类，处理声明解析和方法注册"""

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any]
    ) -> ObjectMeta:
        # 识别声明的方法（桩方法）
        declared_methods: set[str] = set()
        # 识别声明的 property
        declared_properties: set[str] = set()
        # 识别声明的 classmethod
        declared_classmethods: set[str] = set()
        # 识别声明的 staticmethod
        declared_staticmethods: set[str] = set()

        # 创建类
        cls = super().__new__(mcs, name, bases, namespace)

        # 跳过 Object 基类本身
        if name == "Object" and not bases:
            return cls

        # 获取类型注解（Python 3.14+ 使用 PEP 649 延迟注解）
        annotations = getattr(cls, "__annotations__", {})

        # 处理属性声明
        attr_registry: dict[str, Any] = {}
        for attr_name, attr_type in annotations.items():
            # 跳过已经有值的类属性（如 classmethod 等）
            if attr_name in namespace and not isinstance(namespace[attr_name], PyicAttributeDescriptor):
                # 检查是否为方法或 property
                if callable(namespace[attr_name]) or isinstance(namespace[attr_name], property):
                    continue

            # 为属性创建描述符
            if not hasattr(cls, attr_name) or not isinstance(getattr(cls, attr_name), PyicAttributeDescriptor):
                descriptor = PyicAttributeDescriptor(attr_name, attr_type)
                setattr(cls, attr_name, descriptor)
            attr_registry[attr_name] = attr_type

        _attribute_registry[cls] = attr_registry

        # 处理 property 声明
        prop_registry: dict[str, PyicProperty] = {}
        for prop_name, prop_value in namespace.items():
            if prop_name.startswith("_"):
                continue
            if isinstance(prop_value, property):
                # 检查是否为桩 property（getter 是桩方法）
                if prop_value.fget is not None and _is_stub_method(prop_value.fget):
                    declared_properties.add(prop_name)
                    # 创建 PyicProperty 替换原 property
                    pyic_prop = PyicProperty(prop_name, cls)
                    setattr(cls, prop_name, pyic_prop)
                    prop_registry[prop_name] = pyic_prop

        _property_registry[cls] = prop_registry
        setattr(cls, _DECLARED_PROPERTIES, declared_properties)

        # 处理 classmethod 声明
        for method_name, method_value in namespace.items():
            if method_name.startswith("_"):
                continue
            if isinstance(method_value, classmethod):
                # 获取底层函数
                func = method_value.__func__
                if _is_stub_method(func):
                    declared_classmethods.add(method_name)
                    # 替换为桩 classmethod
                    stub = _make_stub_classmethod(method_name, cls)
                    setattr(cls, method_name, stub)

        setattr(cls, _DECLARED_CLASSMETHODS, declared_classmethods)

        # 处理 staticmethod 声明
        for method_name, method_value in namespace.items():
            if method_name.startswith("_"):
                continue
            if isinstance(method_value, staticmethod):
                # 获取底层函数
                func = method_value.__func__
                if _is_stub_method(func):
                    declared_staticmethods.add(method_name)
                    # 替换为桩 staticmethod
                    stub = _make_stub_staticmethod(method_name, cls)
                    setattr(cls, method_name, stub)

        setattr(cls, _DECLARED_STATICMETHODS, declared_staticmethods)

        # 处理普通方法声明
        for method_name, method_value in namespace.items():
            if method_name.startswith("_"):
                continue
            if callable(method_value) and not isinstance(method_value, (classmethod, staticmethod, property)):
                if _is_stub_method(method_value):
                    declared_methods.add(method_name)
                    # 替换为桩方法
                    stub = _make_stub_method(method_name, cls)
                    setattr(cls, method_name, stub)

        # 存储声明的方法列表
        setattr(cls, _DECLARED_METHODS, declared_methods)

        # 初始化方法注册表
        if cls not in _method_registry:
            _method_registry[cls] = {}

        return cls


class Object(metaclass=ObjectMeta):
    """
    pyic 声明类的基类

    用于定义接口声明，方法实现通过 @impl 装饰器在其他文件中提供
    """

    def __init__(self, **kwargs: Any) -> None:
        """初始化对象，支持通过关键字参数设置属性"""
        # 遍历 MRO 中的所有类，收集所有属性
        for klass in type(self).__mro__:
            if klass in _attribute_registry:
                for attr_name in _attribute_registry[klass]:
                    if attr_name in kwargs:
                        setattr(self, attr_name, kwargs[attr_name])


# Extension 视图缓存
_extension_cache: weakref.WeakKeyDictionary[Object, dict[type, Any]] = weakref.WeakKeyDictionary()


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

    用于为 Object 子类提供扩展功能和私有状态

    示例::

        class UserExt(pyic.Extension[User]):
            _counter: int = 0

            def _helper(self) -> str:
                return f"Counter: {self._counter}"
    """

    _target_class: type | None = None
    _instance: Object | None = None

    def __init__(self) -> None:
        self._instance = None

    @classmethod
    def of(cls, instance: T) -> Extension[T]:
        """
        获取实例的 Extension 视图

        Args:
            instance: pyic.Object 的实例

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
    method: Callable[..., Any] | _PyicPropertyGetterPlaceholder | _PyicPropertySetterPlaceholder,
    *,
    override: bool = False
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    方法实现装饰器

    Args:
        method: 要实现的方法（来自 Object 子类）
        override: 是否允许覆盖已有实现

    Returns:
        装饰器函数

    示例::

        @pyic.impl(User.greet)
        def greet(self: User) -> str:
            return f"Hello, {self.name}"

    Raises:
        ValueError: 如果方法已有实现且 override=False
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        # 处理 property getter
        if isinstance(method, _PyicPropertyGetterPlaceholder):
            prop = method._prop
            if prop._fget is not None and not override:
                raise ValueError(
                    f"Property '{prop.name}' getter already implemented for {prop.owner_cls.__name__}. "
                    f"Use @pyic.impl({prop.owner_cls.__name__}.{prop.name}.getter, override=True) to override."
                )
            prop._fget = func
            return func

        # 处理 property setter
        if isinstance(method, _PyicPropertySetterPlaceholder):
            prop = method._prop
            if prop._fset is not None and not override:
                raise ValueError(
                    f"Property '{prop.name}' setter already implemented for {prop.owner_cls.__name__}. "
                    f"Use @pyic.impl({prop.owner_cls.__name__}.{prop.name}.setter, override=True) to override."
                )
            prop._fset = func
            return func

        # 获取目标类和方法名
        if not callable(method):
            raise TypeError(f"Expected a callable, got {type(method)}")

        method_name = getattr(method, "__name__", "")

        # 优先使用存储的类引用
        target_cls = getattr(method, "__pyic_class__", None)

        if target_cls is None:
            # 从方法获取所属类
            qualname = getattr(method, "__qualname__", "")
            if "." in qualname:
                class_name = qualname.rsplit(".", 1)[0]
            else:
                raise ValueError(f"Cannot determine class for method {method}")

            # 查找目标类
            for cls in _method_registry:
                if cls.__name__ == class_name:
                    target_cls = cls
                    break

            if target_cls is None:
                # 尝试从方法的 __globals__ 中查找
                if hasattr(method, "__globals__"):
                    target_cls = method.__globals__.get(class_name)

        if target_cls is None:
            raise ValueError(f"Cannot find class for method {method_name}")

        # 检查是否为 classmethod 声明
        declared_classmethods = getattr(target_cls, _DECLARED_CLASSMETHODS, set())
        is_classmethod = method_name in declared_classmethods

        # 检查是否为 staticmethod 声明
        declared_staticmethods = getattr(target_cls, _DECLARED_STATICMETHODS, set())
        is_staticmethod = method_name in declared_staticmethods

        # 检查是否为普通方法声明
        declared_methods = getattr(target_cls, _DECLARED_METHODS, set())
        is_method = method_name in declared_methods

        if not (is_method or is_classmethod or is_staticmethod):
            raise ValueError(
                f"Method '{method_name}' is not declared in {target_cls.__name__}"
            )

        # 检查重复实现
        if target_cls in _method_registry and method_name in _method_registry[target_cls]:
            if not override:
                raise ValueError(
                    f"Method '{method_name}' already implemented for {target_cls.__name__}. "
                    f"Use @pyic.impl({target_cls.__name__}.{method_name}, override=True) to override."
                )

        # 注册实现
        if target_cls not in _method_registry:
            _method_registry[target_cls] = {}
        _method_registry[target_cls][method_name] = func

        # 保留类引用，便于后续 override
        func.__pyic_class__ = target_cls
        func.__name__ = method_name
        func.__qualname__ = f"{target_cls.__name__}.{method_name}"

        # 替换类上的方法（根据类型包装）
        if is_classmethod:
            setattr(target_cls, method_name, classmethod(func))
        elif is_staticmethod:
            setattr(target_cls, method_name, staticmethod(func))
        else:
            setattr(target_cls, method_name, func)

        return func

    return decorator
