"""Transport adapters that bind the framework's HTTP runtime to a server library.

Nothing is re-exported here, so importing the framework never imports an adapter, and
an adapter's own dependency stays optional to everyone who does not name it.
"""

__all__: tuple[str, ...] = ()
