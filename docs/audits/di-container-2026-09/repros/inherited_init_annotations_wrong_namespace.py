"""LEAD-05: the resolver evaluates string annotations (PEP 563) of an inherited __init__ in the
SUBCLASS module's globals instead of the function's own globals, so names that only exist in the
base module (Inject, a token constant) raise NameError -> ProviderResolutionError.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "_pkgs"))

from inherit_pkg.base import SETTINGS  # noqa: E402
from inherit_pkg.child import UserRepository  # noqa: E402

from bustan import Module, create_app_context  # noqa: E402
from bustan.errors import ProviderResolutionError  # noqa: E402


@Module(providers=[UserRepository, {"provide": SETTINGS, "use_value": {"dsn": "sqlite://"}}])
class AppModule:
    pass


def main() -> None:
    context = create_app_context(AppModule)
    try:
        repo = context.get(UserRepository)
        print(f"RESULT: LEAD-05 FIXED - inherited constructor resolved settings={repo.settings}")
    except ProviderResolutionError as exc:
        print(f"RESULT: LEAD-05 REPRODUCED - {str(exc)[:120]}")


if __name__ == "__main__":
    main()
