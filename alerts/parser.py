"""Compatibility alias for :mod:`alerts.services.parser`."""

import sys

from .services import parser as _module

sys.modules[__name__] = _module
