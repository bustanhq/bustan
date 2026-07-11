"""Manual verification of the create_app factory and Application API (Async)."""

from __future__ import annotations

import httpx
import anyio
import pytest
from bustan import Module, Controller, Get, create_app, Injectable


@Injectable()
class HelloWorldService:
    def get_hello(self) -> str:
        return "Hello World!"


@Controller("/")
class AppController:
    def __init__(self, service: HelloWorldService):
        self.service = service

    @Get("/")
    def get_hello(self) -> dict[str, str]:
        return {"message": self.service.get_hello()}


@Module(
    controllers=[AppController],
    providers=[HelloWorldService]
)
class RootModule:
    pass


@pytest.mark.anyio
async def test_factory_manual_verification() -> None:
    # 1. Create App
    app = create_app(RootModule, debug=True)
    
    # 2. Verify DI access via app.get()
    service = app.get(HelloWorldService)
    assert service.get_hello() == "Hello World!"
    
    # 3. Verify HTTP handling via get_http_server()
    transport = httpx.ASGITransport(app=app.get_http_server())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert response.json() == {"message": "Hello World!"}

    # 4. Verify Async Listen (Mocked uvicorn to avoid blocking)
    from unittest.mock import AsyncMock, patch
    with patch("uvicorn.Server.serve", new_callable=AsyncMock) as mock_serve:
        await app.listen(3000)
        mock_serve.assert_awaited_once()

    print("Manual verification passed!")


if __name__ == "__main__":
    anyio.run(test_factory_manual_verification)
