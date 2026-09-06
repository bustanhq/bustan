# Changelog

> [!IMPORTANT]
> Versions `1.0.0` and `1.0.1` were unintentionally released during CI/CD setup. These releases contain the core framework but should be treated as early alpha orphans. The first production-ready release will be `2.0.0`.

## [2.0.0-rc.2](https://github.com/bustanhq/bustan/compare/v1.1.0...v2.0.0rc2) (2026-09-06)

The first release candidate published from `main`. It carries the whole of the 2.0.0-rc.1 and
2.0.0-rc.2 milestones: rc.1 emptied without ever being tagged, so its work ships here rather
than in a release of its own.

Every entry below is a closed milestone issue, grouped by the classification label it carries.
Three are not listed: the two epics that group the waves, and one report closed as a duplicate
of another in the same milestone.

> [!NOTE]
> `1.1.1` was published on 2026-09-04 from a branch that was never merged to `main`, and no
> changelog entry or version bump followed it. The four fixes it carried were ported into `main`
> under [#62](https://github.com/bustanhq/bustan/issues/62), listed under rc.1 below, so this release supersedes it. `main`'s
> version files read `1.1.0` until this release; they now read `2.0.0rc2`.

### 2.0.0-rc.2 - the resolution kernel's remaining defects (15 issues)

#### Security

* EX-04: a 403 body names the guard's dotted class path and the auth strategy, with debug off ([#65](https://github.com/bustanhq/bustan/issues/65))

#### Correctness

* CR-06 remainder: an unhashable durable context key surfaces as a raw TypeError ([#66](https://github.com/bustanhq/bustan/issues/66))
* T-200 Lifecycle correctness ([#67](https://github.com/bustanhq/bustan/issues/67))
* T-202 Testing surface delegates to the lifecycle ([#68](https://github.com/bustanhq/bustan/issues/68))
* T-201 Override semantics ([#69](https://github.com/bustanhq/bustan/issues/69))
* T-203 Global pipeline providers resolve per request ([#70](https://github.com/bustanhq/bustan/issues/70))
* Follow-up: resolving between a shutdown and the next startup hands back an uninitialized provider ([#75](https://github.com/bustanhq/bustan/issues/75))
* Follow-up: the route scanner has no notion of framework hooks, so any future one reads as an undecorated route method ([#76](https://github.com/bustanhq/bustan/issues/76))
* Follow-up: available_providers still keys by equality after the token-identity change ([#77](https://github.com/bustanhq/bustan/issues/77))
* Arm the bootstrap-only override rule, and retire the documented pattern it refuses ([#80](https://github.com/bustanhq/bustan/issues/80))
* Follow-up: the singleton and durable caches are the last tables keyed by equality alone ([#81](https://github.com/bustanhq/bustan/issues/81))
* RF-05: APPLICATION resolves to four different types depending on entry path ([#82](https://github.com/bustanhq/bustan/issues/82))
* OL-02b: a module cannot declare two APP_GUARD entries, because the duplicate-token rule refuses them first ([#83](https://github.com/bustanhq/bustan/issues/83))
* Follow-up: the durable-controller refusal lives on the create_app path only, so a context accepts what an app refuses ([#88](https://github.com/bustanhq/bustan/issues/88))
* Two Annotated Inject markers naming equal tokens of different types collapse into one ([#115](https://github.com/bustanhq/bustan/issues/115))

### 2.0.0-rc.1 - foundation and the plan-then-execute kernel (19 issues)

#### Security

* T-103 Effective scope algebra ([#45](https://github.com/bustanhq/bustan/issues/45))
* 2.0.0 would ship without four fixes that 1.1.1 already has: CR-01, RI-02, RI-05, RI-12 ([#62](https://github.com/bustanhq/bustan/issues/62))
* RI-10: a durable-scoped controller with no context-key hook is served as one instance to every tenant ([#64](https://github.com/bustanhq/bustan/issues/64))

#### Correctness

* T-001 Formatting and lint baseline ([#27](https://github.com/bustanhq/bustan/issues/27))
* Follow-up: scope validation is skipped for a graph with no controllers ([#33](https://github.com/bustanhq/bustan/issues/33))
* T-003 Shared test fixtures ([#35](https://github.com/bustanhq/bustan/issues/35))
* T-004 Stop the suite defending the defects ([#41](https://github.com/bustanhq/bustan/issues/41))
* T-101 One source of visibility truth ([#43](https://github.com/bustanhq/bustan/issues/43))
* T-102 Annotation resolution engine ([#44](https://github.com/bustanhq/bustan/issues/44))
* T-100 Provider normalization and token identity ([#47](https://github.com/bustanhq/bustan/issues/47))
* Follow-up: a local binding silently shadows an imported export of an equal token (PN-11, cross-module half) ([#55](https://github.com/bustanhq/bustan/issues/55))
* Follow-up: a durable provider with no context key hook is still accepted at bootstrap ([#56](https://github.com/bustanhq/bustan/issues/56))
* Follow-up: ControllerFactory still reads provider metadata with an inheriting getattr ([#57](https://github.com/bustanhq/bustan/issues/57))

#### Architecture

* T-002 Honest quality gates and release hygiene ([#34](https://github.com/bustanhq/bustan/issues/34))
* T-104 Plan-then-execute kernel ([#58](https://github.com/bustanhq/bustan/issues/58))

#### Documentation

* TROUBLESHOOTING.md gives the wrong fix for a module export, and covers no InvalidModuleError ([#52](https://github.com/bustanhq/bustan/issues/52))
* Follow-up: the scope documentation contradicts the rules the kernel now enforces ([#53](https://github.com/bustanhq/bustan/issues/53))
* Make the troubleshooting and scope documentation match the framework rc.1 actually ships ([#84](https://github.com/bustanhq/bustan/issues/84))

#### Operability

* The verification block dirties six example lockfiles on a clean checkout ([#54](https://github.com/bustanhq/bustan/issues/54))

## [1.1.0](https://github.com/bustanhq/bustan/compare/v1.0.1...v1.1.0) (2026-05-07)


### Features

* add native IoC kernel with provider tokens and provider definitions ([d7dd8fa](https://github.com/bustanhq/bustan/commit/d7dd8fa812a335e0613e61eb6c27c83275729593))
* expand framework core capabilities ([3cf36af](https://github.com/bustanhq/bustan/commit/3cf36af33d077089b606c4578d4d8c230a1a3b8e))
* expand framework core capabilities ([1659e7c](https://github.com/bustanhq/bustan/commit/1659e7c55ca16361e9830e1c1f02a0c6fbf1627c))
* implement Body, Query, Param, Header parameter decorators ([81b03dd](https://github.com/bustanhq/bustan/commit/81b03ddc89a24cf366164b5820d74331afc21f12))
* implement dynamic module support and update pre-commit hooks ([46fc5a4](https://github.com/bustanhq/bustan/commit/46fc5a4312bdbe4252e17c11200ed7c225c26823))
* implement NestJS-like application factory and async context hierarchy ([71db722](https://github.com/bustanhq/bustan/commit/71db72288ed2d0e85517be6413beb72e0518e291))
* replace dependency_injector internals with pure Python implementation ([a682713](https://github.com/bustanhq/bustan/commit/a682713a186f95bf16a3bb37c64e2fb3eecf350b))


### Bug Fixes

* CI failures - scaffold app.py rename, request-scoped controller example, API reference sync ([f99f2aa](https://github.com/bustanhq/bustan/commit/f99f2aa1994bb29c81e6cab5d6c55cf7af06de9d))
* **container:** keep local bindings authoritative over imported exports; fix root_key usage in ApplicationContext ([871f1f4](https://github.com/bustanhq/bustan/commit/871f1f463a71493b168b7c39eda4d10a5e8dddb3))
* detect version collisions for header/media-type versioning in compile_routes ([fcd7e49](https://github.com/bustanhq/bustan/commit/fcd7e49b68616dd45f8c51c40a7b5e2845a5aed4))
* lifecycle hooks, cookie binding, and Ip/HostParam alias handling ([862c626](https://github.com/bustanhq/bustan/commit/862c6267dc1c118012bf5f477764c18034051876))
* **scopes:** make get_singleton_lock thread-safe with a guard lock ([17209ba](https://github.com/bustanhq/bustan/commit/17209bae7ea2bec4a7b9504e7b52d7339721b650))


### Documentation

* reconcile public contract and versioning (P0) ([ab8157d](https://github.com/bustanhq/bustan/commit/ab8157d776ff6c8d8d01f821c5c6fbecf7a36ddd))
* reframe as agnostic ASGI architecture and implement Application properties (P0) ([83519b6](https://github.com/bustanhq/bustan/commit/83519b6036a9808776ea56c66c752f2587ecfa09))
* refresh api reference ([3191442](https://github.com/bustanhq/bustan/commit/319144263e14fe8e62b38001119783ee04ef2357))

## [1.0.1](https://github.com/bustanhq/bustan/compare/v1.0.0...v1.0.1) (2026-04-05)


### Bug Fixes

* **release:** use plural releases_created and update package name ([e196500](https://github.com/bustanhq/bustan/commit/e1965000f6d124ed2d2fe70927d7df251bd590d9))
* **release:** use plural releases_created and update package name ([70bcb08](https://github.com/bustanhq/bustan/commit/70bcb087bcb27cb49963cf2fae95054d1eb3e986))

## [1.0.0](https://github.com/bustanhq/bustan/compare/v0.1.0...v1.0.0) (2026-04-05)


### ⚠ BREAKING CHANGES

* All public decorators are now PascalCase. Existing snake_case names are no longer supported.

### Features

* prepare open source adoption baseline ([03ec783](https://github.com/bustanhq/bustan/commit/03ec7835fac2954fff3c1ba7349cb9935851c172))


### Bug Fixes

* unblock release-please pull request creation ([2127063](https://github.com/bustanhq/bustan/commit/21270638b813c1838c7b5a5c09e181261a799f53))
* unblock release-please pull request creation ([d84986f](https://github.com/bustanhq/bustan/commit/d84986f5367e34b7c8c24def8d2b92b09dfcf79d))


### Documentation

* update contact and support email addresses ([236d2c8](https://github.com/bustanhq/bustan/commit/236d2c8152932e02757f30eb61ff4851006e6160))


### Code Refactoring

* rename public decorators to PascalCase ([9cd6e00](https://github.com/bustanhq/bustan/commit/9cd6e00ab14f935110de7e9dc1bfe35eb2252ce9))

## [0.1.0](https://github.com/bustanhq/bustan/compare/v0.0.1...v0.1.0) (2026-04-04)


### Features

* prepare open source adoption baseline ([03ec783](https://github.com/bustanhq/bustan/commit/03ec7835fac2954fff3c1ba7349cb9935851c172))


### Bug Fixes

* unblock release-please pull request creation ([2127063](https://github.com/bustanhq/bustan/commit/21270638b813c1838c7b5a5c09e181261a799f53))
* unblock release-please pull request creation ([d84986f](https://github.com/bustanhq/bustan/commit/d84986f5367e34b7c8c24def8d2b92b09dfcf79d))

## Changelog

All notable changes to this project will be documented in this file.

The changelog is intended to be generated and maintained from Conventional Commits by CI-driven release automation.

## Unreleased

### Added

- Open source adoption baseline: licensing, trust docs, contributor guidance, templates, and stronger CI packaging checks.
