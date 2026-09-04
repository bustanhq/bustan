"""LEAD-03: @Injectable stores its metadata as a plain class attribute, and normalize_provider reads
it with getattr, so a subclass registered without its own decorator binds the PARENT class under
the parent's token. The subclass is never constructed and cannot be resolved.
"""

from bustan import Injectable, Module, create_app_context
from bustan.core.ioc.registry import normalize_provider
from bustan.errors import ProviderResolutionError


@Injectable()
class BaseNotifier:
    kind = "base"


class EmailNotifier(BaseNotifier):
    kind = "email"


@Module(providers=[EmailNotifier])
class AppModule:
    pass


def main() -> None:
    binding = normalize_provider(EmailNotifier, AppModule)
    context = create_app_context(AppModule)
    try:
        resolved = context.get(EmailNotifier)
        print(f"RESULT: LEAD-03 FIXED - providers=[EmailNotifier] resolves {type(resolved).__name__}")
    except ProviderResolutionError as exc:
        print(
            "RESULT: LEAD-03 REPRODUCED - providers=[EmailNotifier] bound token="
            f"{binding.token.__name__} target={binding.target.__name__}; resolve(EmailNotifier): {exc}"
        )


if __name__ == "__main__":
    main()
