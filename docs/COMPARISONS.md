# Comparisons

`Bustan` is easiest to evaluate when you frame it as an architecture layer rather than as a "more convenient Starlette" or a direct FastAPI clone.

## `Bustan` Vs Starlette

- Choose Starlette when you want a minimal ASGI toolkit and you prefer to assemble architecture yourself.
- Choose `Bustan` when the main problem is keeping a growing app organized with explicit modules, DI-managed services, lifecycle stages, and a predictable request pipeline.

Starlette remains the default execution engine under the hood. Bustan adds structure, not a competing transport stack.

## `Bustan` Vs FastAPI

- Choose FastAPI when schema-first API ergonomics, automatic docs, and request/response model convenience are the primary goals.
- Choose `Bustan` when the main problem is application composition, module boundaries, provider visibility, and scaling service wiring over time.

FastAPI optimizes around endpoint ergonomics. Bustan optimizes around architecture and runtime composition.

## `Bustan` Vs NestJS

- Choose NestJS when you want the same architectural ideas in the TypeScript ecosystem.
- Choose `Bustan` when you want that module-and-provider style in Python while keeping direct access to an ASGI platform.

Bustan borrows the module, provider, lifecycle, and pipeline ideas, but it stays Python-native in typing, runtime, and framework integration.

## What Bustan Is Optimizing For

- explicit module boundaries through `imports`, `providers`, `controllers`, and `exports`
- constructor injection for controllers and providers
- request-local state without global mutable context
- predictable request-time execution through guards, pipes, interceptors, and filters
- runtime inspection through route snapshots and discovery helpers
- direct platform access instead of hiding Starlette behind an opaque abstraction