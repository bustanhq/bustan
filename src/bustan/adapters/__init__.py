"""Transport adapters that bind the framework's HTTP runtime to a server library.

Nothing is re-exported here, so importing the framework never imports an adapter, and
an adapter's own dependency stays optional to everyone who does not name it. This is
the only part of the package allowed to import a web server.
"""

__all__: tuple[str, ...] = ()
