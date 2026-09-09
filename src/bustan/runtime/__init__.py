"""The transport-neutral HTTP runtime: route compilation, dispatch and adapter support.

Nothing is re-exported here. This package is what an adapter is written against, and
an adapter that reached it through one re-exporting namespace would be coupled to the
whole of it rather than to the module it actually needs. The versioning options an
application configures are re-exported by the root ``bustan`` package.

The suite that certifies an adapter is not here. It drives adapters and assembles
applications through the bootstrap, so it sits above this package rather than inside
it, and it is imported as ``bustan.conformance``.
"""

__all__: tuple[str, ...] = ()
