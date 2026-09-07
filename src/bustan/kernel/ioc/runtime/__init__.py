"""Execution of the plan the container computed while it was booting.

Nothing here reads a signature, evaluates an annotation or synthesizes a namespace:
by the time this package runs, every question about a class has an answer recorded in
its plan. What is left is looking a value up in a cache, or building it.

Nothing is re-exported here either. The resolution kernel and the steps it runs are
imported by their own module names, so that the split above stays visible at the
import site rather than only in this file.
"""

__all__: tuple[str, ...] = ()
