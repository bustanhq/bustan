"""RF-01: the resolver builds a local namespace of every visible token keyed by __name__ and
passes it as localns to get_type_hints, where it takes precedence over the constructor module's
own globals. A string annotation naming the module's own class is silently rebound to any visible
provider class with the same name, and the wrong object is injected without an error.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "_pkgs"))

from collide_pkg.feature import FeatureModule, FeatureService  # noqa: E402

from bustan import create_app_context  # noqa: E402
from bustan.errors import ProviderResolutionError  # noqa: E402


def main() -> None:
    context = create_app_context(FeatureModule)
    try:
        service = context.get(FeatureService)
    except ProviderResolutionError as exc:
        print(
            f"RESULT: RF-01 FIXED - unresolvable annotation raised instead of misbinding: {str(exc)[:80]}"
        )
        return
    injected = type(service.cfg)
    if injected.__module__.endswith("shared"):
        print(
            f"RESULT: RF-01 REPRODUCED - feature.Config annotation received {injected.__module__}.Config"
        )
    else:
        print(f"RESULT: RF-01 FIXED - received {injected.__module__}.Config")


if __name__ == "__main__":
    main()
