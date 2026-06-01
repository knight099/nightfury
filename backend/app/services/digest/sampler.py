from typing import Sequence, TypeVar

T = TypeVar("T")


def sample_evenly(items: Sequence[T], cap: int) -> list[T]:
    """Return up to `cap` items, evenly spaced across `items`, preserving order.

    If len(items) <= cap, returns a list copy of items unchanged.
    First and last elements are always preserved when cap >= 2.
    """
    n = len(items)
    if n == 0 or cap <= 0:
        return []
    if n <= cap:
        return list(items)
    if cap == 1:
        return [items[0]]

    step = (n - 1) / (cap - 1)
    indices = [round(i * step) for i in range(cap)]
    return [items[i] for i in indices]
