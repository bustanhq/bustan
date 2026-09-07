"""The ``bustan`` command line tool and the project scaffolding it performs.

Nothing is re-exported here. The tool is reached by running the installed console
script, which names the entry point module directly, and argument parsing, the
commands and the work those commands delegate to are separate modules precisely so
that none of them has to be imported to reach another. Keeping this package empty is
what stops importing the framework from importing its command line.
"""

__all__: tuple[str, ...] = ()
