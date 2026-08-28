"""Compatibility alias for :mod:`alerts.monitoring.health`."""

import sys

from .monitoring import health as _module

sys.modules[__name__] = _module
