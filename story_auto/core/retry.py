"""Bounded, testable retry primitive for future provider boundaries."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class RetryExhaustedError(RuntimeError): pass


def retry(operation: Callable[[], T], *, attempts: int = 3, base_delay_seconds: float = 0.1,
          max_delay_seconds: float = 1.0, retryable: Callable[[Exception], bool] = lambda _: True,
          sleep: Callable[[float], None] = lambda _: None) -> T:
    if attempts < 1 or base_delay_seconds < 0 or max_delay_seconds < base_delay_seconds:
        raise ValueError("invalid bounded retry configuration")
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as error:
            if attempt + 1 >= attempts or not retryable(error):
                raise
            sleep(min(max_delay_seconds, base_delay_seconds * (2 ** attempt)))
    raise RetryExhaustedError("unreachable")
