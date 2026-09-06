# Changelog

> [!IMPORTANT]
> Versions `1.0.0` and `1.0.1` were unintentionally released during CI/CD setup. These releases contain the core framework but should be treated as early alpha orphans. The first production-ready release will be `2.0.0`.

## [2.0.0](https://github.com/bustanhq/bustan/compare/v1.1.0...v2.0.0) (2026-09-06)


### ⚠ BREAKING CHANGES

* **ioc:** a provider injecting APPLICATION inside an HTTP application now receives the application context rather than the Application wrapper, and a resolution entered with a request no longer falls back to the transport's own server object; a container built outside an application factory refuses the token instead.
* **lifecycle:** bustan.testing.override_provider raises ProviderResolutionError when its target application has already started. Register overrides before startup, or build the application with create_testing_module(...).override_provider(...).
* **core:** create_app_context now refuses a controller declaring a durable lifetime or the durable context key hook, which it previously accepted, and both entry points raise InvalidControllerError naming the declaration where a durable controller holding request-scoped state previously raised ProviderResolutionError naming a constructor parameter.
* **pipeline:** the `detail` of a guard rejection is now the fixed string `Forbidden` (or `Too Many Requests` when the request was throttled) rather than the guard's exception message. A client that read the message out of the body reads the log instead.
* **core:** a constructor parameter annotated `starlette.responses.Response` or `starlette.applications.Starlette` no longer resolves. Neither ever received the object it named - the response context has been the neutral `HttpResponse` since the adapter port was narrowed, and the application token has always resolved to the Bustan application - so a parameter naming them is now refused while the graph is planned rather than handed something else. Use `HttpResponse` and the `APPLICATION` token. `DurableProvider.get_durable_context_key` receives the neutral `HttpRequest` rather than the transport's request.
* **http:** AbstractHttpAdapter no longer declares compile_routes and no longer takes a container; it declares from_native_request, to_native_response, start, stop and create_test_client instead. Middleware.use is given a bustan.contracts.HttpRequest rather than a Starlette Request. The RESPONSE token and ExecutionContext.response now yield a bustan.HttpResponse rather than a Starlette Response. bustan.platform.http.abstractions is deleted; import the neutral types from bustan or bustan.contracts, and the Starlette helpers from bustan.adapters.starlette.
* **pipeline:** Container.get_global_pipeline_providers returns the modules declaring a global pipeline token rather than resolved instances, and ControllerFactory.instantiate and resolve_pipeline are replaced by their awaited counterparts. Both are internal per docs/STABILITY.md.
* **ioc:** an override now invalidates the instances already built from the provider it replaces, and an override of a singleton binding takes part in the lifecycle instead of being invisible to it. Code that relied on an override reaching only direct consumers, or on a replacement receiving no lifecycle hooks, will observe the new behaviour.
* **lifecycle:** a completed shutdown no longer makes an application context permanently closed. Startup after shutdown builds a fresh set of instances instead of raising, and resolving between the two builds a new instance rather than returning a destroyed one. A module whose constructor needs arguments is refused with InvalidModuleError rather than LifecycleError.
* **addons:** request_context_id keeps its signature but no longer returns a decimal object address. The value is now a generated identifier unique to the request, so nothing may parse it or expect it to match id(request).
* **ioc:** a {"provide": Token, "use_class": Cls} definition with no 'scope' key now binds under the scope Cls declares rather than always under singleton, and a definition whose 'scope' is wider than the one Cls declares is refused as an InvalidProviderError.
* **ioc:** the durable instance store holds at most 128 partitions and evicts the one used longest ago, so a durable instance is no longer kept for the life of the process. A partition that returns after being evicted is built again rather than served the instance it had before.
* **ioc:** a graph whose composition cannot work is refused by create_app and create_app_context instead of failing on the first request that touches it. Two shapes that used to start and then leak are now startup failures: an owner cached for longer than one request that holds the request, the response or a request-scoped provider, and a provider or controller whose dependency no module can supply. Constructing an equal DynamicModule twice now yields one registration rather than two.
* **module:** @Module refuses a set, frozenset or mapping for imports, controllers, providers or exports, and refuses a second @Module declaration on one class.
* **ioc:** provider definitions that were previously accepted and then failed at resolution are refused at bootstrap with InvalidProviderError. An undecorated subclass of an @Injectable class now binds as itself rather than as its parent.
* **module:** a module graph in which two global modules, or two unshadowed imports, export the same token is now refused at build time rather than resolved first-wins by import order, and a module class in an exports list is refused as a module rather than as a missing provider.

