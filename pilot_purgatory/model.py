"""Core Monte Carlo model: how a portfolio of AI pilots moves (or fails to move) to scale.

Every quantity here is an illustrative assumption, not calibrated data. The point of the
model is to make the mechanics of "pilot purgatory" explicit and comparable, so that the
effect of different organisational choices can be explored, not to forecast real outcomes.

Money is in thousands of pounds (GBP k). Time is in quarters.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

# The reasons a pilot never reaches scale. The first four are the barriers most often
# reported by executives in qualitative work on AI scaling; the fifth captures pilots
# that were worth scaling but had no owner, budget or capacity to get there.
UNCLEAR_ROI = "Unclear ROI"
HARD_TO_MEASURE = "Hard-to-measure benefits"
TECH_COMPLEXITY = "Technical complexity"
LONG_TIMESCALES = "Long timescales"
NO_ROUTE = "No route to scale"
BARRIERS = (UNCLEAR_ROI, HARD_TO_MEASURE, TECH_COMPLEXITY, LONG_TIMESCALES, NO_ROUTE)

SCALED = "Scaled"
KILLED = "Stopped"
PURGATORY = "Pilot purgatory"
OUTCOMES = (SCALED, KILLED, PURGATORY)

# Model constants (assumptions, deliberately simple and easy to change).
SCALING_COST_BASE = 150.0  # one-off cost to productionise the simplest pilot
SCALING_COST_PER_COMPLEXITY = 650.0  # extra cost for the most complex pilot
METRICS_UPFRONT_BOOST = 0.3  # gain in measurability when success metrics are agreed first
KILL_GRACE_QUARTERS = 2  # quarters after first evidence before a kill rule bites
REFERENCE_COMPLEXITY = 0.5  # "average" complexity used to test whether complexity was binding


@dataclass(frozen=True)
class Strategy:
    """How an organisation runs its AI pilot portfolio."""

    name: str
    pilots: int = 20
    screening: float = 0.0  # share of candidate ideas screened out at intake (0 to 0.9)
    metrics_upfront: bool = False  # success metrics agreed before each pilot starts
    strategy_quarter: int = 5  # first quarter in which a strategy and scaling owner exist
    scaling_capacity: int = 1  # pilots that can be moved to production per quarter
    kill_rule: bool = False  # explicit stop criteria for pilots that miss their evidence gate
    roi_hurdle: float = 1.5  # evidenced annual benefit required per pound of scaling cost
    abandon_rate: float = 0.04  # quarterly chance a drifting pilot loses its sponsor

    def __post_init__(self) -> None:
        if self.pilots < 1:
            raise ValueError("pilots must be at least 1")
        if not 0.0 <= self.screening <= 0.9:
            raise ValueError("screening must be between 0 and 0.9")
        if self.scaling_capacity < 0:
            raise ValueError("scaling_capacity cannot be negative")
        if self.strategy_quarter < 1:
            raise ValueError("strategy_quarter must be at least 1")
        if not 0.0 <= self.abandon_rate <= 1.0:
            raise ValueError("abandon_rate must be between 0 and 1")


@dataclass
class Pilot:
    """One AI pilot and its hidden true characteristics."""

    value: float  # true annual benefit once scaled, GBP k
    measurability: float  # 0 to 1: how much of that benefit can be evidenced
    complexity: float  # 0 to 1: technical integration difficulty
    time_to_value: int  # quarters before any benefit can be observed
    run_cost: float  # GBP k per quarter while it stays a pilot
    age: int = 0
    spend: float = 0.0
    status: str = "active"
    scaled_in: int = 0
    end_age: int = 0

    @property
    def scaling_cost(self) -> float:
        return SCALING_COST_BASE + SCALING_COST_PER_COMPLEXITY * self.complexity

    @property
    def true_roi(self) -> float:
        return self.value / self.scaling_cost


def draw_pilot(rng: random.Random) -> Pilot:
    """Draw one candidate pilot. Roughly one in five is genuinely worth scaling."""
    complexity = rng.betavariate(2, 2)
    return Pilot(
        value=rng.lognormvariate(math.log(350.0), 0.9),
        measurability=rng.betavariate(2, 2),
        complexity=complexity,
        time_to_value=1 + round(complexity * 4) + rng.randint(0, 2),
        run_cost=rng.uniform(30.0, 90.0),
    )


def effective_measurability(pilot: Pilot, strategy: Strategy) -> float:
    boost = METRICS_UPFRONT_BOOST if strategy.metrics_upfront else 0.0
    return min(1.0, pilot.measurability + boost)


def share_evidenced(pilot: Pilot, strategy: Strategy) -> float:
    """Fraction of a pilot's true benefit that can be put in front of decision makers."""
    return 0.25 + 0.75 * effective_measurability(pilot, strategy)


