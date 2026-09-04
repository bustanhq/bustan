"""CR-02: the sync resolve path serializes singleton construction with a threading.Lock while the
async path uses a separate anyio.Lock. A sync resolution running in a worker thread and an async
resolution on the event loop can construct the same singleton twice; the loser is discarded without
any lifecycle hook, so any resource it opened leaks.
"""

import threading
import time

import anyio

from bustan import Injectable, Module, create_app_context

constructions = {"count": 0}


@Injectable()
class ConnectionPool:
    def __init__(self) -> None:
        constructions["count"] += 1
        time.sleep(0.5)  # simulate opening connections


@Module(providers=[ConnectionPool])
class AppModule:
    pass


def main() -> None:
    context = create_app_context(AppModule)
    container = context.container
    root = context.root_key

    def resolve_sync() -> None:
        container.resolve(ConnectionPool, module=root)

    async def race() -> None:
        thread = threading.Thread(target=resolve_sync)
        thread.start()
        await anyio.sleep(0.1)
        await container.resolve_async(ConnectionPool, module=root)
        thread.join()

    anyio.run(race)
    if constructions["count"] > 1:
        print(f"RESULT: CR-02 REPRODUCED - singleton constructed {constructions['count']} times")
    else:
        print("RESULT: CR-02 FIXED - singleton constructed once")


if __name__ == "__main__":
    main()
