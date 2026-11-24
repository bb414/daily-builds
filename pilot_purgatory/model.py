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
from typing import Dict, List, Optional, Sequence

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
IN_PROGRESS = "Still in progress"
OUTCOMES = (SCALED, KILLED, PURGATORY, IN_PROGRESS)

KILL_GRACE_QUARTERS = 2  # quarters after first evidence before a stop rule bites
REFERENCE_COMPLEXITY = 0.5  # "average" complexity used to test whether complexity was binding


@dataclass(frozen=True)
class Assumptions:
    """The world the organisations operate in. Shared by every strategy in a comparison."""

    value_median: float = 350.0  # median annual benefit of a pilot once scaled, GBP k
    value_spread: float = 0.9  # log-normal spread of that benefit (higher = longer tail)
    scaling_cost_base: float = 150.0  # one-off cost to productionise the simplest pilot
    scaling_cost_per_complexity: float = 650.0  # extra cost for the most complex pilot
    metrics_boost: float = 0.3  # gain in measurability when success metrics are agreed first
    measurement_noise: float = 1.0  # multiplier on how noisy evidence is
    purgatory_age: int = 4  # quarters as a pilot before an unscaled pilot counts as stuck
    launch_cutoff: int = 4  # recycled budget is not used in the final quarters of the horizon
    platform_floor: float = 0.5  # platform effects can cut scaling costs to no less than this share

    def __post_init__(self) -> None:
        if self.value_median <= 0 or self.value_spread < 0:
            raise ValueError("value_median must be positive and value_spread non-negative")
        if self.scaling_cost_base <= 0 or self.scaling_cost_per_complexity < 0:
            raise ValueError("scaling costs must be positive")
        if not 0.0 <= self.metrics_boost <= 1.0:
            raise ValueError("metrics_boost must be between 0 and 1")
        if self.measurement_noise < 0:
            raise ValueError("measurement_noise cannot be negative")
        if self.purgatory_age < 1 or self.launch_cutoff < 0:
            raise ValueError("purgatory_age must be at least 1 and launch_cutoff non-negative")
        if not 0.0 < self.platform_floor <= 1.0:
            raise ValueError("platform_floor must be above 0 and at most 1")

    def scaling_cost(self, complexity: float) -> float:
        return self.scaling_cost_base + self.scaling_cost_per_complexity * complexity


DEFAULT_ASSUMPTIONS = Assumptions()


@dataclass(frozen=True)
class Strategy:
    """How an organisation runs its AI pilot portfolio."""

    name: str
    pilots: int = 20  # pilots launched at the start
    screening: float = 0.0  # share of candidate ideas screened out at intake (0 to 0.9)
    metrics_upfront: bool = False  # success metrics agreed before each pilot starts
    strategy_quarter: int = 5  # first quarter in which a strategy and scaling owner exist
    scaling_capacity: int = 1  # pilots that can be moved to production per quarter
    kill_rule: bool = False  # explicit stop criteria for pilots that miss their evidence gate
    recycle_budget: bool = False  # budget freed by a stopped or scaled pilot funds a new one
    platform_effect: float = 0.0  # each scaled pilot cuts later scaling costs by this share
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
        if not 0.0 <= self.platform_effect <= 0.5:
            raise ValueError("platform_effect must be between 0 and 0.5")
        if self.roi_hurdle <= 0:
            raise ValueError("roi_hurdle must be positive")
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
    scaling_cost: float  # one-off GBP k cost to productionise, before platform effects
    launched_in: int = 1
    age: int = 0
    spend: float = 0.0
    status: str = "active"
    scaled_in: int = 0
    end_age: int = 0

    @property
    def true_roi(self) -> float:
        return self.value / self.scaling_cost


def draw_pilot(rng: random.Random, assumptions: Assumptions = DEFAULT_ASSUMPTIONS) -> Pilot:
    """Draw one candidate pilot. Under the defaults roughly one in five is worth scaling."""
    complexity = rng.betavariate(2, 2)
    return Pilot(
        value=rng.lognormvariate(math.log(assumptions.value_median), assumptions.value_spread),
        measurability=rng.betavariate(2, 2),
        complexity=complexity,
        time_to_value=1 + round(complexity * 4) + rng.randint(0, 2),
        run_cost=rng.uniform(30.0, 90.0),
        scaling_cost=assumptions.scaling_cost(complexity),
    )


