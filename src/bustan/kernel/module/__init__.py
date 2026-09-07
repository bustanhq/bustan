"""Module declarations, the graph they form, and the compiler that validates it.

Nothing is re-exported here. The names an application uses - the module decorators,
the dynamic module type and the configurable module builder - are re-exported by the
root ``bustan`` package, and the graph and the compiler are framework-internal and are
imported by their own module names. Lifting either set to this level would put a
second spelling on the public ones and a first one on the internal ones.
"""

__all__: tuple[str, ...] = ()
