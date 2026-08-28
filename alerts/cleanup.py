"""Compatibility alias for :mod:`alerts.services.cleanup`."""

import sys

from .services import cleanup as _module

sys.modules[__name__] = _module
