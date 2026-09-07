"""The transport-neutral HTTP runtime: route compilation, dispatch and adapter support.

Nothing is re-exported here. This package is what an adapter is written against, and
an adapter that reached it through one re-exporting namespace would be coupled to the
whole of it rather than to the module it actually needs; the conformance suite that
certifies adapters is imported by its own name for exactly that reason. The versioning
options an application configures are re-exported by the root ``bustan`` package.
"""

__all__: tuple[str, ...] = ()
