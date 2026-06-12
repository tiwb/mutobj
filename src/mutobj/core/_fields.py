from __future__ import annotations

from typing import Any, Callable, Generic, Mapping, TypeVar, cast

from ._classmeta import MutobjClassMeta, mutobj_meta_cache
from ._constants import MUTABLE_TYPES, is_dunder
from ._typing_utils import is_classvar


class _MissingSentinel:
    """Default-value sentinel used to distinguish unset from None."""

    def __repr__(self) -> str:
        return "MISSING"


MISSING: Any = _MissingSentinel()

_UNSET: Any = object()

STORAGE: Any = object()


class FieldSpec:
    """Transient field specification created by field(), consumed by the metaclass."""

    __slots__ = ("default", "default_factory", "init")

    def __init__(
        self,
        default: Any = MISSING,
        default_factory: Callable[[], Any] | None = None,
        init: bool = True,
    ) -> None:
        if default is not MISSING and default_factory is not None:
            raise TypeError("cannot specify both default and default_factory")
        self.default = default
        self.default_factory = default_factory
        self.init = init


def field(
    *,
    default: Any = MISSING,
    default_factory: Callable[[], Any] | None = None,
    init: bool = True,
) -> Any:
    return FieldSpec(default=default, default_factory=default_factory, init=init)


_F = TypeVar("_F")


class FieldInfo(Generic[_F]):
    """Public introspection handle for a declaration field.

    Returned by :func:`field_info` and :func:`fields`.  Provides a stable
    read-only view on a field's metadata regardless of internal refactoring.
    """

    __slots__ = ("_desc",)

    def __init__(self, desc: "AttributeDescriptor") -> None:
        self._desc = desc

    @property
    def name(self) -> str:
        return self._desc.name

    @property
    def annotation(self) -> Any:
        return self._desc.annotation

    @property
    def init(self) -> bool:
        return self._desc.init

    @property
    def has_default(self) -> bool:
        return self._desc.has_default

    def make_default(self) -> _F:
        if self._desc.default_factory is not None:
            return self._desc.default_factory()
        if self._desc.default is not MISSING:
            return self._desc.default
        raise ValueError(f"Attribute '{self._desc.name}' has no default")

    @property
    def getter(self) -> "AttributeGetterPlaceholder":
        return AttributeGetterPlaceholder(self._desc)

    @property
    def setter(self) -> "AttributeSetterPlaceholder":
        return AttributeSetterPlaceholder(self._desc)

    def __repr__(self) -> str:
        return f"FieldInfo(name={self.name!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FieldInfo):
            return self._desc is other._desc
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._desc)


