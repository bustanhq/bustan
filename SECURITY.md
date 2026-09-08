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

Versions `1.0.0` and `1.0.1` were unintentionally released during CI/CD setup. Treat them as early alpha orphans. The first production-ready, non-alpha release target remains `2.0.0`. The release being prepared is the `version` field in `pyproject.toml`; read it there rather than from a list that cannot notice it moved.

Security support is best-effort for:

- the default branch
- the most recent tagged pre-`1.0` release, once releases begin

Older unreleased snapshots and abandoned feature branches are not supported.