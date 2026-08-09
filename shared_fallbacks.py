"""
shared_fallbacks.py - Fallback chain system for CoAgent operations.
Each operation has a chain of methods, tried in order.
"""

import logging


class FallbackChain:
    """Try multiple methods in order until one succeeds."""

    def __init__(self, name: str):
        self.name = name
        self.methods = []
        self.last_success = None

    def add_method(self, name: str, fn, *args, **kwargs):
        self.methods.append({"name": name, "fn": fn, "args": args, "kwargs": kwargs})
        return self

    def execute(self, fallback_on_none=True):
        """Try each method in order. Return first non-None result.

        When fallback_on_none=True (default): returns the first non-None
        result, skipping None results. If all methods return None, raises
        RuntimeError.

        When fallback_on_none=False: returns the first result regardless
        of value (including None), treating any non-exception return as
        success. Use this when None is a valid result from a method.
        """
        errors = []
        none_results = []
        for method in self.methods:
            try:
                result = method["fn"](*method["args"], **method["kwargs"])
            except Exception as e:
                errors.append(f"{method['name']}: {e}")
                logging.debug("Fallback method failed: %s/%s", self.name, method["name"], exc_info=True)
                continue
            if fallback_on_none:
                if result is not None:
                    self.last_success = method["name"]
                    return result
                none_results.append(method["name"])
            else:
                self.last_success = method["name"]
                return result
        parts = errors + [f"{n}: returned None" for n in none_results]
        raise RuntimeError(
            f"All methods exhausted for {self.name}: {'; '.join(parts)}"
        )

    def report(self):
        return {
            "name": self.name,
            "last_success": self.last_success,
            "methods": [m["name"] for m in self.methods],
        }
