"""MG-01: the module graph accepts re-exporting an imported token, but the container maps that
token to the re-exporting module, which holds no binding, so every resolution through the importer
fails with 'Binding not found'.
"""

from bustan import Injectable, Module, create_app_context
from bustan.errors import ProviderResolutionError


@Injectable()
class Repository:
    pass


@Module(providers=[Repository], exports=[Repository])
class DataModule:
    pass


@Module(imports=[DataModule], exports=[Repository])
class SharedModule:
    pass


@Injectable()
class Service:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository


@Module(imports=[SharedModule], providers=[Service])
class AppModule:
    pass


def main() -> None:
    context = create_app_context(AppModule)
    try:
        context.get(Service)
        print("RESULT: MG-01 FIXED - re-exported provider resolves through the importing module")
    except ProviderResolutionError as exc:
        print(f"RESULT: MG-01 REPRODUCED - graph accepted the re-export but resolve failed: {str(exc)[-60:]}")


if __name__ == "__main__":
    main()
