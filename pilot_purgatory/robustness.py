"""Do the headline conclusions survive when the assumptions change?

Every scenario changes one thing about the world (applied equally to both organisations),
then re-runs the comparison and the single-fix ranking. If a conclusion only holds under
the baseline assumptions, it is an artefact of those assumptions, not an insight.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from typing import Dict, List, Optional

from .analysis import lever_effects
from .model import DEFAULT_ASSUMPTIONS, Assumptions, Strategy, simulate
from .strategies import GOVERNANCE, MOMENTUM


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    assumptions: Assumptions = DEFAULT_ASSUMPTIONS
    quarters: int = 12
    roi_hurdle: Optional[float] = None
    abandon_rate: Optional[float] = None

    def apply(self, strategy: Strategy) -> Strategy:
        changes = {}
        if self.roi_hurdle is not None:
            changes["roi_hurdle"] = self.roi_hurdle
        if self.abandon_rate is not None:
            changes["abandon_rate"] = self.abandon_rate
        return replace(strategy, **changes) if changes else strategy


SCENARIOS: List[Scenario] = [
    Scenario("Baseline", "The default assumptions"),
    Scenario("Fewer good ideas", "Typical pilot is worth about 30% less", Assumptions(value_median=250)),
    Scenario("More good ideas", "Typical pilot is worth about 40% more", Assumptions(value_median=500)),
    Scenario("Higher bar to scale", "Evidence must show 2x the scaling cost, not 1.5x", roi_hurdle=2.0),
    Scenario("Lower bar to scale", "Evidence need only show 1.2x the scaling cost", roi_hurdle=1.2),
    Scenario("Noisier evidence", "Measurement noise 60% higher", Assumptions(measurement_noise=1.6)),
    Scenario("Cleaner evidence", "Measurement noise halved", Assumptions(measurement_noise=0.5)),
    Scenario(
        "Costlier scaling",
        "Productionising costs roughly 50% more",
        Assumptions(scaling_cost_base=225, scaling_cost_per_complexity=975),
    ),
    Scenario("Impatient sponsors", "Drifting pilots lose their sponsor 10% of quarters, not 4%", abandon_rate=0.10),
    Scenario("Shorter horizon", "Judge results after 2 years, not 3", quarters=8),
    Scenario("Longer horizon", "Judge results after 4 years, not 3", quarters=16),
]


@dataclass(frozen=True)
class ScenarioResult:
    scenario: Scenario
    pilots_first_net: float
    strategy_first_net: float
    top_lever: str
    top_lever_gain: float

    @property
    def strategy_first_wins(self) -> bool:
        return self.strategy_first_net > self.pilots_first_net


@dataclass(frozen=True)
class RobustnessReport:
    results: List[ScenarioResult]

    @property
    def strategy_first_wins(self) -> int:
        return sum(r.strategy_first_wins for r in self.results)

    @property
    def top_lever_counts(self) -> Dict[str, int]:
        return dict(Counter(r.top_lever for r in self.results).most_common())


def run_robustness(
    runs: int = 200, seed: int = 42, scenarios: Optional[List[Scenario]] = None
) -> RobustnessReport:
    results = []
    for sc in scenarios or SCENARIOS:
        momentum, governance = sc.apply(MOMENTUM), sc.apply(GOVERNANCE)
        baseline, effects = lever_effects(momentum, runs, sc.quarters, seed, sc.assumptions)
        governed = simulate(governance, runs, sc.quarters, seed, sc.assumptions)
        results.append(
            ScenarioResult(
                scenario=sc,
                pilots_first_net=baseline.net_value.mean,
                strategy_first_net=governed.net_value.mean,
                top_lever=effects[0].lever,
                top_lever_gain=effects[0].net_value_change,
            )
        )
    return RobustnessReport(results)
