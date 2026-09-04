# Repro harness for the 1.1 line

This directory is the objective gate for the 1.1.1 security patch. It holds one script
per defect that has been **demonstrated against the released 1.1.0 tree**, and a runner
that reports each one as `REPRODUCED`, `FIXED` or `ERROR`.

Run it with:

```bash
uv run python docs/audits/di-container-2026-09/run_repros.py
```

Add `--expect-fixed` to turn it into a regression gate that exits non-zero unless every
script reports `FIXED`. That is the acceptance criterion for the patch.

## Why this set is smaller than the one on the main line

The audit these findings come from was performed against the development line, which is
41 commits ahead of the released version and differs substantially inside the injection
kernel. Each finding was re-checked here against the released tree, and only those that
actually reproduce on it are included. The rest were either absent from the released
version or exercise an interface that does not exist on it, and carrying them into a
patch release would have meant fixing code that users are not running.

## What each script demonstrates

| Script | What an untrusted caller gets |
| --- | --- |
| `RI-01_default_scope_controller_leaks_identity.py` | A controller with no declared scope that injects a request-scoped provider is cached as a process-wide singleton, so the first caller's identity is served to every later caller. |
| `RI-02_use_class_dict_downgrades_declared_scope.py` | Binding a request-scoped class under an interface token with a `use_class` dict silently registers it as a singleton. |
| `RI-03_singleton_may_capture_durable_instance.py` | The scope guard rejects only request-scoped dependencies, so a singleton may capture and retain a tenant-keyed durable instance. |
| `RI-04_durable_provider_retains_first_callers_request.py` | A durable provider may inject the request and keeps it for the life of the partition, exposing the first caller's headers to everyone routed there. |
| `RI-10_durable_controller_shared_across_tenants.py` | A durable-scoped controller falls through to the singleton path, so one instance is shared across every tenant partition it was meant to separate. |
| `CR-01_durable_store_grows_without_bound.py` | The durable instance store has no eviction, so varying one header allocates one retained instance per distinct value. |
| `CR-06_durable_locks_never_released.py` | The per-partition construction locks are never released, so the lock table grows in lockstep with the store. |

Scripts print a single machine-readable line of the form
`RESULT: <finding-id> REPRODUCED|FIXED|ERROR - <message>`, which is what the runner
parses. Keep that contract when you change one.
