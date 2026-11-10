"""Opt-in low-overhead timing records for large-World performance work."""
from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager

ENABLED = os.environ.get("PYBROWSER_PROFILE", "").strip().casefold() not in {"", "0", "false", "no"}


def log(event: str, **fields) -> None:
    if not ENABLED:
        return
    values = " ".join(f"{name}={value}" for name, value in fields.items())
    print(f"PYBROWSER_PROFILE event={event} {values}".rstrip(), file=sys.stderr, flush=True)


@contextmanager
def timed(event: str, **fields):
    if not ENABLED:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        log(event, elapsed_ms=f"{(time.perf_counter() - started) * 1000:.1f}", **fields)
