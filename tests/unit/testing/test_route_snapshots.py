"""Unit tests for application route snapshots and diffs."""

from __future__ import annotations

from bustan import Controller, Get, Module, create_app


def test_application_route_snapshots_are_deterministically_sorted() -> None:
    @Controller("/zeta")
    class ZetaController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "zeta"}

    @Controller("/alpha")
    class AlphaController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "alpha"}

    @Module(controllers=[ZetaController, AlphaController])
    class AppModule:
        pass

    app = create_app(AppModule)
    first = app.snapshot_routes()
    second = app.snapshot_routes()

    assert first == second
    assert [item["path"] for item in first] == ["/alpha", "/zeta"]
    assert first[0]["controller"] == "AlphaController"
    assert first[1]["controller"] == "ZetaController"


def test_application_route_diff_reports_additions_removals_and_changed_dimensions() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"route": "users"}

    @Controller("/alpha")
    class AlphaController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"route": "alpha"}

    @Module(controllers=[UsersController, AlphaController])
    class PreviousModule:
        pass

    previous_snapshot = create_app(PreviousModule).snapshot_routes()

    @Controller("/members")
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"route": "members"}

    @Controller("/beta")
    class BetaController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"route": "beta"}

    @Module(controllers=[UsersController, BetaController])
    class CurrentModule:
        pass

    diff = create_app(CurrentModule).diff_routes(previous_snapshot)

    assert [(entry["change"], entry["route"]) for entry in diff] == [
        ("removed", "AlphaController.index"),
        ("added", "BetaController.index"),
        ("changed", "UsersController.index"),
    ]
    assert diff[0]["before"] is not None
    assert diff[0]["after"] is None
    assert diff[1]["before"] is None
    assert diff[1]["after"] is not None
    assert diff[2]["fields"] == ["module", "path"]