# Security Policy

## Reporting A Vulnerability

Do not open a public GitHub issue for security vulnerabilities.

Report security issues privately to `security@bustan.dev` with:

- a clear description of the issue
- impact and affected surface
- reproduction steps or proof of concept if available
- any suggested mitigation if you already have one

You should receive an acknowledgement within 5 business days.

## Disclosure Process

- The maintainer will confirm whether the report is a security issue.
- Fixes will be prepared privately when possible.
- Public disclosure should wait until a fix or mitigation is available.
- Credit will be given for responsible disclosure unless you request otherwise.

## Supported Versions

Security support is best-effort for:

- the default branch
- the most recent release on the current minor line: the newest release whose major and
  minor version match the `version` field in `pyproject.toml`

That list names no version on purpose. Read the field, apply the two bullets, and the
answer holds without this section being edited each time a release ships.

Pre-release candidates are not supported. A version carrying a pre-release suffix is
published so that the release can be tested, and a vulnerability found in one is fixed
on the default branch and ships in the next release rather than as a patched candidate.
That is stated rather than left to inference, because candidates are what the package
index offers while a line is being prepared: while the current line has published only
candidates, the default branch is the only supported code.

Earlier minor lines, unreleased snapshots and abandoned feature branches are not
supported. Support follows the current line rather than accumulating behind it, so a
line stops receiving security fixes once a newer one becomes current.