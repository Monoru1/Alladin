"""
Experimental protocol — Lot K1.

Pre-registration of objectives, metrics, thresholds, seeds, and
abandonment criteria before any OOS observation.
Isolated from the execution path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExperimentSpec:
    """
    Pre-registered experiment specification.

    Must be defined BEFORE observing any out-of-sample results.
    Changing the spec after OOS observation invalidates the experiment.
    """

    name: str
    primary_metric: str            # e.g. "expectancy_R_OOS_net"
    min_effect_size: float         # minimum meaningful improvement over baseline
    n_seeds: int                   # number of independent seeds to run
    seeds: list[int]               # explicit seed list (length == n_seeds)
    n_timesteps_per_trial: int     # spike train length per decision step
    abandonment_criteria: list[str]  # conditions under which to discard the experiment
    baseline_description: str      # description of the naive baseline to compare against
    notes: str = ""


@dataclass
class TrialResult:
    """
    Result of a single experimental trial (one seed, one condition).

    Negative results are valid and must be preserved.
    """

    experiment_name: str
    seed: int
    condition: str                 # e.g. "snn_lif", "baseline_naive", "snn_rstdp"
    primary_metric_value: float | None  # None = INCOMPLETE (missing data)
    n_trials: int
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExperimentReport:
    """Aggregated results across seeds for one condition."""

    experiment_name: str
    condition: str
    results: list[TrialResult]

    def metric_values(self) -> list[float]:
        return [r.primary_metric_value for r in self.results if r.primary_metric_value is not None]

    def mean(self) -> float | None:
        vals = self.metric_values()
        return sum(vals) / len(vals) if vals else None

    def n_complete(self) -> int:
        return len(self.metric_values())


def validate_spec(spec: ExperimentSpec) -> list[str]:
    """
    Validate an ExperimentSpec before running.

    Returns list of error messages (empty = valid).
    """
    errors: list[str] = []
    if not spec.name:
        errors.append("name is required")
    if spec.min_effect_size <= 0:
        errors.append("min_effect_size must be positive")
    if spec.n_seeds < 1:
        errors.append("n_seeds must be >= 1")
    if len(spec.seeds) != spec.n_seeds:
        errors.append(f"seeds length {len(spec.seeds)} != n_seeds {spec.n_seeds}")
    if len(set(spec.seeds)) != len(spec.seeds):
        errors.append("seeds must be unique")
    if spec.n_timesteps_per_trial < 1:
        errors.append("n_timesteps_per_trial must be >= 1")
    if not spec.abandonment_criteria:
        errors.append("at least one abandonment criterion is required")
    if not spec.baseline_description:
        errors.append("baseline_description is required")
    return errors


# Pre-registered K1 experiment spec
K1_EXPERIMENT = ExperimentSpec(
    name="K1_LIF_RSTDP_vs_NAIVE_BASELINE",
    primary_metric="mean_reward_per_episode",
    min_effect_size=0.05,
    n_seeds=5,
    seeds=[42, 137, 2718, 31415, 99991],
    n_timesteps_per_trial=20,
    abandonment_criteria=[
        "mean_reward_per_episode < 0 for all seeds after 100 episodes",
        "weight variance collapses to < 1e-6 (saturation)",
        "spike rate drops to 0 for all neurons for > 10 consecutive timesteps",
    ],
    baseline_description=(
        "Naive baseline: always predict the sign of the last observed return. "
        "Same features, same reward signal, no learning."
    ),
    notes=(
        "K1 uses synthetic OHLCV-like features from deterministic fixtures. "
        "OOS evaluation deferred to K2 once real causal data is available. "
        "Negative results are acceptable and must be preserved."
    ),
)
