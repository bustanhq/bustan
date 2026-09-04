"""A feature module with its own plain class also named Config."""

from __future__ import annotations

from bustan import Injectable, InjectionToken, Module

from .shared import SharedModule

CONFIG = InjectionToken("CONFIG")


class Config:
    source = "feature.Config plain settings object"


@Injectable()
class FeatureService:
    # The author means feature.Config, which is bound under the CONFIG token, not as a class token.
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg


@Module(
    imports=[SharedModule],
    providers=[FeatureService, {"provide": CONFIG, "use_value": Config()}],
)
class FeatureModule:
    pass