class AttributeDescriptor:
    """Attribute descriptor used for declaration fields."""

    __slots__ = (
        "name",
        "annotation",
        "default",
        "default_factory",
        "init",
        "owner_cls",
        "readonly",
        "has_storage",
        "fget",
        "fset",
        "field_info",
    )

    def __init__(
        self,
        name: str,
        annotation: Any,
        default: Any = MISSING,
        default_factory: Callable[[], Any] | None = None,
        init: bool = True,
        *,
        owner_cls: type[Any] | None = None,
        readonly: bool = False,
        has_storage: bool = True,
        fget: Callable[..., Any] | None = None,
        fset: Callable[..., Any] | None = None,
    ) -> None:
        self.name = name
        self.annotation = annotation
        self.default = default
        self.default_factory = default_factory
        self.init = init
        self.owner_cls = owner_cls
        self.has_storage = has_storage
        self.readonly = readonly
        self.field_info: FieldInfo[Any] = FieldInfo[Any](self)
        if has_storage:
            self.fget = STORAGE
            self.fset = None if readonly else STORAGE
        else:
            self.fget = fget
            self.fset = fset

    @property
    def has_default(self) -> bool:
        return self.default is not MISSING or self.default_factory is not None

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self.field_info
        if self.fget is STORAGE:
            # 字段值统一存放在 obj.__mutobj_storage__（dict），lazy 求值默认值：
            # - 已显式赋值：直接命中
            # - default_factory：首次访问求值并缓存（保证多次访问拿到同一对象）
            # - default：每次返回 self.default，不写入 storage（节省内存）
            # - 无默认值：抛 AttributeError
            # 用 storage.get + is 判断替代 try/except KeyError，避免默认值字段
            # 每次访问都触发异常栈开销。
            storage: dict[str, Any] = obj.__mutobj_storage__
            value = storage.get(self.name, _UNSET)
            if value is not _UNSET:
                return value
            if self.default_factory is not None:
                value = self.default_factory()
                storage[self.name] = value
                return value
            if self.default is not MISSING:
                return self.default
            raise AttributeError(
                f"'{type(obj).__name__}' object has no attribute '{self.name}'"
            ) from None
        if self.fget is None:
            owner_name = self.owner_cls.__name__ if self.owner_cls is not None else "<unknown>"
            raise NotImplementedError(
                f"Property '{self.name}' getter is not implemented. "
                f"Use @mutobj.impl({owner_name}.{self.name}.getter) to provide implementation."
            )
        return self.fget(obj)

    def __set__(self, obj: Any, value: Any) -> None:
        fset = self.fset
        if fset is STORAGE:
            obj.__mutobj_storage__[self.name] = value
            return
        if fset is None:
            owner_name = self.owner_cls.__name__ if self.owner_cls is not None else "<unknown>"
            raise AttributeError(
                f"Property '{self.name}' is read-only or setter is not implemented. "
                f"Use @mutobj.impl({owner_name}.{self.name}.setter) to provide implementation."
            )
        fset(obj, value)

    def __delete__(self, obj: Any) -> None:
        try:
            del obj.__mutobj_storage__[self.name]
        except KeyError as exc:
            raise AttributeError(
                f"'{type(obj).__name__}' object has no attribute '{self.name}'"
            ) from exc


class AttributeGetterPlaceholder:
    def __init__(self, descriptor: AttributeDescriptor):
        self.descriptor = descriptor


class AttributeSetterPlaceholder:
    def __init__(self, descriptor: AttributeDescriptor):
        self.descriptor = descriptor


def _compute_ordered(cls: type, mc: MutobjClassMeta) -> dict[str, AttributeDescriptor]:
    ordered: dict[str, AttributeDescriptor] = {}
    for klass in cls.__mro__[1:]:
        bm = mutobj_meta_cache.get(klass)
        if bm is not None:
            for name, desc in bm.fields.items():
                if name not in ordered:
                    ordered[name] = desc
    for name, desc in mc.fields.items():
        ordered[name] = desc
    return ordered


def get_ordered_descriptors(cls: type, mc: MutobjClassMeta) -> dict[str, AttributeDescriptor]:
    """获取 ordered_descriptors，如已失效则重新计算并缓存。"""
    ordered = mc.ordered_descriptors
    if ordered is None:
        ordered = _compute_ordered(cls, mc)
        mc.ordered_descriptors = ordered
    return ordered



def field_info(field: _F, /) -> FieldInfo[_F]:
    """将类级字段 token 包装为 FieldInfo，供 pyright 推断字段值类型。

    用法::

        info = mutobj.field_info(Action.categories)
        cats = info.make_default()  # pyright 推断为 tuple[str, ...]
        _ = info.has_default

    与 :func:`fields` 的对比：
    - ``field_info(Cls.field)``：静态字段名，pyright 可推断字段值类型
    - ``fields(cls)["name"]``：动态字段名遍历，返回 ``FieldInfo[Any]``
    """
    if not isinstance(field, FieldInfo):
        raise TypeError(
            f"field_info(field) expects a class-level field token (e.g. Cls.field_name), "
            f"got {type(field).__name__!r}. Use mutobj.fields(cls)[name] "
            f"for dynamic field-name access."
        )
    return cast(FieldInfo[_F], field)


def fields(cls: type, /) -> Mapping[str, FieldInfo[Any]]:
    mc = mutobj_meta_cache.get(cls)
    if mc is not None:
        result: dict[str, FieldInfo[Any]] = {
            name: desc.field_info
            for name, desc in get_ordered_descriptors(cls, mc).items()
        }
        return result
    return {}


