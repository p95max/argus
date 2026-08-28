"""Compatibility alias for :mod:`alerts.services.cases`."""

import sys

from .services import cases as _module

sys.modules[__name__] = _module
