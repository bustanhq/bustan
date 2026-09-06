"""Bootstrap-time planning of how providers are constructed.

Nothing in this package may reach runtime state: a planner is given a class and a
description of what is visible to it, and returns a plan or raises. Keeping the two
apart is what lets a plan be computed once at startup instead of on every request.
"""
