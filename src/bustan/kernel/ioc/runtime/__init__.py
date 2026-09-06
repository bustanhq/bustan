"""Execution of the plan the container computed while it was booting.

Nothing here reads a signature, evaluates an annotation or synthesizes a namespace:
by the time this package runs, every question about a class has an answer recorded in
its plan. What is left is looking a value up in a cache, or building it.
"""
