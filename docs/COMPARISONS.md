# Comparisons

`Bustan` is most effective when evaluated alongside the frameworks it integrates with or is inspired by.

## `Bustan` Vs Starlette

- Choose Starlette when you want a minimal ASGI toolkit and prefer assembling architecture yourself.
- Choose `Bustan` when you want a structured application engine (modules, DI, lifecycle hooks) that uses Starlette as its high-performance execution driver.

## `Bustan` Vs FastAPI

- Choose FastAPI when schema-first API tooling, automatic OpenAPI generation, and request/response model ergonomics are the primary goals.
- Choose `Bustan` when the primary challenge is managing complex application structure, explicit module boundaries, and decoupled service layers.

## `Bustan` Vs Litestar

- Choose Litestar when you want a feature-rich, high-performance ASGI framework with extensive built-in plugins.
- Choose `Bustan` when you want a rigorous architectural pattern (inspired by NestJS) and cross-platform flexibility; while currently defaulting to Starlette, a Litestar adapter is a future planned integration point.

## What `Bustan` Is Optimizing For

- **Explicit Module Boundaries**: Encapsulate related functionality and explicitly declare imports and exports.
- **Constructor Injection**: Use class-based provider and controller injection for better testability and type safety.
- **Request-Local State**: Manage dependencies that exist only for the life of an incoming request without global state.
- **Predictable Request Pipeline**: Apply guards, pipes, interceptors, and filters in a fixed, documented execution order.
- **Platform Integration**: Maintain direct access to the underlying engine's features (e.g., Starlette middleware or mounts) through standardized accessors.