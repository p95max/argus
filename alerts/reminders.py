"""Compatibility alias for :mod:`alerts.services.reminders`."""

import sys

from .services import reminders as _module

sys.modules[__name__] = _module