def _format_field_names(field_names: list[str]) -> str:
    """将字段名列表格式化为 "'a', 'b', 'c'" 形式，用于错误信息。"""
    return ", ".join(f"'{name}'" for name in field_names)


def validate_field_descriptor(owner_name: str, descriptor: AttributeDescriptor) -> None:
    """校验字段描述符合法性。

    供 Declaration / Extension / Implementation 三套元类共享。错误文案不再带
    类别前缀（"Declaration" / "Extension" 等），只用 owner_name 标识所属类。
    """


def validate_construction_fields(obj: Any, owner_label: str, *, hint: str) -> None:
    """校验构造完成后必填字段是否全部已赋值，缺失则抛出 TypeError。

    duck-typing 依赖 obj.__mutobj_storage__（dict[str, Any]）。供 Declaration /
    Extension / Implementation 三处构造完成后的字段完整性检查共用。
    """
    missing: list[str] = []
    storage: dict[str, Any] = obj.__mutobj_storage__
    cls: type[Any] = obj.__class__
    mc = mutobj_meta_cache.get(cls)
    if mc is not None:
        for name, desc in get_ordered_descriptors(cls, mc).items():
            if desc.has_storage and not desc.has_default and storage.get(desc.name, _UNSET) is _UNSET:
                missing.append(name)
    if missing:
        raise TypeError(
            f"{owner_label} missing field(s) after construction: "
            f"{_format_field_names(missing)}. {hint}"
        )


def process_field_annotations(
    annotations: dict[str, Any],
    namespace: dict[str, Any],
    module: str,
    owner_cls: type,
    parent_classvars: set[str] | None = None,
    skip: frozenset[str] = frozenset(),
) -> tuple[list[tuple[str, AttributeDescriptor]], set[str], list[AttributeDescriptor]]:
    """扫描本类 annotations，过滤 ClassVar，为每个字段创建 AttributeDescriptor。

    skip: 内部基础设施属性名集合，不进 field 系统。

    返回:
        (field_descriptors, classvar_attrs, inherited_redeclared)
        - field_descriptors: [(attr_name, descriptor), ...]，调用方负责挂载到 cls 上
        - classvar_attrs: 本类 annotations 中识别为 ClassVar 的字段名集合
        - inherited_redeclared: 父类已有 AttributeDescriptor、本类仅重复声明 annotation
          但未提供新值的字段 [AttributeDescriptor, ...]。每个 descriptor 是父类
          描述符的拷贝（owner_cls 设为本类），调用方负责 setattr + 记入 attr_registry。

    注意：此函数只处理本类 annotations，不处理父类字段覆写（Declaration 独有逻辑）。
    Extension / Implementation 的简单字段声明走这一条路即可。
    """
    if parent_classvars is None:
        parent_classvars = set()
    classvar_attrs: set[str] = set()
    descriptors: list[tuple[str, AttributeDescriptor]] = []
    inherited_redeclared: list[AttributeDescriptor] = []
    owner_name = owner_cls.__name__

    for attr_name, attr_type in annotations.items():
        if attr_name in skip:
            continue
        if is_classvar(attr_type, module) or attr_name in parent_classvars:
            classvar_attrs.add(attr_name)
            value = namespace.get(attr_name)
            if isinstance(value, FieldSpec):
                raise TypeError(
                    f"'{owner_name}' attribute '{attr_name}' is ClassVar "
                    f"and does not support field(default_factory=...). "
                    f"Use a plain default value or a module-level constant instead."
                )
            continue

        value = namespace.get(attr_name)
        if isinstance(value, FieldSpec):
            descriptor = AttributeDescriptor(
                attr_name,
                attr_type,
                default=value.default,
                default_factory=value.default_factory,
                init=value.init,
                owner_cls=owner_cls,
            )
        elif attr_name in namespace and not isinstance(value, AttributeDescriptor):
            if callable(value) or isinstance(value, property):
                continue
            if isinstance(value, MUTABLE_TYPES):
                type_name = type(cast(object, value)).__name__
                raise TypeError(
                    f"'{owner_name}' attribute '{attr_name}' uses mutable default "
                    f"value {type_name}. "
                    f"Use field(default_factory={type_name}) instead."
                )
            descriptor = AttributeDescriptor(
                attr_name,
                attr_type,
                default=value,
                owner_cls=owner_cls,
            )
        else:
            # 检查父类是否已有 AttributeDescriptor（用 base.__dict__ 沿 MRO 查找，
            # 绕过描述符协议，避免 getattr 返回 FieldInfo）。
            parent_desc: AttributeDescriptor | None = None
            for base in owner_cls.__mro__[1:]:
                base_val = base.__dict__.get(attr_name)
                if isinstance(base_val, AttributeDescriptor):
                    parent_desc = base_val
                    break
            if parent_desc is not None:
                # 父类已有描述符、本类无新值：拷贝父类描述符（owner_cls 改为本类）。
                desc = AttributeDescriptor(
                    attr_name,
                    parent_desc.annotation,
                    default=parent_desc.default,
                    default_factory=parent_desc.default_factory,
                    init=parent_desc.init,
                    owner_cls=owner_cls,
                    readonly=parent_desc.readonly,
                    has_storage=parent_desc.has_storage,
                    fget=parent_desc.fget if not parent_desc.has_storage else None,
                    fset=parent_desc.fset if not parent_desc.has_storage else None,
                )
                inherited_redeclared.append(desc)
                continue
            else:
                descriptor = AttributeDescriptor(attr_name, attr_type, owner_cls=owner_cls)

        validate_field_descriptor(owner_name, descriptor)
        descriptors.append((attr_name, descriptor))

    return descriptors, classvar_attrs, inherited_redeclared


