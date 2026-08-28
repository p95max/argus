"""Compatibility alias for :mod:`alerts.services.classifier`."""

import sys

from .services import classifier as _module

sys.modules[__name__] = _module