def effective_measurability(pilot: Pilot, strategy: Strategy, assumptions: Assumptions = DEFAULT_ASSUMPTIONS) -> float:
    boost = assumptions.metrics_boost if strategy.metrics_upfront else 0.0
    return min(1.0, pilot.measurability + boost)


def share_evidenced(pilot: Pilot, strategy: Strategy, assumptions: Assumptions = DEFAULT_ASSUMPTIONS) -> float:
    """Fraction of a pilot's true benefit that can be put in front of decision makers."""
    return 0.25 + 0.75 * effective_measurability(pilot, strategy, assumptions)


def expected_evidenced_roi(
    pilot: Pilot, strategy: Strategy, assumptions: Assumptions = DEFAULT_ASSUMPTIONS, cost_multiplier: float = 1.0
) -> float:
    """The evidenced ROI a pilot would show on average, before measurement noise."""
    return pilot.value * share_evidenced(pilot, strategy, assumptions) / (pilot.scaling_cost * cost_multiplier)


def evidenced_roi(
    pilot: Pilot,
    strategy: Strategy,
    rng: random.Random,
    assumptions: Assumptions = DEFAULT_ASSUMPTIONS,
    cost_multiplier: float = 1.0,
) -> float:
    """What the organisation can actually prove this quarter.

    Poorly measured pilots can only evidence part of their benefit, and that evidence
    is noisier, so valuable but hard-to-measure pilots often look weak on paper.
    """
    m = effective_measurability(pilot, strategy, assumptions)
    noise = rng.lognormvariate(0.0, (0.05 + 0.4 * (1.0 - m)) * assumptions.measurement_noise)
    return expected_evidenced_roi(pilot, strategy, assumptions, cost_multiplier) * noise


def launch_portfolio(
    strategy: Strategy,
    rng: random.Random,
    count: Optional[int] = None,
    assumptions: Assumptions = DEFAULT_ASSUMPTIONS,
) -> List[Pilot]:
    """Generate candidate ideas and keep the ones that pass intake screening."""
    n = strategy.pilots if count is None else count
    if n <= 0:
        return []
    if strategy.screening <= 0.0:
        return [draw_pilot(rng, assumptions) for _ in range(n)]
    n_candidates = math.ceil(n / (1.0 - strategy.screening))
    candidates = [draw_pilot(rng, assumptions) for _ in range(n_candidates)]
    # Screening uses a rough, noisy estimate of value, not the hidden truth.
    scored = [(c.true_roi * rng.lognormvariate(0.0, 0.5), i, c) for i, c in enumerate(candidates)]
    scored.sort(key=lambda t: (t[0], -t[1]), reverse=True)
    return [c for _, _, c in scored[:n]]


def blocking_barrier(pilot: Pilot, strategy: Strategy, assumptions: Assumptions = DEFAULT_ASSUMPTIONS) -> str:
    """Name the main reason a stalled pilot never scaled. Rules are deterministic.

    "Worth scaling" is judged at the pilot's own scaling cost before any platform effects,
    so the attribution does not depend on what happened to other pilots.
    """
    if pilot.end_age < pilot.time_to_value:
        return LONG_TIMESCALES
    if pilot.true_roi >= strategy.roi_hurdle:
        # Worth scaling. Either its benefit could not be evidenced well enough to clear the
        # hurdle, or the evidence was there and it still had no strategy, owner or capacity.
        if expected_evidenced_roi(pilot, strategy, assumptions) < strategy.roi_hurdle:
            return HARD_TO_MEASURE
        return NO_ROUTE
    reference_cost = assumptions.scaling_cost(REFERENCE_COMPLEXITY)
    if pilot.complexity > REFERENCE_COMPLEXITY and pilot.value / reference_cost >= strategy.roi_hurdle:
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


