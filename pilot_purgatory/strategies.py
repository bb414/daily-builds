"""Two archetypal ways of running AI pilots, and the individual levers that separate them."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable, Dict

from .model import Strategy

# Pilots first: lots of enthusiasm, little structure. The strategy is written after the
# pilots are already running, nobody agreed what success looks like, there is one small
# team to productionise anything, and pilots are rarely stopped on purpose.
MOMENTUM = Strategy(
    name="Pilots first (momentum-driven)",
    pilots=20,
    screening=0.0,
    metrics_upfront=False,
    strategy_quarter=5,
    scaling_capacity=1,
    kill_rule=False,
)

# Strategy first: fewer, better-chosen pilots with success metrics agreed up front, a
# strategy and scaling owner from day one, more capacity to productionise, and explicit
# stop criteria so weak pilots free up budget instead of drifting.
GOVERNANCE = Strategy(
    name="Strategy first (governance-driven)",
    pilots=12,
    screening=0.5,
    metrics_upfront=True,
    strategy_quarter=1,
    scaling_capacity=2,
    kill_rule=True,
)

PRESETS: Dict[str, Strategy] = {"momentum": MOMENTUM, "governance": GOVERNANCE}

# Each lever applies one governance practice to a given strategy, leaving everything else alone.
LEVERS: Dict[str, Callable[[Strategy], Strategy]] = {
    "Screen ideas at intake": lambda s: replace(s, screening=GOVERNANCE.screening),
    "Agree success metrics up front": lambda s: replace(s, metrics_upfront=True),
    "Write the strategy before the pilots": lambda s: replace(s, strategy_quarter=1),
    "Double scaling capacity": lambda s: replace(s, scaling_capacity=max(1, s.scaling_capacity * 2)),
    "Add explicit stop criteria": lambda s: replace(s, kill_rule=True),
}
