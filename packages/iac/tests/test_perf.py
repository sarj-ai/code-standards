from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import TYPE_CHECKING

import pytest

from sarj_iac_lint.rules import REGISTRY


if TYPE_CHECKING:
    from collections.abc import Callable


_RESOURCE_BLOCK = """\
# resource block {i}
resource "google_sql_database_instance" "db_{i}" {{
  name             = "db-{i}"
  database_version = "POSTGRES_16"
  region           = "us-central1"
  deletion_protection = true
  settings {{
    tier = "db-custom-2-7680"
    ip_configuration {{
      ipv4_enabled    = false
      private_network = "projects/x/global/networks/vpc-{i}"
    }}
  }}
  user_labels = {{
    env  = "prod"
    team = "data"
  }}
}}

variable "cidr_{i}" {{
  description = "allowed range for service {i}"
  default     = "10.{i}.0.0/16"
}}
"""

_SYNTHETIC_HCL = "\n".join(_RESOURCE_BLOCK.format(i=i) for i in range(80))

_ABSOLUTE_MS_PER_KLOC = 200.0
_GROWTH_INPUT_FACTOR = 4
_GROWTH_BUDGET = 8.0
_GROWTH_SLACK_S = 0.003
_GROWTH_HCL = "\n".join(_RESOURCE_BLOCK.format(i=i) for i in range(80 * _GROWTH_INPUT_FACTOR))


@dataclass(frozen=True)
class _GrowthTimes:
    base: float
    large: float


def _best_time_s(rule_id: str, path: Path, source: str, repeats: int = 5) -> float:
    rule = REGISTRY[rule_id]()
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        rule.check(path, source)
        best = min(best, time.perf_counter() - start)
    return best


@pytest.fixture(scope="module")
def rule_timings() -> dict[str, float]:
    path = Path("synthetic.tf")
    return {rid: _best_time_s(rid, path, _SYNTHETIC_HCL) for rid in sorted(REGISTRY)}


def test_no_rule_exceeds_absolute_budget(rule_timings: dict[str, float]) -> None:
    loc = _SYNTHETIC_HCL.count("\n") + 1
    for rule_id, seconds in rule_timings.items():
        ms_per_kloc = seconds / loc * 1_000_000
        assert ms_per_kloc < _ABSOLUTE_MS_PER_KLOC, (
            f"{rule_id}: {ms_per_kloc:.1f} ms/1k LOC exceeds {_ABSOLUTE_MS_PER_KLOC} ms budget"
        )


def _best_cpu_time_s(check: Callable[[Path, str], object], source: str) -> float:
    path = Path("synthetic.tf")
    check(path, source)
    best = float("inf")
    for _ in range(5):
        start = time.process_time()
        check(path, source)
        best = min(best, time.process_time() - start)
    return best


def _warm_growth_times(check: Callable[[Path, str], object]) -> _GrowthTimes:
    # Native parser caches and repeated checks are warm; this is not cold-parser coverage.
    return _GrowthTimes(base=_best_cpu_time_s(check, _SYNTHETIC_HCL), large=_best_cpu_time_s(check, _GROWTH_HCL))


def _exceeds_growth_budget(base: float, large: float) -> bool:
    # Retain the previous gate's 3ms margin for small measurements.
    return large > base * _GROWTH_BUDGET + _GROWTH_SLACK_S


def test_no_rule_exceeds_warm_growth_budget() -> None:
    timings = {rid: _warm_growth_times(REGISTRY[rid]().check) for rid in sorted(REGISTRY)}
    slow = {rid: timing for rid, timing in timings.items() if _exceeds_growth_budget(timing.base, timing.large)}
    assert not slow, f"Warm CPU growth exceeds {_GROWTH_BUDGET:g}x for {_GROWTH_INPUT_FACTOR}x input: {slow}"


@pytest.mark.parametrize("quadratic", [False, True])
def test_warm_growth_gate_distinguishes_linear_and_quadratic_work(quadratic: bool) -> None:
    def check(_path: Path, source: str) -> int:
        blocks = source.count('resource "') * 8
        width = blocks if quadratic else 1
        total = 0
        for left in range(blocks):
            for right in range(width):
                total += left + right
        return total

    timing = _warm_growth_times(check)
    if quadratic:
        assert timing.base > _GROWTH_SLACK_S, "Quadratic control must exceed the additive margin"
    assert _exceeds_growth_budget(timing.base, timing.large) is quadratic
