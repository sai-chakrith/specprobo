"""Finite boundary witnesses for conjunctive, typed diagnostic conditions."""

import math
from collections import defaultdict
from typing import Any

from .schema import Precondition


def holds(condition: Precondition, actual: object) -> bool:
    if actual is None:
        return False
    value = condition.value
    if isinstance(value, bool) and not isinstance(actual, bool):
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return False
    if isinstance(value, str) and not isinstance(actual, str):
        return False
    if condition.op == "==":
        return actual == value
    if condition.op == "!=":
        return actual != value
    if isinstance(actual, bool) or isinstance(value, bool):
        return False
    if not isinstance(actual, (int, float)) or not isinstance(value, (int, float)):
        return False
    return {
        "<": actual < value,
        "<=": actual <= value,
        ">": actual > value,
        ">=": actual >= value,
    }.get(condition.op or "", False)


def candidates(conditions: list[Precondition]) -> list[Any]:
    values = [c.value for c in conditions]
    if all(isinstance(v, bool) for v in values):
        return [False, True]
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        numbers = sorted(set(float(v) for v in values if isinstance(v, (int, float))))
        result = list(numbers)
        for number in numbers:
            result.extend(
                [
                    number - 1,
                    number + 1,
                    math.nextafter(number, -math.inf),
                    math.nextafter(number, math.inf),
                ]
            )
        result.extend((a + b) / 2 for a, b in zip(numbers, numbers[1:], strict=False))
        return result
    if all(isinstance(v, str) for v in values):
        return [*values, "__different_value__"]
    raise ValueError("Mixed or unresolved condition value types")


def environment(conditions: list[Precondition], truth: bool = True) -> dict[str, object]:
    groups: dict[str, list[Precondition]] = defaultdict(list)
    for condition in conditions:
        if condition.kind not in {"signal", "timing"} or not condition.signal:
            continue
        groups[condition.signal].append(condition)
    values: dict[str, object] = {}
    for signal, group in groups.items():
        options = [v for v in candidates(group) if all(holds(c, v) for c in group)]
        if not options:
            raise ValueError(f"Contradictory conditions for {signal}")
        values[signal] = options[0]
    if not truth:
        for signal, group in groups.items():
            options = [v for v in candidates(group) if not all(holds(c, v) for c in group)]
            if options:
                values[signal] = options[0]
                return values
        if groups:
            raise ValueError("No violating environment exists")
    return values


def targeted_negatives(conditions: list[Precondition]) -> list[tuple[int, dict[str, object]]]:
    """Violate one conjunct while holding every other conjunct true, when feasible."""
    baseline = environment(conditions)
    results = []
    for index, condition in enumerate(conditions):
        if condition.kind not in {"signal", "timing"} or not condition.signal:
            continue
        peers = [c for i, c in enumerate(conditions) if i != index and c.signal == condition.signal]
        choices = [
            v
            for v in candidates([condition, *peers])
            if not holds(condition, v) and all(holds(c, v) for c in peers)
        ]
        if choices:
            results.append((index, {**baseline, condition.signal: choices[0]}))
    return results
