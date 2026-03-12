"""位置参数初始化测试。"""

import mutobj


class TestPositionalInit:
    """场景一：不写 __init__，自动位置参数。"""

    def test_positional_args(self) -> None:
        class Response(mutobj.Declaration):
            status: int = 200
            body: bytes = b""

        resp = Response(404, b"hello")
        assert resp.status == 404
        assert resp.body == b"hello"

    def test_kwargs_still_work(self) -> None:
        class Response(mutobj.Declaration):
            status: int = 200
            body: bytes = b""

        resp = Response(status=404, body=b"hello")
        assert resp.status == 404
        assert resp.body == b"hello"

    def test_mixed_args_kwargs(self) -> None:
        class Response(mutobj.Declaration):
            status: int = 200
            body: bytes = b""

        resp = Response(404, body=b"hello")
        assert resp.status == 404
        assert resp.body == b"hello"

    def test_defaults(self) -> None:
        class Response(mutobj.Declaration):
            status: int = 200
            body: bytes = b""

        resp = Response(404)
        assert resp.status == 404
        assert resp.body == b""

    def test_no_args(self) -> None:
        class Response(mutobj.Declaration):
            status: int = 200
            body: bytes = b""

        resp = Response()
        assert resp.status == 200
        assert resp.body == b""

    def test_too_many_args(self) -> None:
        class Response(mutobj.Declaration):
            status: int = 200
            body: bytes = b""

        try:
            Response(404, b"hello", "extra")  # type: ignore[call-arg]
            assert False, "Should have raised TypeError"
        except TypeError as e:
            assert "2 positional arguments but 3 were given" in str(e)

    def test_duplicate_arg(self) -> None:
        class Response(mutobj.Declaration):
            status: int = 200
            body: bytes = b""

        try:
            Response(404, status=200)  # type: ignore[misc]
            assert False, "Should have raised TypeError"
        except TypeError as e:
            assert "multiple values" in str(e)
            assert "status" in str(e)


class TestPositionalInitInheritance:
    """继承时字段顺序：父类在前（dataclass 惯例）。"""

    def test_parent_fields_first(self) -> None:
        class Base(mutobj.Declaration):
            x: int = 0

        class Child(Base):
            y: str = ""

        child = Child(1, "hello")
        assert child.x == 1
        assert child.y == "hello"

    def test_multiple_inheritance(self) -> None:
        class A(mutobj.Declaration):
            x: int = 0

        class B(mutobj.Declaration):
            y: str = ""

        class C(A, B):
            z: float = 0.0

        c = C(1, "hello", 3.14)
        assert c.x == 1
        assert c.y == "hello"
        assert c.z == 3.14

    def test_child_override_field(self) -> None:
        """子类覆盖父类字段时，位置顺序保持父类位置。"""

        class Base(mutobj.Declaration):
            x: int = 0
            y: str = ""

        class Child(Base):
            y: str = "override"
            z: float = 0.0

        child = Child(1, "hello", 3.14)
        assert child.x == 1
        assert child.y == "hello"
        assert child.z == 3.14


class TestCustomInit:
    """场景二：写了 __init__，Declaration 不干预。"""

    def test_custom_init(self) -> None:
        class Request(mutobj.Declaration):
            method: str = "GET"
            path: str = "/"

            def __init__(self, scope: dict) -> None:
                self.method = scope.get("method", "GET")
                self.path = scope.get("path", "/")

        req = Request({"method": "POST", "path": "/api"})
        assert req.method == "POST"
        assert req.path == "/api"

    def test_custom_init_defaults_not_applied(self) -> None:
        """自定义 __init__ 时，Declaration 不干预，未赋值的字段无值。

        注：字段默认值当前由 Declaration.__init__ 应用，自定义 __init__
        绕过了这一机制。未来可能由 metaclass 保证默认值始终应用。
        """

        class Thing(mutobj.Declaration):
            name: str = "default"
            value: int = 42

            def __init__(self, name: str) -> None:
                self.name = name

        thing = Thing("test")
        assert thing.name == "test"
        try:
            _ = thing.value
            assert False, "Should have raised AttributeError"
        except AttributeError:
            pass
