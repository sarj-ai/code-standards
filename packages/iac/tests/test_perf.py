"""Performance regression test.

Two guards, both run over a large synthetic HCL file:

* an absolute backstop — no rule may blow a generous ms/1k-LOC ceiling, catching a
  catastrophic slowdown regardless of hardware;
* a relative outlier gate — no single rule may take more than 10x the median rule
  time. This is hardware-independent and is what catches an algorithmic regression
  (e.g. a rule going quadratic) that an absolute, machine-dependent budget would miss
  on a fast laptop but hit on slow CI.

The documented target is < 50 ms / 1k LOC per rule; the relative gate enforces it in
spirit without flaking across machines.
"""

from __future__ import annotations

from pathlib import Path
import time

from sarj_iac_lint.rules import REGISTRY


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
_RELATIVE_OUTLIER_FACTOR = 10.0
_RELATIVE_SLACK_S = 0.003


def _best_time_s(rule_id: str, path: Path, source: str, repeats: int = 5) -> float:
    rule = REGISTRY[rule_id]()
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        _ = rule.check(path, source)
        best = min(best, time.perf_counter() - start)
    return best


def test_no_rule_exceeds_absolute_budget() -> None:
    path = Path("synthetic.tf")
    loc = _SYNTHETIC_HCL.count("\n") + 1
    for rule_id in sorted(REGISTRY):
        seconds = _best_time_s(rule_id, path, _SYNTHETIC_HCL)
        ms_per_kloc = seconds / loc * 1_000_000
        assert ms_per_kloc < _ABSOLUTE_MS_PER_KLOC, (
            f"{rule_id}: {ms_per_kloc:.1f} ms/1k LOC exceeds {_ABSOLUTE_MS_PER_KLOC} ms budget"
        )


def test_no_rule_is_algorithmic_outlier() -> None:
    path = Path("synthetic.tf")
    timings = {rid: _best_time_s(rid, path, _SYNTHETIC_HCL) for rid in REGISTRY}
    ordered = sorted(timings.values())
    median = ordered[len(ordered) // 2]
    ceiling = median * _RELATIVE_OUTLIER_FACTOR + _RELATIVE_SLACK_S
    slow = {rid: t for rid, t in timings.items() if t > ceiling}
    assert not slow, (
        "rule(s) more than "
        f"{_RELATIVE_OUTLIER_FACTOR:.0f}x the median ({median * 1000:.2f} ms) — likely an "
        f"algorithmic regression: { {k: f'{v * 1000:.2f}ms' for k, v in slow.items()} }"
    )
