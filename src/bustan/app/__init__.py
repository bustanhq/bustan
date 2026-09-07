"""Assembly of a running application from a compiled module graph.

Nothing is re-exported here. The four names this package offers the world outside it -
``Application`` and ``ApplicationContext`` from ``application``, ``create_app`` and
``create_app_context`` from ``bootstrap`` - are already re-exported by the root
``bustan`` package, which is where an application author is meant to find them. Naming
them again here would give each of them a second supported spelling with nothing to
say which one is meant, and would make importing the lifespan integration pull the
whole bootstrap in behind it.
"""

__all__: tuple[str, ...] = ()
