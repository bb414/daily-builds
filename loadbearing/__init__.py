"""Load bearing: the Python companion to the model in app/index.html, with bit-identical results."""
from . import model
from .model import *  # noqa: F401,F403 (the public API is model.__all__)

__all__ = list(model.__all__)
__version__ = '1.0'
