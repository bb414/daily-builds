"""Pilot purgatory simulator: why AI pilots stall before they scale."""

from .model import BARRIERS, OUTCOMES, Strategy, Summary, simulate, simulate_once
from .strategies import GOVERNANCE, LEVERS, MOMENTUM, PRESETS

__all__ = [
    "BARRIERS",
    "OUTCOMES",
    "Strategy",
    "Summary",
    "simulate",
    "simulate_once",
    "GOVERNANCE",
    "LEVERS",
    "MOMENTUM",
    "PRESETS",
]
__version__ = "1.0.0"
