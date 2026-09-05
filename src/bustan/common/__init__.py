"""Definitions shared by more than one layer of the framework.

Nothing is re-exported here on purpose. The modules below are imported by their own
names (``bustan.common.types``, ``bustan.common.constants``,
``bustan.common.decorators``) so that importing any one of them never drags the others
in, and so that this package cannot quietly become a second public surface.
"""

__all__: tuple[str, ...] = ()
