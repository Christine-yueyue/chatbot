"""backend package marker for local imports.

This file makes the `backend` directory a Python package so scripts that
do `from backend import main` work when run from the repository root.
"""

__all__ = ["main"]