def expected_evidenced_roi(pilot: Pilot, strategy: Strategy) -> float:
    """The evidenced ROI a pilot would show on average, before measurement noise."""
    return pilot.value * share_evidenced(pilot, strategy) / pilot.scaling_cost


def evidenced_roi(pilot: Pilot, strategy: Strategy, rng: random.Random) -> float:
    """What the organisation can actually prove this quarter.

    Poorly measured pilots can only evidence part of their benefit, and that evidence
    is noisier, so valuable but hard-to-measure pilots often look weak on paper.
    """
    m = effective_measurability(pilot, strategy)
    noise = rng.lognormvariate(0.0, 0.05 + 0.4 * (1.0 - m))
    return expected_evidenced_roi(pilot, strategy) * noise


def launch_portfolio(strategy: Strategy, rng: random.Random) -> List[Pilot]:
    """Generate candidate ideas and keep the ones that pass intake screening."""
    if strategy.screening <= 0.0:
        return [draw_pilot(rng) for _ in range(strategy.pilots)]
    n_candidates = math.ceil(strategy.pilots / (1.0 - strategy.screening))
    candidates = [draw_pilot(rng) for _ in range(n_candidates)]
    # Screening uses a rough, noisy estimate of value, not the hidden truth.
    scored = [(c.true_roi * rng.lognormvariate(0.0, 0.5), i, c) for i, c in enumerate(candidates)]
    scored.sort(key=lambda t: (t[0], -t[1]), reverse=True)
    return [c for _, _, c in scored[: strategy.pilots]]


def blocking_barrier(pilot: Pilot, strategy: Strategy) -> str:
    """Name the main reason a pilot that never scaled got stuck. Rules are deterministic."""
    if pilot.end_age < pilot.time_to_value:
        return LONG_TIMESCALES
    if pilot.true_roi >= strategy.roi_hurdle:
        # Worth scaling. Either its benefit could not be evidenced well enough to clear the
        # hurdle, or the evidence was there and it still had no strategy, owner or capacity.
        if expected_evidenced_roi(pilot, strategy) < strategy.roi_hurdle:
            return HARD_TO_MEASURE
        return NO_ROUTE
    cost_at_reference = SCALING_COST_BASE + SCALING_COST_PER_COMPLEXITY * REFERENCE_COMPLEXITY
    if pilot.complexity > REFERENCE_COMPLEXITY and pilot.value / cost_at_reference >= strategy.roi_hurdle:
        return TECH_COMPLEXITY
    return UNCLEAR_ROI


@dataclass
class RunResult:
    pilots: int
    outcomes: Dict[str, int]
    barriers: Dict[str, int]
    value_captured: float
    pilot_spend: float
    scaling_spend: float
    wasted_spend: float
    missed_opportunities: int
    quarters_to_scale: List[int] = field(default_factory=list)

    @property
    def net_value(self) -> float:
        return self.value_captured - self.pilot_spend - self.scaling_spend