### Features

* **adapters:** add a raw ASGI adapter that binds no web framework ([11e0e79](https://github.com/bustanhq/bustan/commit/11e0e79e33e45a84f24b965ed7968f95c08a2330))
* complete roadmap runtime and governance support ([ae81089](https://github.com/bustanhq/bustan/commit/ae81089cd690cde7758dccfa15e3b7ca58126221))
* **contracts:** home every neutral HTTP type in bustan.contracts ([a2bcaa6](https://github.com/bustanhq/bustan/commit/a2bcaa6387b0020812d48d6c4ab8746c62fe312b))
* **contracts:** T-300 the contracts package ([9d62442](https://github.com/bustanhq/bustan/commit/9d62442d5622dd34ac4c06c38c87adb7b3b6d3da))
* **ioc:** compute effective scope from the binding table at build time ([cd3b86f](https://github.com/bustanhq/bustan/commit/cd3b86ff4cd15ae400ae47e2d8358866036b66b7))
* **ioc:** plan constructions at bootstrap and execute them at runtime ([fd79862](https://github.com/bustanhq/bustan/commit/fd79862cba798e7a8c556437ba2b484aceb7fca1))
* **ioc:** plan constructor dependencies as a pure function ([2c10cac](https://github.com/bustanhq/bustan/commit/2c10cacbcd8c0e4bc7d3974edb456a074b947075))


### Bug Fixes

* **adapters:** refuse a request whose two Content-Length headers disagree ([73484b2](https://github.com/bustanhq/bustan/commit/73484b2944dddfbaff1571be64d4665f80fe6768))
* **addons:** mint a request identifier that cannot collide across requests ([c484768](https://github.com/bustanhq/bustan/commit/c4847682214151331a6962a74989a485a03185c3))
* align smoke checks with local hooks ([af60d1b](https://github.com/bustanhq/bustan/commit/af60d1bb37d39f9a00025bcebff7028cbaf016a4))
* **app:** let an application context name the HTTP application built around it ([1d0deee](https://github.com/bustanhq/bustan/commit/1d0deeee82278f65c5bc969aa47a155433ea6f1d))
* **audit:** take RF-05's container probe inside the lifespan ([1fc59da](https://github.com/bustanhq/bustan/commit/1fc59da0610856754453cacb531dc30f6a5bb9b9))
* **audit:** take RF-05's container probe inside the lifespan ([7d783e7](https://github.com/bustanhq/bustan/commit/7d783e74ea8164765c81fee81cdbda6031733d15))
* **ci:** repair the published-package verification flow ([79874cd](https://github.com/bustanhq/bustan/commit/79874cde093bcb0337324bcac5443935b3cfa4cf))
* **core:** let a module declare several components under one pipeline token ([e7c42c1](https://github.com/bustanhq/bustan/commit/e7c42c1cd4a45a32163d8a6b2ade811934635096))
* **core:** let a module declare several components under one pipeline token ([e501ff9](https://github.com/bustanhq/bustan/commit/e501ff9271203a028155d0831cd23502fd62cacb))
* **core:** refuse an unservable controller lifetime where both entry points look ([bbb88e4](https://github.com/bustanhq/bustan/commit/bbb88e4cf63c9a1f987fb307cce2462e18693e33))
* **core:** refuse an unservable controller lifetime where both entry points look ([68e09d1](https://github.com/bustanhq/bustan/commit/68e09d10271b13ca097853858d5ae5bc1fa4edc8))
* **examples:** re-lock the six example projects and gate them in CI ([9e46316](https://github.com/bustanhq/bustan/commit/9e4631602a05e8dc47705fc6a82ffccf77b5f2b7)), closes [#54](https://github.com/bustanhq/bustan/issues/54)
* hardening pass — release verification, resolver seams, lifecycle teardown ([17d38e0](https://github.com/bustanhq/bustan/commit/17d38e0d4ea257cd7fea3237954a25314c3c4a8f))
* **http:** bind header parameters only from request headers ([4d98e72](https://github.com/bustanhq/bustan/commit/4d98e72ddd2012bd324d04f46e56832d69564cba))
* **http:** refuse a controller that asks for a lifetime it cannot be served under ([66a28f7](https://github.com/bustanhq/bustan/commit/66a28f70c8f3b60d83c384f207df39f7c2252ac8))
* **http:** refuse a controller that asks for a lifetime it cannot be served under ([1a50482](https://github.com/bustanhq/bustan/commit/1a50482684ce8d7943f3c12016bdfdef6372782e)), closes [#64](https://github.com/bustanhq/bustan/issues/64) [#57](https://github.com/bustanhq/bustan/issues/57)
* **http:** stop copying the placeholder content-length onto final responses ([b69f6e9](https://github.com/bustanhq/bustan/commit/b69f6e90198e696191d143900b6fdffd1fdbd19d))
* **ioc,addons:** forward-port CR-01, RI-02 and RI-12 from the 1.1.1 security patch ([3e7c48a](https://github.com/bustanhq/bustan/commit/3e7c48acc05b5ac6c7a7806fa798f3d3ea1ee89d))
* **ioc:** answer APPLICATION with one application context everywhere ([8a682bb](https://github.com/bustanhq/bustan/commit/8a682bb1a7021fe1219304263743d9f5f27b8820))
* **ioc:** answer APPLICATION with one application context everywhere ([496bf42](https://github.com/bustanhq/bustan/commit/496bf42d78f9c0c2ba8f584f32c9e731265e9591))
* **ioc:** bound the durable instance store and release construction locks ([02b40b7](https://github.com/bustanhq/bustan/commit/02b40b79f7e75b854241a47a0068513d28c0e608))
* **ioc:** fail an annotation name lookup with KeyError alone ([09c01be](https://github.com/bustanhq/bustan/commit/09c01beee9a3e8a9c3829d74f02a248dd669c981))
* **ioc:** harden resolver seams for cross-module identity and concurrency ([44be8bf](https://github.com/bustanhq/bustan/commit/44be8bf30b44e9b4155be75551e1f639431cd324))
* **ioc:** key provider tokens by type so equal tokens stay two providers ([54d1d27](https://github.com/bustanhq/bustan/commit/54d1d274a46a7018de0345b7a9a8f0d40be9f36c))
* **ioc:** key provider tokens by type so equal tokens stay two providers ([1dd6245](https://github.com/bustanhq/bustan/commit/1dd6245102d147bfd3b46a6660fe4805b94c4a92))
* **ioc:** key the instance caches by token identity ([052a0f5](https://github.com/bustanhq/bustan/commit/052a0f5a10c566162810955b3808fcd7595a9f07))
* **ioc:** key the instance caches by token identity ([cb96a9c](https://github.com/bustanhq/bustan/commit/cb96a9c0bdcf5f36b89d781182d567ad77b59ade)), closes [#81](https://github.com/bustanhq/bustan/issues/81)
* **ioc:** make an override reach everything built from what it replaces ([d26f9eb](https://github.com/bustanhq/bustan/commit/d26f9eb27f424cd9928e14e3147febf5a965266d))
* **ioc:** normalize providers from the class they were written on ([b9e3a3a](https://github.com/bustanhq/bustan/commit/b9e3a3aa65e765248399d2addb807144425d7b08))
* **ioc:** refuse an unhashable durable context key where the key is built ([723bf2a](https://github.com/bustanhq/bustan/commit/723bf2a070754eb7c280be899ea0014f58dde3c9))
* **ioc:** refuse an unhashable durable context key where the key is built ([9655fe9](https://github.com/bustanhq/bustan/commit/9655fe90b2f7d7f326d9547dac8767d545c7ab93))
* **ioc:** refuse resolution between a shutdown and the next startup ([0614a4a](https://github.com/bustanhq/bustan/commit/0614a4a0df0bfad74471b2377125eb202b287017))
* **ioc:** refuse resolution between a shutdown and the next startup ([8638168](https://github.com/bustanhq/bustan/commit/8638168416950f56a7e407e6f2a8634ffafdebd6))
* **ioc:** require an explicit durable context key instead of id(request) ([80551a3](https://github.com/bustanhq/bustan/commit/80551a380ee9442e019a76a8b991467fa50d2648))
* **ioc:** T-201 override semantics ([e5366c3](https://github.com/bustanhq/bustan/commit/e5366c3e261d8b0c911123faf67e9f1a4e0f4883))
* **ioc:** take a use_class binding's lifetime from the class it constructs ([780d4aa](https://github.com/bustanhq/bustan/commit/780d4aad6ce1c2d779abdf76a073878c7a103fdb))
* **ioc:** tell two Inject markers of differently typed tokens apart ([a71b2de](https://github.com/bustanhq/bustan/commit/a71b2ded978b9e5ec77e542f0097e6df0f138fe4))
* **ioc:** tell two Inject markers of differently typed tokens apart ([971600a](https://github.com/bustanhq/bustan/commit/971600ae5ba909b36117d472697fd03ab346038a))
* **lifecycle:** arm the bootstrap-only override rule and retire the pattern it refuses ([0ef070b](https://github.com/bustanhq/bustan/commit/0ef070b9a4e6f0b4c651d9b4d604aeda04987130))
* **lifecycle:** run hooks only on what the framework built, and undo a failed startup ([57dffee](https://github.com/bustanhq/bustan/commit/57dffee728f09ef3fe85ce5af0cf792bbc2ef3da))
* **lifecycle:** T-200 lifecycle correctness ([a8dd882](https://github.com/bustanhq/bustan/commit/a8dd8826ea9e274d400a65dccf959d9d581fdc66))
* **lifecycle:** tear down in reverse order and survive failing hooks ([2716c3c](https://github.com/bustanhq/bustan/commit/2716c3ca7bf8ffca41b363753583868dfbaafa8c))
* **module:** compute provider visibility once in the module graph ([f9626cd](https://github.com/bustanhq/bustan/commit/f9626cdfbca5986ea3b78ca9eab3c3c4d147c406))
* **module:** refuse module declarations that cannot be honoured ([7ffd9d5](https://github.com/bustanhq/bustan/commit/7ffd9d5bf359c4f5c86efddf36fa59cf0adeb79e))
* **pipeline:** answer a guard rejection with a fixed reason ([e6f4514](https://github.com/bustanhq/bustan/commit/e6f4514aa9e19b4f8ba9896eff87332e21df88fe))
* **pipeline:** resolve global pipeline providers once per request ([5ae2e5f](https://github.com/bustanhq/bustan/commit/5ae2e5fef35d51b629a625a7f9899af4fccdf36f))
* **platform:** let a controller carry a framework hook without decorating it ([cea97e3](https://github.com/bustanhq/bustan/commit/cea97e3795f8f44bd9650fb715444dc1b9ea9763))
* **platform:** let a controller carry a framework hook without decorating it ([dd5d33a](https://github.com/bustanhq/bustan/commit/dd5d33a9f4540c4ed93ac6a9b879f0452a2a56cb))
* resolve four critical defects found in the PR [#19](https://github.com/bustanhq/bustan/issues/19) review ([91d9554](https://github.com/bustanhq/bustan/commit/91d95543ad34d4c262e80ddebc7a1bc818ea2033))
* **security:** stop controller-level Public from bypassing handler auth ([565ac6e](https://github.com/bustanhq/bustan/commit/565ac6ec0f23a699f338f74e643bd5c393d9eef1))
* **skills:** refuse an Owns list that did not parse into paths ([8417083](https://github.com/bustanhq/bustan/commit/8417083da57f08e99b8b3c4d58824f1b37654a97))
* **testing:** drive the application lifecycle instead of re-implementing it ([2996c10](https://github.com/bustanhq/bustan/commit/2996c103e127378279c8a38f9fff8c2d193c40a7))
* **testing:** find a replacement's declaring module by token identity ([f1047a5](https://github.com/bustanhq/bustan/commit/f1047a5ef4c917e22d31e54f7deb5f9b9904e41a))


### Documentation

* **audit:** add DI container adversarial audit report, evidence and roadmap ([c65fae7](https://github.com/bustanhq/bustan/commit/c65fae7f073e19f80b6f5b02e23dda35945d7df2))
* **delivery:** add the Bustan 2.0 seven-day delivery backlog ([3ab7800](https://github.com/bustanhq/bustan/commit/3ab7800550987789a8193508f351d994fb114208))
* **delivery:** gate the layout move on rc.2 and on a passing layering check ([4f5d510](https://github.com/bustanhq/bustan/commit/4f5d5108d74be3255c4d500b9ec3d8e7d149ca4f))
* document every error class and the scope algebra the kernel enforces ([c78b242](https://github.com/bustanhq/bustan/commit/c78b242596dbfbcfac3424145055e48142b49202))
* make the troubleshooting and scope pages match the framework rc.1 ships ([6ade649](https://github.com/bustanhq/bustan/commit/6ade64910eb122f5af8d340563b08e0af51b29be))
* **module:** state what available_providers can and cannot answer ([073670f](https://github.com/bustanhq/bustan/commit/073670f592b48d829650f85ac876018b1918d9d9))
* **module:** state what available_providers can and cannot answer ([895005a](https://github.com/bustanhq/bustan/commit/895005a12af0ae319149ce4646fa05dd3214ce50)), closes [#77](https://github.com/bustanhq/bustan/issues/77)
* **readme:** name create_testing_module in the supported imports example ([7f98a76](https://github.com/bustanhq/bustan/commit/7f98a76ba947370034d89aebc7af07c211127492))
* **readme:** point the testing section at the supported override path ([217a5ba](https://github.com/bustanhq/bustan/commit/217a5babe98f242b2c8fc5d48dd4b4024b657456))
* refresh api reference ([a879393](https://github.com/bustanhq/bustan/commit/a879393d725bd51d59fb679bf6f212d3a8603a07))
* **skills:** add the delivery supervisor skill ([59de97a](https://github.com/bustanhq/bustan/commit/59de97a559dbba97984f9b5d0afbdb2196760e43))
* **skills:** amend Owns in the issue body, not in a comment ([1391929](https://github.com/bustanhq/bustan/commit/13919290981e5b4eda7b58879af81140137cdddd))
* **skills:** check each acceptance criterion against the Owns list before dispatch ([9e77f2c](https://github.com/bustanhq/bustan/commit/9e77f2ceb16eac82efe6a642a2db6b7342e8616b))
* **skills:** do not carry a CI diagnosis from one branch to another ([043377f](https://github.com/bustanhq/bustan/commit/043377faa2a0d748528ff49a9a6451215316e40a))
* **skills:** do not schedule a check-in for a human go-ahead ([363794d](https://github.com/bustanhq/bustan/commit/363794dc1ebeb3d2d6f5e90015944e02beb1fb5d))
* **skills:** grep the suite for the string a ticket changes ([a5bf356](https://github.com/bustanhq/bustan/commit/a5bf3563a44fe95b14e3739a60eb1ef2219110bf))
* **skills:** how to judge a ticket that edited the acceptance gate ([c79b4a0](https://github.com/bustanhq/bustan/commit/c79b4a01810572dfecd49c0f72753044fa388c36))
* **skills:** record the two review constraints that cost a step today ([466d9d0](https://github.com/bustanhq/bustan/commit/466d9d0dc5b0173997d22cbe28fbd15cc7f54ec7))
* **skills:** record what cutting the first release taught ([03dceeb](https://github.com/bustanhq/bustan/commit/03dceeb16c30cb6a592f41001496558b67da8114))
* **skills:** sweep the repository root, not a list of directories ([f8d0d2e](https://github.com/bustanhq/bustan/commit/f8d0d2ee2bbaec0afcd83b00ff85e586f094daad))


### Code Refactoring

* **core:** retype the request boundary against the request contract ([b9aa1d6](https://github.com/bustanhq/bustan/commit/b9aa1d63cb92eb8d309c2985b2cc29cd34458c0f))
* **http:** narrow the adapter port to transport translation ([74dcc3a](https://github.com/bustanhq/bustan/commit/74dcc3ad3b5966cf822fbeb49ca54a50ebcd3664))

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
