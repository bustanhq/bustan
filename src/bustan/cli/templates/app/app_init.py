import asyncio

from bustan import create_app
from .app_module import AppModule

async def bootstrap(reload: bool = False):
    app = create_app(AppModule)
    await app.listen(port=3000, reload=reload)

def main():
    asyncio.run(bootstrap())

def dev():
    asyncio.run(bootstrap(reload=True))
