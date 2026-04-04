# Comparisons

`star` is easiest to evaluate when you place it next to the tools it overlaps with.

## `star` Vs Starlette

- Choose Starlette when you want a minimal ASGI toolkit and prefer assembling architecture yourself.
- Choose `star` when you still want Starlette underneath but want modules, DI-managed providers, lifecycle hooks, and a request pipeline as first-class patterns.

## `star` Vs FastAPI

- Choose FastAPI when schema-first API tooling, automatic OpenAPI generation, and request/response model ergonomics are the primary goal.
- Choose `star` when the main problem is application structure, explicit module boundaries, and NestJS-style composition on top of Starlette.

## `star` Vs NestJS

- Choose NestJS when the team is already in the TypeScript and Node.js ecosystem.
- Choose `star` when you want a similar architectural model in Python while staying close to ASGI and Starlette.

## What `star` Is Optimizing For

- explicit module boundaries
- constructor injection for providers and controllers
- request-local dependencies without global state
- predictable cross-cutting hooks through guards, pipes, interceptors, and filters
- direct escape hatches back to Starlette when needed