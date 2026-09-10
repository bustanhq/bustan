"""Unit tests for Application.listen() functionality (Asynchronous)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from bustan import Module, create_app


@Module()
class RootModule:
    pass


@pytest.mark.anyio
async def test_application_listen_default() -> None:
    app = create_app(RootModule)

    # uvicorn.Server.serve is the async method called by adapter.listen
    with patch("uvicorn.Server.serve", new_callable=AsyncMock) as mock_serve:
        # We need to mock the Server instantiation to capture the config if needed,
        # but mocking serve is sufficient to verify it's awaited.
        await app.listen(3000)
        mock_serve.assert_awaited_once()


@pytest.mark.anyio
async def test_application_listen_custom_args() -> None:
    app = create_app(RootModule)

    with (
        patch("uvicorn.Config") as mock_config_cls,
        patch("uvicorn.Server.serve", new_callable=AsyncMock) as mock_serve,
    ):
        await app.listen(8080, host="0.0.0.0", log_level="debug")

        mock_config_cls.assert_called_once()
        args, kwargs = mock_config_cls.call_args
        assert kwargs["host"] == "0.0.0.0"
        assert kwargs["port"] == 8080
        assert kwargs["log_level"] == "debug"

        mock_serve.assert_awaited_once()


@pytest.mark.anyio
async def test_asking_for_a_reloader_is_refused_rather_than_quietly_discarded() -> None:
    """The wrapper forwards the flag and the adapter underneath refuses it.

    Reloading means owning the process, which belongs to a development server rather
    than to an adapter. The flag used to reach uvicorn's configuration beside a live
    application object, where it changed nothing, so an application asked to reload
    served without reloading and said so nowhere.
    """

    app = create_app(RootModule)

    with pytest.raises(NotImplementedError, match="no reloader"):
        await app.listen(8080, reload=True)
