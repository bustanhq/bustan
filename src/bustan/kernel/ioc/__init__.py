"""The container: what it is told about providers, what it plans, and what it resolves.

Nothing is re-exported here. Planning and execution are two subpackages because the
boundary between them is load-bearing - a plan is computed once while the application
boots and read on every request afterwards - and a name re-exported at this level
would be reachable from either side without saying which one it belongs to. The tokens
and the scope declarations are imported by their own module names for the same reason.
"""

__all__: tuple[str, ...] = ()
