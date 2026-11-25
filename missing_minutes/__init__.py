"""Missing minutes: follow the minutes an AI saves at one desk through a whole process.

A discrete-event simulation of a multi-step process, run without and with an
AI assistant on one step, using the same cases and the same luck. It is a
line-for-line port of the model inside app/index.html.
"""

from .model import (DAY, PRESETS, compare, normalise, preset_config, simulate,
                    validate)

__all__ = ["DAY", "PRESETS", "compare", "normalise", "preset_config", "simulate", "validate"]
