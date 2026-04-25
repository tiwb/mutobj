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
