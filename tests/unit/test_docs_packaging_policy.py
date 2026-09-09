"""Hold the two packaging claims the documentation makes.

uv is the only supported package manager and Python 3.13 is the floor. Both were true in
every mechanism the project has long before they were true in its prose, and prose drifts:
a contributor reaching for the install line everyone else writes puts pip back without
noticing, and the floor is easy to state in a release note and nowhere a reader looks.
"""

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# The audit is a record of what was observed, not advice, and the delivery backlog quotes
# commands as they ran. Neither is read as instructions by a user installing the package.
EXCLUDED_DIRECTORIES = ("audits", "delivery")

# Installers a reader might reasonably try, and which nothing here is tested against.
FORBIDDEN_INSTALLERS = re.compile(
    r"\b(pip install|pip3 install|poetry add|pdm add|pipenv install|conda install)\b"
)

# The documents a newcomer opens before writing any code. A floor stated only in the
# release notes is a floor nobody meets until the resolver refuses them.
MUST_STATE_THE_FLOOR = (
    "README.md",
    "docs/README.md",
    "docs/tutorials/first-app.md",
    "docs/how-to/deploy.md",
    "docs/reference/cli.md",
    "docs/reference/versioning.md",
)


def _user_facing_documents() -> list[Path]:
    """Every Markdown file a reader could follow as instructions."""
    return [
        path
        for path in sorted(REPOSITORY_ROOT.glob("**/*.md"))
        if ".venv" not in path.parts
        and "node_modules" not in path.parts
        and ".pytest_cache" not in path.parts
        and not any(directory in path.parts for directory in EXCLUDED_DIRECTORIES)
    ]


def test_no_document_offers_an_installer_other_than_uv() -> None:
    offenders = [
        f"{path.relative_to(REPOSITORY_ROOT)}:{number}: {match.group(0)}"
        for path in _user_facing_documents()
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if (match := FORBIDDEN_INSTALLERS.search(line))
    ]
    assert not offenders, (
        "uv is the only supported package manager, and these lines offer another:\n  "
        + "\n  ".join(offenders)
    )


def test_the_framework_names_uv_when_an_extra_is_missing() -> None:
    """The install advice a user meets at the moment of failure is the one that matters."""
    from bustan.app.bootstrap import _STARLETTE_EXTRA_REQUIREMENT
    from bustan.conformance import _STARLETTE_EXTRA_MISSING

    for message in (_STARLETTE_EXTRA_REQUIREMENT, _STARLETTE_EXTRA_MISSING):
        assert "uv add" in message
        assert "pip install" not in message


def test_the_documents_a_newcomer_opens_state_the_python_floor() -> None:
    missing = [
        name for name in MUST_STATE_THE_FLOOR if "3.13" not in (REPOSITORY_ROOT / name).read_text()
    ]
    assert not missing, (
        "these are the documents a reader opens before writing code, and they do not "
        f"name the Python floor: {', '.join(missing)}"
    )


def test_the_floor_the_documents_state_is_the_floor_the_package_requires() -> None:
    """A stated floor that disagrees with `requires-python` is worse than none."""
    manifest = (REPOSITORY_ROOT / "pyproject.toml").read_text()
    declared = re.search(r'requires-python\s*=\s*">=(\d+\.\d+)"', manifest)
    assert declared, "pyproject.toml declares no requires-python"
    assert declared.group(1) == "3.13", (
        f"the documents name 3.13 as the floor and pyproject requires {declared.group(1)}; "
        "change both or neither"
    )
