"""Crutch check: does an AI scam checker sharpen people's judgement, or stand in for it?

The browser app (app/index.html) runs the test. This package scores the
sessions it exports, simulates participants and analyses whole studies.
"""

from .model import (
    BANK, CUES, MESSAGES, PERSONAS, PROFILES, assign_arm, build_session, default_design,
    participant_seed, score_session, simulate_responses, validate_session,
)

__all__ = [
    "BANK", "CUES", "MESSAGES", "PERSONAS", "PROFILES", "assign_arm", "build_session",
    "default_design", "participant_seed", "score_session", "simulate_responses",
    "validate_session",
]
