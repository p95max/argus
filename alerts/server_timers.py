"""Compatibility alias for :mod:`alerts.monitoring.server_timers`."""

import sys

from .monitoring import server_timers as _module

sys.modules[__name__] = _module
