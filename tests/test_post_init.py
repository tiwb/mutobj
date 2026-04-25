"""__post_init__ 与 field(init=...) 测试。"""

import pytest

import mutobj
from mutobj import MISSING


class TestPostInit:
    """__post_init__ 自动调用行为。"""

    def test_post_init_runs_after_binding(self) -> None:
        class User(mutobj.Declaration):
            first_name: str
            last_name: str
            full_name: str = mutobj.field(default="", init=False)

            def __post_init__(self) -> None: ...

        @mutobj.impl(User.__post_init__)
        def _user_post_init(self: User) -> None:
            self.full_name = f"{self.first_name} {self.last_name}"

        user = User(first_name="Ada", last_name="Lovelace")
        assert user.full_name == "Ada Lovelace"

    def test_missing_post_init_is_ignored(self) -> None:
        class Counter(mutobj.Declaration):
            value: int = 1

        assert Counter().value == 1

    def test_post_init_can_use_positional_args(self) -> None:
        class Point(mutobj.Declaration):
            x: int
            y: int
            label: str = mutobj.field(default="", init=False)

            def __post_init__(self) -> None: ...

        @mutobj.impl(Point.__post_init__)
        def _point_post_init(self: Point) -> None:
            self.label = f"({self.x}, {self.y})"

        point = Point(3, 4)
        assert point.label == "(3, 4)"

    def test_impl_without_stub_declaration(self) -> None:
        """子类不声明 __post_init__ 桩,也能直接 @impl 覆盖。"""
        class Box(mutobj.Declaration):
            width: float
            height: float
            area: float = mutobj.field(default=0.0, init=False)

        @mutobj.impl(Box.__post_init__)
        def _box_post_init(self: Box) -> None:
            self.area = self.width * self.height

        box = Box(width=3.0, height=4.0)
        assert box.area == 12.0

    def test_impl_does_not_leak_to_siblings(self) -> None:
        """给一个子类 @impl __post_init__,不应影响兄弟类或基类。"""
        class Foo(mutobj.Declaration):
            tag: str = ""

        class Bar(mutobj.Declaration):
            tag: str = ""

        @mutobj.impl(Foo.__post_init__)
        def _foo_post_init(self: Foo) -> None:
            self.tag = "FOO"

        assert Foo().tag == "FOO"
        assert Bar().tag == ""               # 未触发 Foo 的覆盖
        assert mutobj.Declaration.__post_init__ is not Foo.__post_init__

    def test_post_init_fires_when_custom_init_skips_super(self) -> None:
        """@impl(__init__) 自定义构造不调 super 时,post_init 仍由元类强制触发。"""
        class Box(mutobj.Declaration):
            width: float
            area: float = mutobj.field(default=0.0, init=False)

            def __init__(self, width: float) -> None: ...
            def __post_init__(self) -> None: ...

        @mutobj.impl(Box.__init__)
        def _box_init(self: Box, width: float) -> None:
            self.width = width
            # 故意不调 super().__init__()

        @mutobj.impl(Box.__post_init__)
        def _box_post_init(self: Box) -> None:
            self.area = self.width * 2

        box = Box(width=5.0)
        assert box.area == 10.0


class TestFieldInit:
    """field(init=False) 行为。"""

    def test_init_false_rejects_keyword(self) -> None:
        class Article(mutobj.Declaration):
            title: str
            slug: str = mutobj.field(default="", init=False)

        with pytest.raises(TypeError, match=r"unexpected keyword argument 'slug'"):
            Article(title="hello", slug="hello")

    def test_init_false_uses_default_factory(self) -> None:
        class Cache(mutobj.Declaration):
            name: str
            entries: list[str] = mutobj.field(default_factory=list, init=False)

        cache = Cache(name="users")
        assert cache.entries == []

    def test_init_false_excluded_from_positional_args(self) -> None:
        class Article(mutobj.Declaration):
            title: str
            slug: str = mutobj.field(default="", init=False)

        article = Article("hello")
        assert article.title == "hello"
        assert article.slug == ""

        with pytest.raises(TypeError, match=r"takes 1 positional arguments but 2 were given"):
            Article("hello", "world")


def test_missing_exported() -> None:
    assert MISSING is mutobj.MISSING
