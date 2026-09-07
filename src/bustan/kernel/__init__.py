"""Injection, module composition and lifecycle: what the framework is built out of.

Nothing is re-exported here. Every layer above this one may import the kernel, so a
name lifted to this level is reachable from everywhere at once, and the shape of the
package would then be an argument that applications may depend on it. They may not:
the supported spelling of the exception types is ``bustan.errors``, and everything
else here is framework-internal and is imported by its own module name.
"""

__all__: tuple[str, ...] = ()
