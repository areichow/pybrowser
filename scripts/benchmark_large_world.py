"""Generate and measure deterministic PyBrowser benchmark Worlds.

Example:
  py -3.14 scripts/benchmark_large_world.py --root C:\\temp\\pybrowser-bench --modules 2941
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import time
from pathlib import Path

from pybrowser.index_worker import index_module
from pybrowser.project import discover_modules


def module_source(index: int) -> str:
    return f'''"""Generated benchmark module {index}."""
import os

CONSTANT_{index} = {index}

class Service{index}:
    def __init__(self, value={index}):
        self.value = value

    def calculate(self, factor=2):
        result = self.value * factor
        return result

def helper_{index}(value):
    return Service{index}(value).calculate()
'''


def generate(root: Path, count: int) -> None:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for index in range(count):
        package = root / f"pkg_{index // 100:03d}"
        package.mkdir(exist_ok=True)
        if not (package / "__init__.py").exists():
            (package / "__init__.py").write_text("", encoding="utf-8", newline="\n")
        (package / f"module_{index:05d}.py").write_text(
            module_source(index), encoding="utf-8", newline="\n")


def elapsed_ms(action):
    started = time.perf_counter(); value = action()
    return value, (time.perf_counter() - started) * 1000


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--modules", type=int, default=2941)
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()
    generate(args.root, args.modules)
    entries, discovery = elapsed_ms(lambda: discover_modules(args.root))
    target = entries[len(entries) // 2].path
    timings = []
    for _ in range(args.samples):
        _result, duration = elapsed_ms(lambda: index_module(str(target)))
        timings.append(duration)
    print(json.dumps({
        "root": str(args.root.resolve()),
        "requested_modules": args.modules,
        "discovered_modules": len(entries),
        "discovery_ms": round(discovery, 1),
        "single_module_index_ms_median": round(statistics.median(timings), 1),
        "single_module_index_ms_samples": [round(value, 1) for value in timings],
    }, indent=2))


if __name__ == "__main__":
    main()
