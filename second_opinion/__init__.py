"""Second opinion: score and pool results from a test of how well people use an AI checker's advice."""

from .design import ITEMS, build_session
from .metrics import score, validate_session

__all__ = ["ITEMS", "build_session", "score", "validate_session"]
__version__ = "1.0.0"