def _get_classvars(cls: type) -> set[str]:
    """沿 MRO 收集所有已声明的 ClassVar 属性名。"""
    result: set[str] = set()
    for klass in cls.__mro__:
        mc = mutobj_meta_cache.get(klass)
        if mc is not None:
            result.update(mc.classvars)
    return result


def validate_class_setattr(
    cls: type,
    name: str,
    value: Any,
) -> None:
    """类级别 __setattr__ 校验。

    按命中顺序检查：
    1. callable / classmethod / staticmethod / property → 放行
    2. 已存在于 cls.__dict__ 的属性覆盖 → 放行
    3. 已声明 ClassVar → 放行
    4. Python dunder（以 __ 开头且结尾）→ 放行
    5. 否则 → TypeError

    调用方负责在此之前处理 AttributeDescriptor 分支。
    """
    if callable(value) or isinstance(value, (classmethod, staticmethod, property)):
        return

    if name in cls.__dict__:
        return

    if name in _get_classvars(cls):
        return

    # Python dunder（如 __module__ / __classdictcell__ 等）→ 放行
    if is_dunder(name):
        return

    raise TypeError(
        f"Cannot set '{name}' on class '{cls.__name__}': "
        f"class-level data must be declared with ClassVar[...] annotation. "
        f"Example: class {cls.__name__}(...):\n"
        f"    {name}: ClassVar[...] = default_value"
    )


def validate_class_namespace(
    cls: type,
    *,
    skip: frozenset[str] = frozenset(),
) -> None:
    """扫描 cls.__dict__，拒绝未声明的数据属性（渠道 A 漏点）。

    cls.__dict__ 中允许存在：
    - AttributeDescriptor（字段描述符）
    - callable / classmethod / staticmethod / property
    - 已声明 ClassVar（纯数据值）
    - Python dunder（以 __ 开头且结尾）
    - skip 集中的内部属性

    其余数据值一律 TypeError。
    """
    classvars = _get_classvars(cls)
    for attr_name, attr_value in cls.__dict__.items():
        if attr_name in skip:
            continue
        if is_dunder(attr_name):
            continue
        if isinstance(attr_value, AttributeDescriptor):
            continue
        if callable(attr_value) or isinstance(attr_value, (classmethod, staticmethod, property)):
            continue
        if attr_name in classvars:
            continue

        raise TypeError(
            f"'{cls.__name__}' has undeclared class-level data '{attr_name}'. "
            f"Class-level data must be declared with ClassVar[...] annotation. "
            f"Example: class {cls.__name__}(...):\n"
            f"    {attr_name}: ClassVar[...] = default_value"
        )
