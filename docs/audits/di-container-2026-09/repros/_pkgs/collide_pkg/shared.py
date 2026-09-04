"""A shared module exporting a provider class named Config."""

from __future__ import annotations

from bustan import Injectable, Module


@Injectable()
class Config:
    source = "shared.Config provider"


@Module(providers=[Config], exports=[Config])
class SharedModule:
    pass
