"""Attribute-accessible dictionaries keep the original model's field names readable."""
from __future__ import annotations

import copy
import math


class Record(dict):
    # A record is still JSON-compatible mapping data, while agent.x is convenient
    # for translated policy formulas. Dictionary method names remain ordinary methods.
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as error:
            # AttributeError preserves normal getattr(..., default)/hasattr behavior.
            raise AttributeError(name) from error

    def __setattr__(self, name, value):
        # Attribute assignments and dictionary assignments update the same state.
        self[name] = value


def record(value):
    # Recursively convert nested mappings/lists and copy leaves. Callers can
    # edit an input world or exported data without aliasing the engine's config.
    if isinstance(value, dict):
        return Record((key, record(item)) for key, item in value.items())
    if isinstance(value, list):
        return [record(item) for item in value]
    return copy.deepcopy(value)


def finite(value):
    # JavaScript Number.isFinite does not coerce strings, booleans, or null.
    return type(value) in (int, float) and math.isfinite(value)