def simulate_once(
    strategy: Strategy,
    rng: random.Random,
    quarters: int = 12,
    assumptions: Assumptions = DEFAULT_ASSUMPTIONS,
) -> RunResult:
    """Run one portfolio of pilots through a fixed horizon of quarters."""
    if quarters < 1:
        raise ValueError("quarters must be at least 1")
    portfolio = launch_portfolio(strategy, rng, assumptions=assumptions)
    value_captured = 0.0
    scaling_spend = 0.0
    run_rate = 0.0  # quarterly benefit from pilots already in production
    cost_multiplier = 1.0
    scaled_so_far = 0
    freed_slots = 0

    for quarter in range(1, quarters + 1):
        value_captured += run_rate

        if strategy.recycle_budget and freed_slots and quarter <= quarters - assumptions.launch_cutoff:
            for pilot in launch_portfolio(strategy, rng, freed_slots, assumptions):
                pilot.launched_in = quarter
                portfolio.append(pilot)
        freed_slots = 0

        eligible = []
        for pilot in portfolio:
            if pilot.status != "active":
                continue
            pilot.age += 1
            pilot.spend += pilot.run_cost
            if pilot.age >= pilot.time_to_value:
                roi = evidenced_roi(pilot, strategy, rng, assumptions, cost_multiplier)
                if quarter >= strategy.strategy_quarter and roi >= strategy.roi_hurdle:
                    eligible.append((roi, pilot))
                    continue
                if strategy.kill_rule and pilot.age >= pilot.time_to_value + KILL_GRACE_QUARTERS:
                    pilot.status = "killed"
                    pilot.end_age = pilot.age
                    freed_slots += 1
                    continue
            if not strategy.kill_rule and rng.random() < strategy.abandon_rate:
                pilot.status = "killed"
                pilot.end_age = pilot.age
                freed_slots += 1

        # Limited capacity: the strongest cases go first, the rest wait in the queue.
        eligible.sort(key=lambda t: t[0], reverse=True)
        for _, pilot in eligible[: strategy.scaling_capacity]:
            pilot.status = "scaled"
            pilot.scaled_in = quarter
            pilot.end_age = pilot.age
            scaling_spend += pilot.scaling_cost * cost_multiplier
            run_rate += pilot.value / 4.0
            scaled_so_far += 1
            freed_slots += 1
            cost_multiplier = max(assumptions.platform_floor, (1.0 - strategy.platform_effect) ** scaled_so_far)

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
            if pilot.age < assumptions.purgatory_age:
                outcomes[IN_PROGRESS] += 1  # too young to call stuck
                continue
            outcomes[PURGATORY] += 1
        else:
            outcomes[KILLED] += 1
        barriers[blocking_barrier(pilot, strategy, assumptions)] += 1
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
    pilots_launched: float
    outcome_share: Dict[str, float]
    barrier_share: Dict[str, float]
    net_value: Spread
    value_captured: float
    pilot_spend: float
    wasted_spend: float
    missed_opportunities: float
    median_quarters_to_scale: float


def simulate(
    strategy: Strategy,
    runs: int = 500,
    quarters: int = 12,
    seed: int = 42,
    assumptions: Assumptions = DEFAULT_ASSUMPTIONS,
) -> Summary:
    """Monte Carlo over many portfolios. Run i always uses the same seed for every strategy."""
    if runs < 1:
        raise ValueError("runs must be at least 1")
    results = [
        simulate_once(strategy, random.Random(seed * 1_000_003 + i), quarters, assumptions) for i in range(runs)
    ]

    total_pilots = sum(r.pilots for r in results)
    outcome_share = {o: sum(r.outcomes[o] for r in results) / total_pilots for o in OUTCOMES}
    stalled = sum(r.outcomes[KILLED] + r.outcomes[PURGATORY] for r in results)
    barrier_share = {b: (sum(r.barriers[b] for r in results) / stalled if stalled else 0.0) for b in BARRIERS}
    all_to_scale = [q for r in results for q in r.quarters_to_scale]

    return Summary(
        strategy=strategy,
        runs=runs,
        quarters=quarters,
        pilots_launched=total_pilots / runs,
        outcome_share=outcome_share,
        barrier_share=barrier_share,
        net_value=_spread([r.net_value for r in results]),
        value_captured=statistics.fmean(r.value_captured for r in results),
        pilot_spend=statistics.fmean(r.pilot_spend for r in results),
        wasted_spend=statistics.fmean(r.wasted_spend for r in results),
        missed_opportunities=statistics.fmean(r.missed_opportunities for r in results),
        median_quarters_to_scale=statistics.median(all_to_scale) if all_to_scale else float("nan"),
    )
