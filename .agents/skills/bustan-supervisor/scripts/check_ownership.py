#!/usr/bin/env python3
"""Compare a pull request's changed paths against its ticket's file-ownership list.

File ownership is what lets delivery agents who cannot see each other work the same
repository at the same time, so it is the first gate a pull request has to clear. This
reports every changed path that no ownership pattern allows, and exits non-zero when
there is at least one.

Patterns come either from the ticket issue, parsed out of its `Owns` section, or from
repeated `--owns` flags. The parsed patterns are always printed: read that line before
trusting the verdict, and switch to explicit `--owns` flags when the parse is wrong.

A pattern ending in `/` or `**` matches everything beneath it. Everything else is
matched with shell globbing, where `*` does not cross a directory separator.

Needs a GitHub token in GH_TOKEN or GITHUB_TOKEN.
"""

import argparse
import fnmatch
import json
import os
import re
import sys
import urllib.error
import urllib.request

API_ROOT = "https://api.github.com"
PAGE_SIZE = 100

# An Owns section ends at the next bold lead-in, the next markdown heading, or a rule.
SECTION_END = re.compile(r"^\s*(\*\*[A-Z]|#{1,6}\s|---\s*$)")
OWNS_HEADING = re.compile(r"^\s*(\*\*Owns\*\*|#{1,6}\s+Owns\b)", re.IGNORECASE)
BACKTICKED = re.compile(r"`([^`]+)`")


class GitHubError(RuntimeError):
    """The GitHub API refused a request or returned something unusable."""


def _token() -> str:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise GitHubError("set GH_TOKEN or GITHUB_TOKEN to a token that can read the repository")
    return token


def _get(path: str) -> object:
    request = urllib.request.Request(  # noqa: S310 - the scheme is fixed by API_ROOT
        f"{API_ROOT}{path}",
        headers={
            "Authorization": f"Bearer {_token()}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "bustan-supervisor-ownership-check",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:  # noqa: S310 - as above
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise GitHubError(f"GET {path} returned {error.code}: {error.reason}") from error
    except urllib.error.URLError as error:
        raise GitHubError(f"GET {path} failed: {error.reason}") from error


def changed_paths(repo: str, pull_number: int) -> list[str]:
    """Return every path the pull request touches, following pagination."""
    paths: list[str] = []
    page = 1
    while True:
        batch = _get(f"/repos/{repo}/pulls/{pull_number}/files?per_page={PAGE_SIZE}&page={page}")
        if not isinstance(batch, list):
            raise GitHubError(f"unexpected response listing files for pull request {pull_number}")
        paths.extend(entry["filename"] for entry in batch)
        if len(batch) < PAGE_SIZE:
            return sorted(paths)
        page += 1


def owns_patterns_from_issue(repo: str, issue_number: int) -> list[str]:
    """Pull the backticked paths out of an issue's Owns section.

    This is a best-effort parse of prose, which is why the caller prints what it found
    and can override it. Anything after the Owns section's first following heading, bold
    lead-in, or horizontal rule is ignored.
    """
    issue = _get(f"/repos/{repo}/issues/{issue_number}")
    if not isinstance(issue, dict) or not issue.get("body"):
        raise GitHubError(f"issue {issue_number} has no body to parse")

    patterns: list[str] = []
    inside = False
    for line in issue["body"].splitlines():
        if not inside:
            if OWNS_HEADING.match(line):
                inside = True
                patterns.extend(BACKTICKED.findall(line))
            continue
        if SECTION_END.match(line) and not OWNS_HEADING.match(line):
            break
        patterns.extend(BACKTICKED.findall(line))

    if not patterns:
        raise GitHubError(
            f"found no backticked paths in the Owns section of issue {issue_number}; "
            "pass the patterns explicitly with --owns"
        )
    return patterns


def is_owned(path: str, patterns: list[str]) -> bool:
    """Report whether any ownership pattern covers this path."""
    for pattern in patterns:
        prefix = pattern.rstrip("/")
        if prefix.endswith("/**"):
            prefix = prefix[: -len("/**")]
        if pattern.endswith(("/", "/**")) and (path == prefix or path.startswith(f"{prefix}/")):
            return True
        if fnmatch.fnmatchcase(path, pattern):
            return True
        # A bare directory name owns its contents, which is how tickets usually phrase it.
        if path.startswith(f"{prefix}/"):
            return True
    return False


def _print_tolerating_closed_pipe(lines: list[str]) -> None:
    """Write the report, giving up quietly if the reader has already stopped reading."""
    try:
        for line in lines:
            print(line)
        sys.stdout.flush()
    except BrokenPipeError:
        # Point the dead stream at nothing so the interpreter's shutdown flush stays quiet.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--pr", required=True, type=int, help="pull request number to check")
    parser.add_argument(
        "--owns-from-issue",
        type=int,
        metavar="N",
        help="parse ownership patterns from issue N's Owns section",
    )
    parser.add_argument(
        "--owns",
        action="append",
        default=[],
        metavar="PATTERN",
        help="an ownership pattern; repeat for more, and overrides --owns-from-issue",
    )
    arguments = parser.parse_args()

    if not arguments.owns and arguments.owns_from_issue is None:
        parser.error("give --owns at least once, or --owns-from-issue")

    try:
        patterns = arguments.owns or owns_patterns_from_issue(
            arguments.repo, arguments.owns_from_issue
        )
        paths = changed_paths(arguments.repo, arguments.pr)
    except GitHubError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    violations = [path for path in paths if not is_owned(path, patterns)]

    # The verdict is settled before anything is printed, so a reader that closes the
    # pipe early - piping into head, say - cannot be mistaken for a violation. The exit
    # code is this tool's whole product and must not depend on who is reading it.
    source = "--owns" if arguments.owns else f"issue #{arguments.owns_from_issue}"
    report = [
        f"ownership patterns ({source}): {', '.join(patterns)}",
        f"pull request #{arguments.pr} changes {len(paths)} files",
        "",
        *(f"{'OUTSIDE OWNS' if path in violations else 'ok          '}  {path}" for path in paths),
        "",
    ]
    if violations:
        report.append(
            f"{len(violations)} of {len(paths)} changed files are outside the ticket's Owns list."
        )
        report.append("This is REQUEST_CHANGES regardless of the quality of the change.")
    else:
        report.append(f"All {len(paths)} changed files are within the ticket's Owns list.")

    _print_tolerating_closed_pipe(report)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
