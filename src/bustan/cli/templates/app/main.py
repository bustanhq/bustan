from __future__ import annotations

from bustan import create_app as _create_bustan_app

from . import AppModule, app


def create_app():
    return _create_bustan_app(AppModule)


def main() -> None:
    import uvicorn

    uvicorn.run("$package_name:app", reload=True)


if __name__ == "__main__":
    main()