def simulate_once(strategy: Strategy, rng: random.Random, quarters: int = 12) -> RunResult:
    """Run one portfolio of pilots through a fixed horizon of quarters."""
    if quarters < 1:
        raise ValueError("quarters must be at least 1")
    portfolio = launch_portfolio(strategy, rng)
    value_captured = 0.0
    scaling_spend = 0.0

    for quarter in range(1, quarters + 1):
        eligible = []
        for pilot in portfolio:
            if pilot.status != "active":
                continue
            pilot.age += 1
            pilot.spend += pilot.run_cost
            has_evidence = pilot.age >= pilot.time_to_value
            if has_evidence:
                roi = evidenced_roi(pilot, strategy, rng)
                if quarter >= strategy.strategy_quarter and roi >= strategy.roi_hurdle:
                    eligible.append((roi, pilot))
                    continue
                if strategy.kill_rule and pilot.age >= pilot.time_to_value + KILL_GRACE_QUARTERS:
                    pilot.status = "killed"
                    pilot.end_age = pilot.age
                    continue
            if not strategy.kill_rule and rng.random() < strategy.abandon_rate:
                pilot.status = "killed"
                pilot.end_age = pilot.age

        # Limited capacity: the strongest cases go first, the rest wait in the queue.
        eligible.sort(key=lambda t: t[0], reverse=True)
        for _, pilot in eligible[: strategy.scaling_capacity]:
            pilot.status = "scaled"
            pilot.scaled_in = quarter
            pilot.end_age = pilot.age
            scaling_spend += pilot.scaling_cost
            value_captured += pilot.value / 4.0 * (quarters - quarter)

    outcomes = {o: 0 for o in OUTCOMES}
    barriers = {b: 0 for b in BARRIERS}
    wasted = 0.0
    missed = 0
    to_scale = []
    for pilot in portfolio:
        if pilot.status == "scaled":
            outcomes[SCALED] += 1
            to_scale.append(pilot.scaled_in)
            continue
        if pilot.status == "active":
            pilot.end_age = pilot.age
            outcomes[PURGATORY] += 1
        else:
            outcomes[KILLED] += 1
        barriers[blocking_barrier(pilot, strategy)] += 1
        wasted += pilot.spend
        if pilot.true_roi >= strategy.roi_hurdle:
            missed += 1

    return RunResult(
        pilots=len(portfolio),
        outcomes=outcomes,
        barriers=barriers,
        value_captured=value_captured,
        pilot_spend=sum(p.spend for p in portfolio),
        scaling_spend=scaling_spend,
        wasted_spend=wasted,
        missed_opportunities=missed,
        quarters_to_scale=to_scale,
    )


@dataclass(frozen=True)
class Spread:
    mean: float
    p10: float
    p90: float


def _spread(values: Sequence[float]) -> Spread:
    if len(values) == 1:
        v = float(values[0])
        return Spread(v, v, v)
    deciles = statistics.quantiles(values, n=10, method="inclusive")
    return Spread(statistics.fmean(values), deciles[0], deciles[8])


@dataclass(frozen=True)
class Summary:
    strategy: Strategy
    runs: int
    quarters: int
    outcome_share: Dict[str, float]
    barrier_share: Dict[str, float]
    net_value: Spread
    value_captured: float
    pilot_spend: float
    wasted_spend: float
    missed_opportunities: float
    median_quarters_to_scale: float


def simulate(strategy: Strategy, runs: int = 500, quarters: int = 12, seed: int = 42) -> Summary:
    """Monte Carlo over many portfolios. Run i always uses the same seed for every strategy."""
    if runs < 1:
        raise ValueError("runs must be at least 1")
    results = [simulate_once(strategy, random.Random(seed * 1_000_003 + i), quarters) for i in range(runs)]

    total_pilots = sum(r.pilots for r in results)
    outcome_share = {o: sum(r.outcomes[o] for r in results) / total_pilots for o in OUTCOMES}
    not_scaled = sum(r.pilots - r.outcomes[SCALED] for r in results)
    barrier_share = {
        b: (sum(r.barriers[b] for r in results) / not_scaled if not_scaled else 0.0) for b in BARRIERS
    }
    all_to_scale = [q for r in results for q in r.quarters_to_scale]

    return Summary(
        strategy=strategy,
        runs=runs,
        quarters=quarters,
        outcome_share=outcome_share,
        barrier_share=barrier_share,
        net_value=_spread([r.net_value for r in results]),
        value_captured=statistics.fmean(r.value_captured for r in results),
        pilot_spend=statistics.fmean(r.pilot_spend for r in results),
        wasted_spend=statistics.fmean(r.wasted_spend for r in results),
        missed_opportunities=statistics.fmean(r.missed_opportunities for r in results),
        median_quarters_to_scale=statistics.median(all_to_scale) if all_to_scale else float("nan"),
    )
