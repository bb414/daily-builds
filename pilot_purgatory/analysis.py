"""Which single governance practice does the most for a pilots-first organisation?"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from .model import DEFAULT_ASSUMPTIONS, PURGATORY, SCALED, Assumptions, Strategy, Summary, simulate
from .strategies import LEVERS


@dataclass(frozen=True)
class LeverEffect:
    lever: str
    net_value_change: float  # GBP k, mean across runs
    scaled_change: float  # percentage points of pilots scaled
    purgatory_change: float  # percentage points of pilots stuck in purgatory


def lever_effects(
    base: Strategy,
    runs: int = 500,
    quarters: int = 12,
    seed: int = 42,
    assumptions: Assumptions = DEFAULT_ASSUMPTIONS,
) -> Tuple[Summary, List[LeverEffect]]:
    """Apply each lever on its own to the base strategy and measure the change."""
    baseline = simulate(base, runs, quarters, seed, assumptions)
    effects = []
    for name, apply in LEVERS.items():
        changed = simulate(apply(base), runs, quarters, seed, assumptions)
        effects.append(
            LeverEffect(
                lever=name,
                net_value_change=changed.net_value.mean - baseline.net_value.mean,
                scaled_change=100 * (changed.outcome_share[SCALED] - baseline.outcome_share[SCALED]),
                purgatory_change=100 * (changed.outcome_share[PURGATORY] - baseline.outcome_share[PURGATORY]),
            )
        )
    effects.sort(key=lambda e: e.net_value_change, reverse=True)
    return baseline, effects
