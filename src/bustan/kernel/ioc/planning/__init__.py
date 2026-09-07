"""Bootstrap-time planning of how providers are constructed.

Nothing in this package may reach runtime state: a planner is given a class and a
description of what is visible to it, and returns a plan or raises. Keeping the two
apart is what lets a plan be computed once at startup instead of on every request.

Nothing is re-exported here either. A planner is imported by its own module name, so
that the rule above stays visible at the import site rather than only in this file.
"""

__all__: tuple[str, ...] = ()
