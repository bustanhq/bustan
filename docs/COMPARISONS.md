# Comparisons

`bustan` is easiest to evaluate when you place it next to the tools it overlaps with.

## `bustan` Vs Starlette

- Choose Starlette when you want a minimal ASGI toolkit and prefer assembling architecture yourself.
- Choose `bustan` when you still want Starlette underneath but want modules, DI-managed providers, lifecycle hooks, and a request pipeline as first-class patterns.

## `bustan` Vs FastAPI

- Choose FastAPI when schema-first API tooling, automatic OpenAPI generation, and request/response model ergonomics are the primary goal.
- Choose `bustan` when the main problem is application structure, explicit module boundaries, and NestJS-style composition on top of Starlette.

## `bustan` Vs NestJS

- Choose NestJS when the team is already in the TypeScript and Node.js ecosystem.
- Choose `bustan` when you want a similar architectural model in Python while staying close to ASGI and Starlette.

## What `bustan` Is Optimizing For

- explicit module boundaries
- constructor injection for providers and controllers
- request-local dependencies without global state
- predictable cross-cutting hooks through guards, pipes, interceptors, and filters
- direct escape hatches back to Starlette when needed