"""Declaration 字段构造完整性测试。"""

import pytest

import mutobj


class TestRequiredInitFields:
    def test_pure_annotations_are_required(self) -> None:
        class Point(mutobj.Declaration):
            x: int
            y: int

        with pytest.raises(
            TypeError,
            match=r"Point missing field\(s\) after construction: 'x', 'y'",
        ):
            Point()

    def test_field_without_default_is_required(self) -> None:
        class Article(mutobj.Declaration):
            title: str = mutobj.field()
            slug: str = "ready"

        with pytest.raises(
            TypeError,
            match=r"Article missing field\(s\) after construction: 'title'",
        ):
            Article()

    def test_annotated_default_can_be_omitted(self) -> None:
        class Greeting(mutobj.Declaration):
            message: str = "hello"

        assert Greeting().message == "hello"


class TestInitFalseValidation:
    def test_init_false_requires_default(self) -> None:
        with pytest.raises(
            TypeError,
            match=(
                r"Declaration 'Token' field 'value' is init=False but has no default; "
                r"provide default/default_factory or set init=True\."
            ),
        ):
            class Token(mutobj.Declaration):
                value: str = mutobj.field(init=False)

    def test_runtime_field_override_keeps_validation(self) -> None:
        class Token(mutobj.Declaration):
            value: str = "ready"

        with pytest.raises(TypeError, match=r"field 'value' is init=False but has no default"):
            Token.value = mutobj.field(init=False)


class TestConstructionCompleteness:
    def test_custom_init_missing_field_is_rejected_after_post_init(self) -> None:
        class Box(mutobj.Declaration):
            width: float
            height: float

            def __init__(self, width: float) -> None: ...

        @mutobj.impl(Box.__init__)
        def _box_init(self: Box, width: float) -> None:
            self.width = width

        with pytest.raises(
            TypeError,
            match=(
                r"Box missing field\(s\) after construction: 'height'\. "
                r"Either pass them to __init__ or assign in __post_init__\."
            ),
        ):
            Box(3.0)

    def test_post_init_can_fill_missing_field_before_check(self) -> None:
        class Box(mutobj.Declaration):
            width: float
            label: str

            def __init__(self, width: float) -> None: ...
            def __post_init__(self) -> None: ...

        @mutobj.impl(Box.__init__)
        def _box_init(self: Box, width: float) -> None:
            self.width = width

        @mutobj.impl(Box.__post_init__)
        def _box_post_init(self: Box) -> None:
            self.label = f"w={self.width}"

        box = Box(3.0)
        assert box.label == "w=3.0"

    def test_missing_multiple_fields_are_reported_in_order(self) -> None:
        class Session(mutobj.Declaration):
            user_id: str
            token: str
            scope: str = "default"

        with pytest.raises(
            TypeError,
            match=r"Session missing field\(s\) after construction: 'user_id', 'token'",
        ):
            Session()

    def test_custom_init_super_chain_with_delayed_field_assignment(self) -> None:
        """回归测试：@impl __init__ 在 super() 链调用后再赋值字段。

        这个模式大量用于 mutgui 事件系统：
        event_handler_init 先调用 super().__init__()（空参数），
        然后才设置 self.args / self.kwargs。修复后的构造完整性检查
        在 __post_init__ 之后统一验证，不再在 super() 链中误报。
        """
        class Handler(mutobj.Declaration):
            args: tuple
            kwargs: dict

            def __init__(self, *args: object, **kwargs: object) -> None: ...

        class Callback(Handler):
            func: object

            def __init__(self, func: object, /, *args: object, **kwargs: object) -> None: ...

        @mutobj.impl(Handler.__init__)
        def _handler_init(self: Handler, *args: object, **kwargs: object) -> None:
            super(Handler, self).__init__()  # 空参数调用基类
            # 字段在 super() 之后才赋值——修复前会在此处报 TypeError
            self.args = args
            self.kwargs = kwargs

        @mutobj.impl(Callback.__init__)
        def _callback_init(
            self: Callback, func: object, /, *args: object, **kwargs: object
        ) -> None:
            super(Callback, self).__init__(*args, **kwargs)  # 链到 _handler_init
            self.func = func

        cb = Callback(print, "hello", key="world")
        assert cb.func is print
        assert cb.args == ("hello",)
        assert cb.kwargs == {"key": "world"}
