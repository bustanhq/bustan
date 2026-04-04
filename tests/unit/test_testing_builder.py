"""Unit tests for dynamic test-module construction."""

from star import controller, get, injectable
from star.metadata import ModuleMetadata, get_module_metadata
from star.testing import create_test_module


def test_create_test_module_builds_module_metadata_from_arguments() -> None:
    @injectable
    class UserService:
        pass

    @controller("/users")
    class UserController:
        @get("/")
        def list_users(self) -> list[dict[str, str]]:
            return [{"name": "Ada"}]

    TestUsersModule = create_test_module(
        name="TestUsersModule",
        controllers=[UserController],
        providers=[UserService],
        exports=[UserService],
    )

    assert TestUsersModule.__name__ == "TestUsersModule"
    assert get_module_metadata(TestUsersModule) == ModuleMetadata(
        imports=(),
        controllers=(UserController,),
        providers=(UserService,),
        exports=(UserService,),
    )